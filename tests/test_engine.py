"""Engine (prepare/resume state machine) tests — zero LLM calls.

Results are injected as raw agent-output texts, exactly what the
judge-manager driver would write into ``results/<id>.md``."""

from __future__ import annotations

from fixtures.helpers import (
    VERDICT_JSON_SATISFIED,
    VERDICT_JSON_UNSATISFIED,
    make_config,
)
from agent_judges.engine import (
    META_REVIEWERS,
    advance,
    build_result,
    build_route_decision,
    prepare_fixed,
    prepare_progressive,
)
from agent_judges.run_state import (
    RunState,
    Stage,
    load_state,
    save_state,
)
from agent_judges.types import Severity
from agent_judges.utils.truncate import count_tokens

PANEL = ("spec-reviewer", "design-reviewer", "test-plan-reviewer")

MAJOR_VERDICT_JSON = """```json
{"severity": "major", "confidence": 0.85, "reasoning": "r",
 "findings": [{"description": "d", "severity": "major", "confidence": 0.7,
   "evidence": "e", "suggestion": "s"}],
 "satisfied": false}
```"""

META_VERDICT_JSON = """```json
{"severity": "major", "confidence": 0.8, "reasoning": "meta",
 "findings": [], "satisfied": false, "confidence_adjustment": -0.2}
```"""


def _configs(**overrides):
    names = list(PANEL) + list(META_REVIEWERS)
    cfgs = {n: make_config(n) for n in names}
    for name, cfg in overrides.items():
        cfgs[name] = cfg
    return cfgs


def _prepare(content="短内容审查目标", **kwargs):
    defaults = dict(
        content=content,
        context=None,
        filename=None,
        configs=_configs(),
        available=list(PANEL),
        threshold=0.8,
        max_tier="thorough",
    )
    defaults.update(kwargs)
    return prepare_progressive(**defaults)


class TestPrepare:
    def test_short_content_starts_sentinel(self):
        state, tasks = _prepare()
        assert state.stage == Stage.AWAITING_SENTINEL
        assert state.gated is True
        assert state.start_panel == 1
        assert len(tasks) == 1
        assert tasks[0].agent == PANEL[0]
        assert tasks[0].task_id == f"p1-{PANEL[0]}-v1"
        # the prompt carries content + checklist + output protocol
        assert "短内容审查目标" in tasks[0].prompt
        assert "检查清单" in tasks[0].prompt
        assert "输出要求" in tasks[0].prompt

    def test_long_content_starts_full_panel(self):
        content = "详细规格内容 "
        while count_tokens(content) < 8100:
            content *= 2
        state, tasks = _prepare(content=content)
        assert state.stage == Stage.AWAITING_PANEL
        assert state.start_panel == 3
        assert len(tasks) == 3
        assert {t.agent for t in tasks} == set(PANEL)

    def test_fixed_prepare_full_panel(self):
        cfgs = _configs()
        state, tasks = prepare_fixed(
            content="x", context=None, filename=None, configs=cfgs,
            panel=["spec-reviewer"], debate_rounds=0, review_depth=0,
        )
        assert state.gated is False
        assert state.stage == Stage.AWAITING_PANEL
        assert len(tasks) == 1

    def test_majority_vote_emits_vote_tasks(self):
        cfgs = _configs(**{"spec-reviewer": make_config("spec-reviewer", majority_vote=3)})
        state, tasks = _prepare(configs=cfgs)
        assert len(tasks) == 3
        assert [t.task_id for t in tasks] == [
            "p1-spec-reviewer-v1", "p1-spec-reviewer-v2", "p1-spec-reviewer-v3"
        ]

    def test_content_hint_selects_sentinel(self):
        # filename hint routes the sentinel to the matching reviewer
        cfgs = _configs()
        state, tasks = _prepare(filename="spec.md", configs=cfgs)
        assert tasks[0].agent == "spec-reviewer"


class TestProgressiveFlow:
    def test_early_stop_on_clean_sentinel(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        state, tasks = advance(
            state, {f"p1-{PANEL[0]}-v1": VERDICT_JSON_SATISFIED}, cfgs
        )
        assert state.stage == Stage.DONE
        assert tasks == []
        assert state.early_stopped is True
        assert state.tier == "fast"
        assert state.verdict.severity == Severity.PASS
        assert state.verdict.escalate_to_human is False  # 0.92 >= 0.8
        result = build_result(state)
        assert result.stability_degraded is True
        assert result.conformity_warnings == []  # early stop = no Phase 3
        route = build_route_decision(state)
        assert route.profile == "fast"
        assert route.early_stopped is True
        # (B-4 fix) early stop reports exactly the reviewers that actually
        # ran (the sentinel), never the full pre-planned panel
        assert route.reviewer_names == [PANEL[0]]
        assert "早停" in route.reason

    def test_sentinel_low_confidence_expands(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        low = VERDICT_JSON_SATISFIED.replace("0.92", "0.70")
        state, tasks = advance(state, {f"p1-{PANEL[0]}-v1": low}, cfgs)
        assert state.stage == Stage.AWAITING_PANEL
        assert {t.agent for t in tasks} == {"design-reviewer", "test-plan-reviewer"}
        # sentinel verdict kept
        assert PANEL[0] in state.individual

    def test_missing_results_reemit(self):
        cfgs = _configs()
        state, first = _prepare(configs=cfgs)
        # advance with NO results: same task re-emitted, stage unchanged
        state, tasks = advance(state, {}, cfgs)
        assert state.stage == Stage.AWAITING_SENTINEL
        assert [t.task_id for t in tasks] == [first[0].task_id]

    def test_empty_result_degrades_to_failed_verdict(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        state, tasks = advance(state, {f"p1-{PANEL[0]}-v1": ""}, cfgs)
        # failed sentinel (conf 0.0) fails gate 1 → expansion, not a crash
        assert state.stage == Stage.AWAITING_PANEL
        assert len(tasks) == 2

    def test_thorough_path_with_meta_calibration(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        results: dict[str, str] = {}

        # 1) sentinel fails gate 1 (critical finding)
        state, tasks = advance(
            state, {f"p1-{PANEL[0]}-v1": VERDICT_JSON_UNSATISFIED}, cfgs
        )
        assert state.stage == Stage.AWAITING_PANEL

        # 2) panel expansion fails too → gate 2: critical → thorough
        for t in tasks:
            results[t.task_id] = VERDICT_JSON_UNSATISFIED
        state, tasks = advance(state, results, cfgs)
        assert state.tier == "thorough"
        assert state.planned_debate_rounds == 2
        assert state.planned_review_depth == 1
        assert len(tasks) == 3  # debate round 1
        assert all(t.kind.value == "debate" for t in tasks)

        # 3) debate round 1
        for t in tasks:
            results[t.task_id] = "我坚持存在量化指标缺失问题"
        state, tasks = advance(state, results, cfgs)
        assert len(tasks) == 3  # debate round 2
        assert tasks[0].task_id.startswith("deb-r2-")

        # 4) debate round 2 → blind final
        for t in tasks:
            results[t.task_id] = "维持原判"
        state, tasks = advance(state, results, cfgs)
        assert all(t.kind.value == "blind_final" for t in tasks)

        # 5) blind finals → meta Phase-1 tasks (thorough: depth 1)
        for t in tasks:
            results[t.task_id] = VERDICT_JSON_UNSATISFIED
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.AWAITING_META
        assert {t.agent for t in tasks} == set(META_REVIEWERS)
        assert state.verdict is not None
        assert state.stability_score == 1.0  # nobody flipped

        # 6) meta Phase-1 → meta debate round (B-2 fix: full 4-phase meta)
        for t in tasks:
            results[t.task_id] = META_VERDICT_JSON
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.AWAITING_META_DEBATE
        assert len(tasks) == 2  # one debate task per meta reviewer
        assert all(t.kind.value == "meta_debate" for t in tasks)
        assert tasks[0].task_id.startswith("meta-deb-r1-")

        # 7) meta debate → meta blind finals
        for t in tasks:
            results[t.task_id] = "元审查辩论:坚持存在漏判"
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.AWAITING_META_FINAL
        assert len(tasks) == 2
        assert all(t.kind.value == "meta_blind_final" for t in tasks)
        assert tasks[0].task_id.startswith("meta-fin-1-")

        # 8) meta blind finals → calibration + finalize
        for t in tasks:
            results[t.task_id] = META_VERDICT_JSON
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.DONE
        assert tasks == []
        v = state.verdict
        # explicit formula: 0.85 × (1 − 0.3) = 0.595; adjustment −0.2 blend:
        # adjusted = clamp(0.85 − 0.2) = 0.65 → (0.595 + 0.65) / 2 = 0.6225
        assert v.calibrated_confidence == 0.6225
        assert v.escalate_to_human is True  # 0.6225 < 0.8
        assert v.severity == Severity.CRITICAL
        result = build_result(state)
        assert len(result.debate_rounds) == 2
        assert len(result.individual_verdicts) == 3
        # build_result must propagate conformity_warnings from RunState
        assert result.conformity_warnings == state.conformity_warnings
        # meta synthesis draws from the blind finals (same canned text)
        assert state.meta_verdict is not None
        assert state.meta_verdict.severity == Severity.MAJOR
        route = build_route_decision(state)
        assert route.profile == "thorough"
        assert "thorough 续跑" in route.reason

    def test_standard_path_major_only(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        results = {f"p1-{PANEL[0]}-v1": MAJOR_VERDICT_JSON}
        state, tasks = advance(state, results, cfgs)
        for t in tasks:
            results[t.task_id] = MAJOR_VERDICT_JSON
        state, tasks = advance(state, results, cfgs)
        assert state.tier == "standard"
        assert state.planned_debate_rounds == 1
        for t in tasks:  # debate r1
            results[t.task_id] = "argue"
        state, tasks = advance(state, results, cfgs)
        assert all(t.kind.value == "blind_final" for t in tasks)  # 1 round only
        for t in tasks:
            results[t.task_id] = MAJOR_VERDICT_JSON
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.DONE
        assert state.planned_review_depth == 0
        assert state.verdict.severity == Severity.MAJOR
        assert state.verdict.escalate_to_human is False  # 0.85 >= 0.8

    def test_max_tier_clamps_to_standard(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs, max_tier="standard")
        results = {f"p1-{PANEL[0]}-v1": VERDICT_JSON_UNSATISFIED}
        state, tasks = advance(state, results, cfgs)
        for t in tasks:
            results[t.task_id] = VERDICT_JSON_UNSATISFIED
        state, tasks = advance(state, results, cfgs)
        assert state.tier == "standard"  # clamped from thorough
        assert state.planned_review_depth == 0

    def test_majority_vote_aggregation(self):
        # fixed single-reviewer flow: no gates, pure AaaJ vote formula
        voter = make_config("spec-reviewer", majority_vote=3)
        cfgs = _configs(**{"spec-reviewer": voter})
        state, tasks = prepare_fixed(
            content="x", context=None, filename=None, configs=cfgs,
            panel=["spec-reviewer"], debate_rounds=0, review_depth=0,
        )
        assert len(tasks) == 3
        # 2 of 3 votes satisfied → majority satisfied, conf = max(2/3, 1/3)
        results = {
            "p1-spec-reviewer-v1": VERDICT_JSON_SATISFIED,
            "p1-spec-reviewer-v2": VERDICT_JSON_SATISFIED,
            "p1-spec-reviewer-v3": VERDICT_JSON_UNSATISFIED,
        }
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.DONE
        # AaaJ vote formula on the panel verdict: conf = max(2/3, 1/3)
        assert state.individual["spec-reviewer"].satisfied is True
        assert state.individual["spec-reviewer"].confidence == 0.6667
        # synthesis is severity-driven (same as the legacy direct path):
        # the dissenting critical vote makes the overall verdict unsatisfied
        assert state.verdict.satisfied is False
        assert state.verdict.severity == Severity.CRITICAL
        assert state.verdict.confidence == 0.6667  # 1:1 weight pairing


class TestFixedFlow:
    def test_single_reviewer_fast_check(self):
        cfgs = _configs()
        state, _ = prepare_fixed(
            content="x", context=None, filename=None, configs=cfgs,
            panel=["spec-reviewer"], debate_rounds=0, review_depth=0,
        )
        state, tasks = advance(
            state, {"p1-spec-reviewer-v1": MAJOR_VERDICT_JSON}, cfgs
        )
        assert state.stage == Stage.DONE
        assert tasks == []
        assert state.verdict.severity == Severity.MAJOR
        assert state.stability_degraded is True
        route = build_route_decision(state)
        assert route.profile == "fast"
        assert "显式参数" in route.reason

    def test_fixed_manual_full_debate(self):
        cfgs = _configs()
        state, tasks = prepare_fixed(
            content="x", context=None, filename=None, configs=cfgs,
            panel=list(PANEL), debate_rounds=2, review_depth=0,
        )
        results = {t.task_id: MAJOR_VERDICT_JSON for t in tasks}
        state, tasks = advance(state, results, cfgs)
        assert state.tier == "thorough"
        assert len(tasks) == 3  # debate r1
        for t in tasks:
            results[t.task_id] = "argue"
        state, tasks = advance(state, results, cfgs)
        assert tasks[0].task_id.startswith("deb-r2-")
        for t in tasks:
            results[t.task_id] = "argue"
        state, tasks = advance(state, results, cfgs)
        for t in tasks:  # blind finals
            results[t.task_id] = MAJOR_VERDICT_JSON
        # agent-mode reviewers see ONLY the task prompt → it must carry the
        # JSON output protocol (regression: prose answers degrade to conf 0.0)
        assert all("```json" in t.prompt for t in tasks)
        state, tasks = advance(state, results, cfgs)
        assert state.stage == Stage.DONE  # depth 0 → no meta
        assert state.meta_verdict is None


class TestPersistence:
    def test_state_roundtrip(self, tmp_path):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        state.individual[PANEL[0]] = state.individual.get(PANEL[0]) or _any_verdict()
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        assert loaded == state

    def test_done_state_advance_is_noop(self):
        cfgs = _configs()
        state, _ = _prepare(configs=cfgs)
        state, _ = advance(state, {f"p1-{PANEL[0]}-v1": VERDICT_JSON_SATISFIED}, cfgs)
        assert state.stage == Stage.DONE
        state2, tasks = advance(state, {}, cfgs)
        assert state2.stage == Stage.DONE
        assert tasks == []


def _any_verdict():
    from fixtures.helpers import make_verdict

    return make_verdict(Severity.MAJOR)
