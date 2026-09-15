"""Prepare/resume engine: the deterministic state-machine core (FR-11).

Two entry flavours share one ``advance`` stage machine:

- **progressive (gated)** — zero flow params: deterministic start rule
  (token count → sentinel or full panel), then the two pure-rule gates
  from :mod:`adversarial_judge.progressive` decide early stop / escalation
- **fixed** — explicit ``-r`` / ``--profile`` params: full panel from the
  start, fixed debate rounds and review depth, gates disabled

``advance(state, results, configs)`` is a pure transition: it consumes
driver-written raw agent outputs (``results``), reuses the existing
gates / synthesis / parsing / prompt builders without modification, and
emits the next batch of agent tasks or reaches the terminal ``done``
stage. The judge-manager driver never makes flow decisions (AGENTS.md 1.2).
"""

from __future__ import annotations

import logging

from .consensus import (
    aggregate_majority_votes,
    compute_consensus,
    compute_stability,
    detect_conformity,
    failed_verdict,
    synthesize_verdict,
)
from .debate import DebateResult
from .evidence import enrich_context
from .escalation import EscalationRouter
from .judge import parse_verdict
from .meta_review import (
    calibrate_confidence,
    serialize_verdict,
)
from .prompts.debate import (
    build_blind_final_system_prompt,
    build_blind_final_user_prompt,
    build_debate_system_prompt,
    build_debate_user_prompt,
)
from .prompts.judge_system import build_system_prompt
from .prompts.judge_user import build_judge_prompt
from .progressive import (
    TIER_RANK,
    escalation_tier,
    should_early_stop,
    start_panel_size,
)
from .reviewer import ReviewerConfig
from .router import (
    PROFILE_MAP,
    RouteDecision,
    deterministic_panel,
    filter_by_scene,
    infer_scene_from_filename,
)
from .run_state import (
    AgentTask,
    DebateRound,
    RunState,
    Stage,
    TaskKind,
)
from .types import Verdict
from .utils.truncate import count_tokens

logger = logging.getLogger(__name__)

__all__ = [
    "prepare_progressive",
    "prepare_fixed",
    "advance",
    "build_result",
    "build_route_decision",
    "META_REVIEWERS",
]

#: meta-reviewer agent names (must exist in the registry / be installed)
META_REVIEWERS = ["meta-reviewer", "meta-reviewer-2"]

_TaskList = list[AgentTask]


def prepare_progressive(
    content: str,
    context: str | None,
    filename: str | None,
    configs: dict[str, ReviewerConfig],
    available: list[str],
    threshold: float = 0.8,
    max_tier: str = "thorough",
    scene: str | None = None,
) -> tuple[RunState, _TaskList]:
    """Zero-flow-param start: deterministic token rule + sentinel first."""
    if scene is None:
        scene = infer_scene_from_filename(filename)
    context = enrich_context(content, context, filename, scene=scene)
    token_count = count_tokens(content)
    start = start_panel_size(token_count)
    pool = filter_by_scene(
        available, {n: c.scenes for n, c in configs.items()}, scene
    )
    panel = deterministic_panel(pool, PROFILE_MAP["thorough"]["reviewers"])
    state = RunState(
        content=content,
        context=context,
        filename=filename,
        panel=panel,
        all_reviewers=list(available),
        token_count=token_count,
        content_type=scene,
        threshold=threshold,
        gated=True,
        max_tier=max_tier,
        majority_votes={n: configs[n].majority_vote for n in panel if n in configs},
        start_panel=start,
        stage=Stage.AWAITING_SENTINEL,
    )
    if start >= 3 or len(panel) < 2:
        # long content (or a single-reviewer pool): full panel, no sentinel phase
        state.stage = Stage.AWAITING_PANEL
        return state, _emit_phase1(state, configs, state.panel)
    # sentinel first: only the first panelist runs
    return state, _emit_phase1(state, configs, [state.panel[0]])


def prepare_fixed(
    content: str,
    context: str | None,
    filename: str | None,
    configs: dict[str, ReviewerConfig],
    panel: list[str],
    debate_rounds: int,
    review_depth: int,
    threshold: float = 0.8,
    scene: str | None = None,
) -> tuple[RunState, _TaskList]:
    """Explicit-params start: full panel immediately, gates disabled."""
    if scene is None:
        scene = infer_scene_from_filename(filename)
    context = enrich_context(content, context, filename, scene=scene)
    token_count = count_tokens(content)
    state = RunState(
        content=content,
        context=context,
        filename=filename,
        panel=list(panel),
        all_reviewers=list(panel),
        token_count=token_count,
        content_type=scene,
        threshold=threshold,
        gated=False,
        planned_debate_rounds=debate_rounds,
        planned_review_depth=review_depth,
        majority_votes={n: configs[n].majority_vote for n in panel if n in configs},
        start_panel=len(panel),
        stage=Stage.AWAITING_PANEL,
    )
    return state, _emit_phase1(state, configs, state.panel)


# ---------------------------------------------------------------------------
# stage machine
# ---------------------------------------------------------------------------


def advance(
    state: RunState,
    results: dict[str, str],
    configs: dict[str, ReviewerConfig],
) -> tuple[RunState, _TaskList]:
    """Pure transition: consume raw agent outputs, emit next tasks.

    Idempotent: a task counts as pending until its result FILE exists
    (an empty result file is a collected-but-failed task, degraded by
    the engine — never re-emitted, never blocking).
    """
    if state.stage == Stage.DONE:
        return state, []
    handler = {
        Stage.AWAITING_SENTINEL: _on_sentinel,
        Stage.AWAITING_PANEL: _on_panel,
        Stage.AWAITING_DEBATE: _on_debate,
        Stage.AWAITING_FINAL: _on_final,
        Stage.AWAITING_META: _on_meta,
        Stage.AWAITING_META_DEBATE: _on_meta_debate,
        Stage.AWAITING_META_FINAL: _on_meta_final,
    }[state.stage]
    return handler(state, results, configs)


# --- stage handlers --------------------------------------------------------


def _on_sentinel(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    sentinel = state.panel[0]
    ids = _p1_ids(state, sentinel)
    pending = [i for i in ids if i not in results]
    if pending:
        return state, _emit_phase1(state, configs, [sentinel])
    votes = [_verdict_from(results[i], sentinel, "independent review") for i in ids]
    v = votes[0] if len(votes) == 1 else aggregate_majority_votes(votes)
    state.individual[sentinel] = v

    stop, reason = should_early_stop([v])
    if stop:
        state.gate1_reason = reason
        state.tier = "fast"
        state.early_stopped = True
        _synthesize_final(
            state,
            configs,
            [v],
            finals=None,
            stability_degraded=True,
            reviewers=[sentinel],  # single-verdict synthesis: pair weights 1:1
        )
        _finalize(state)
        return state, []

    state.gate1_reason = reason  # kept for the audit trail
    state.stage = Stage.AWAITING_PANEL
    rest = state.panel[1:]
    if rest:
        return state, _emit_phase1(state, configs, rest)
    # single-reviewer pool: nothing to expand, panel handling proceeds
    return _on_panel(state, results, configs)


def _on_panel(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    # collect any reviewer whose vote tasks are all present
    pending_reviewers: list[str] = []
    for n in state.panel:
        if n in state.individual:
            continue
        ids = _p1_ids(state, n)
        if all(i in results for i in ids):
            votes = [_verdict_from(results[i], n, "independent review") for i in ids]
            state.individual[n] = (
                votes[0] if len(votes) == 1 else aggregate_majority_votes(votes)
            )
        else:
            pending_reviewers.append(n)
    if pending_reviewers:
        return state, _emit_phase1(state, configs, pending_reviewers)

    panel_cfgs = [configs[n] for n in state.panel]
    panel_verdicts = [state.individual[n] for n in state.panel]

    # tier decision
    if state.gated:
        tier, reason = escalation_tier(panel_verdicts, panel_cfgs)
        if TIER_RANK[tier] > TIER_RANK[state.max_tier]:
            tier = state.max_tier
        state.tier = tier
        state.gate2_reason = reason
        state.planned_debate_rounds = PROFILE_MAP[tier]["debate_rounds"]
        state.planned_review_depth = int(PROFILE_MAP[tier]["meta_review"])
    else:
        state.tier = _fixed_tier(state)

    if len(state.panel) >= 2 and state.planned_debate_rounds > 0:
        state.stage = Stage.AWAITING_DEBATE
        state.rounds_done = 0
        return state, _emit_debate_round(state, configs, round_index=1)
    if len(state.panel) >= 2:
        state.stage = Stage.AWAITING_FINAL
        return state, _emit_final(state, configs)
    # single-reviewer fast-check form: skip debate and blind final
    _synthesize_final(state, configs, panel_verdicts, finals=None, stability_degraded=True)
    if state.planned_review_depth > 0:
        state.stage = Stage.AWAITING_META
        return state, _emit_meta(state, configs, layer=1)
    _finalize(state)
    return state, []


def _on_debate(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    round_index = state.rounds_done + 1
    ids = {n: f"deb-r{round_index}-{n}" for n in state.panel}
    pending = [n for n, i in ids.items() if i not in results]
    if pending:
        return state, _emit_debate_round(state, configs, round_index)

    positions = [
        results[ids[n]] if results[ids[n]].strip() else _current_position(state, n)
        for n in state.panel
    ]
    state.debate_rounds.append(DebateRound(positions=positions))
    state.rounds_done = round_index

    if round_index < state.planned_debate_rounds:
        return state, _emit_debate_round(state, configs, round_index + 1)
    state.stage = Stage.AWAITING_FINAL
    return state, _emit_final(state, configs)


def _on_final(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    ids = {n: f"fin-{n}" for n in state.panel}
    pending = [n for n, i in ids.items() if i not in results]
    if pending:
        return state, _emit_final(state)

    finals = [_verdict_from(results[ids[n]], n, "blind final") for n in state.panel]
    for n, v in zip(state.panel, finals):
        state.final_verdicts[n] = v
    _synthesize_final(
        state,
        configs,
        [state.individual[n] for n in state.panel],
        finals=finals,
        stability_degraded=False,
    )
    if state.planned_review_depth > 0:
        state.stage = Stage.AWAITING_META
        return state, _emit_meta(state, configs, layer=1)
    _finalize(state)
    return state, []


def _on_meta(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    """Meta Phase-1: collect independent meta reviews.

    (B-2 fix) With >= 2 meta reviewers the meta layer now runs a real
    4-phase debate — Phase-1 → debate rounds → blind final → synthesis —
    mirroring the legacy ``MetaReviewer.review`` full-pipeline behaviour
    instead of the previous Phase-1-only + direct synthesis.
    """
    layer = state.meta_depth_done + 1
    meta_names = [n for n in META_REVIEWERS if n in configs]
    if len(meta_names) < 2:
        # meta agents unavailable (registry without meta templates): finalize
        _finalize(state)
        return state, []

    per_reviewer: dict[str, list[Verdict]] = {}
    pending: list[str] = []
    for n in meta_names:
        votes = max(1, state.majority_votes.get(n, 1))
        ids = [f"meta-d{layer}-{n}-v{k}" for k in range(1, votes + 1)]
        if all(i in results for i in ids):
            per_reviewer[n] = [
                _verdict_from(results[i], n, "meta review") for i in ids
            ]
        else:
            pending.append(n)
    if pending:
        return state, _emit_meta(state, configs, layer)

    aggregated = {
        n: (vs[0] if len(vs) == 1 else aggregate_majority_votes(vs))
        for n, vs in per_reviewer.items()
    }
    state.meta_individual = aggregated
    state.meta_names = meta_names
    state.meta_debate_rounds_done = 0
    state.meta_final_verdicts = {}

    meta_rounds = min(state.planned_debate_rounds, 1) if len(meta_names) >= 2 else 0
    if meta_rounds > 0:
        state.stage = Stage.AWAITING_META_DEBATE
        return state, _emit_meta_debate(state, configs, layer, round_index=1)
    # single meta reviewer path or zero rounds: straight to blind final
    state.stage = Stage.AWAITING_META_FINAL
    return state, _emit_meta_final(state, configs, layer)


def _on_meta_debate(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    """Meta debate round: each meta reviewer sees and rebuts the others."""
    layer = state.meta_depth_done + 1
    round_index = state.meta_debate_rounds_done + 1
    ids = {n: f"meta-deb-r{round_index}-{n}" for n in state.meta_names}
    pending = [n for n, i in ids.items() if i not in results]
    if pending:
        return state, _emit_meta_debate(state, configs, layer, round_index)

    positions = [
        results[ids[n]] if results[ids[n]].strip() else _meta_position(state, n)
        for n in state.meta_names
    ]
    state.meta_positions = positions
    state.meta_debate_rounds_done = round_index

    if round_index < min(state.planned_debate_rounds, 1):
        return state, _emit_meta_debate(state, configs, layer, round_index + 1)
    state.stage = Stage.AWAITING_META_FINAL
    return state, _emit_meta_final(state, configs, layer)


def _on_meta_final(
    state: RunState, results: dict[str, str], configs: dict[str, ReviewerConfig]
) -> tuple[RunState, _TaskList]:
    """Meta blind final: independent final verdicts → synthesis → calibrate."""
    layer = state.meta_depth_done + 1
    ids = {n: f"meta-fin-{layer}-{n}" for n in state.meta_names}
    pending = [n for n, i in ids.items() if i not in results]
    if pending:
        return state, _emit_meta_final(state, configs, layer)

    finals = [_verdict_from(results[ids[n]], n, "meta blind final") for n in state.meta_names]
    for n, v in zip(state.meta_names, finals):
        state.meta_final_verdicts[n] = v

    meta_cfgs = [configs[n] for n in state.meta_names]
    assert state.verdict is not None
    meta_content = serialize_verdict(state.verdict, state.content)
    meta_verdict = synthesize_verdict(finals, meta_cfgs, meta_content)
    state.meta_verdict = meta_verdict
    state.verdict.calibrated_confidence = calibrate_confidence(
        state.verdict, meta_verdict
    )
    state.meta_depth_done = layer

    if layer < state.planned_review_depth:
        state.stage = Stage.AWAITING_META
        return state, _emit_meta(state, configs, layer + 1)
    _finalize(state)
    return state, []


# --- task emitters ---------------------------------------------------------


def _full_prompt(system: str, user: str) -> str:
    """Combine system prompt (persona + judge frame) with user prompt.

    In the anonymous-agent design the reviewer persona is NOT in the agent
    definition — it is compiled into the task prompt at emit time. The
    judge-manager driver passes this combined prompt verbatim to the
    anonymous ``reviewer`` subagent.
    """
    return f"{system}\n\n---\n\n{user}"


def _emit_phase1(
    state: RunState, configs: dict[str, ReviewerConfig], names: list[str]
) -> _TaskList:
    tasks: _TaskList = []
    for n in names:
        cfg = configs[n]
        votes = max(1, state.majority_votes.get(n, 1))
        system = build_system_prompt(cfg.system_prompt)
        user = build_judge_prompt(state.content, cfg.checklist, state.context)
        prompt = _full_prompt(system, user)
        kind = (
            TaskKind.SENTINEL_REVIEW
            if state.stage == Stage.AWAITING_SENTINEL
            else TaskKind.INDEPENDENT_REVIEW
        )
        for k in range(1, votes + 1):
            tasks.append(
                AgentTask(
                    task_id=f"p1-{n}-v{k}",
                    agent=n,
                    kind=kind,
                    prompt=prompt,
                )
            )
    return tasks


def _emit_debate_round(
    state: RunState, configs: dict[str, ReviewerConfig], round_index: int
) -> _TaskList:
    tasks: _TaskList = []
    for i, n in enumerate(state.panel):
        cfg = configs[n]
        others = "\n".join(
            f"[{state.panel[j]}]: {_current_position(state, state.panel[j])}"
            for j in range(len(state.panel))
            if j != i
        )
        system = build_debate_system_prompt(cfg.system_prompt)
        user = build_debate_user_prompt(state.content, others)
        prompt = _full_prompt(system, user)
        tasks.append(
            AgentTask(
                task_id=f"deb-r{round_index}-{n}",
                agent=n,
                kind=TaskKind.DEBATE,
                prompt=prompt,
            )
        )
    return tasks


def _emit_final(
    state: RunState, configs: dict[str, ReviewerConfig]
) -> _TaskList:
    tasks: _TaskList = []
    for n in state.panel:
        cfg = configs[n]
        system = build_blind_final_system_prompt(cfg.system_prompt)
        user = build_blind_final_user_prompt(state.content, _current_position(state, n))
        prompt = _full_prompt(system, user)
        tasks.append(
            AgentTask(task_id=f"fin-{n}", agent=n, kind=TaskKind.BLIND_FINAL, prompt=prompt)
        )
    return tasks


def _emit_meta(
    state: RunState, configs: dict[str, ReviewerConfig], layer: int
) -> _TaskList:
    assert state.verdict is not None
    meta_content = serialize_verdict(state.verdict, state.content)
    tasks: _TaskList = []
    for n in META_REVIEWERS:
        if n not in configs:
            continue
        cfg = configs[n]
        votes = max(1, state.majority_votes.get(n, 1))
        system = build_system_prompt(cfg.system_prompt)
        user = build_judge_prompt(meta_content, cfg.checklist, state.context)
        prompt = _full_prompt(system, user)
        for k in range(1, votes + 1):
            tasks.append(
                AgentTask(
                    task_id=f"meta-d{layer}-{n}-v{k}",
                    agent=n,
                    kind=TaskKind.META_REVIEW,
                    prompt=prompt,
                )
            )
    return tasks


def _emit_meta_debate(
    state: RunState, configs: dict[str, ReviewerConfig], layer: int, round_index: int
) -> _TaskList:
    """Emit one meta debate round: each meta reviewer rebuts the others."""
    assert state.verdict is not None
    meta_content = serialize_verdict(state.verdict, state.content)
    tasks: _TaskList = []
    for i, n in enumerate(state.meta_names):
        cfg = configs[n]
        others = "\n".join(
            f"[{state.meta_names[j]}]: {_meta_position(state, state.meta_names[j])}"
            for j in range(len(state.meta_names))
            if j != i
        )
        system = build_debate_system_prompt(cfg.system_prompt)
        user = build_debate_user_prompt(meta_content, others)
        prompt = _full_prompt(system, user)
        tasks.append(
            AgentTask(
                task_id=f"meta-deb-r{round_index}-{n}",
                agent=n,
                kind=TaskKind.META_DEBATE,
                prompt=prompt,
            )
        )
    return tasks


def _emit_meta_final(
    state: RunState, configs: dict[str, ReviewerConfig], layer: int
) -> _TaskList:
    """Emit meta blind finals: independent final verdicts after debate."""
    assert state.verdict is not None
    meta_content = serialize_verdict(state.verdict, state.content)
    tasks: _TaskList = []
    for n in state.meta_names:
        cfg = configs[n]
        system = build_blind_final_system_prompt(cfg.system_prompt)
        user = build_blind_final_user_prompt(
            meta_content, _meta_position(state, n)
        )
        prompt = _full_prompt(system, user)
        tasks.append(
            AgentTask(
                task_id=f"meta-fin-{layer}-{n}",
                agent=n,
                kind=TaskKind.META_BLIND_FINAL,
                prompt=prompt,
            )
        )
    return tasks


def _meta_position(state: RunState, name: str) -> str:
    """Current meta reviewer position: latest debate round or Phase-1 reasoning."""
    if state.meta_positions and name in state.meta_names:
        idx = state.meta_names.index(name)
        if idx < len(state.meta_positions):
            return state.meta_positions[idx]
    v = state.meta_individual.get(name)
    return v.reasoning if v else ""


# --- helpers ---------------------------------------------------------------


def _p1_ids(state: RunState, name: str) -> list[str]:
    votes = max(1, state.majority_votes.get(name, 1))
    return [f"p1-{name}-v{k}" for k in range(1, votes + 1)]


def _current_position(state: RunState, name: str) -> str:
    if state.debate_rounds:
        idx = state.panel.index(name)
        return state.debate_rounds[-1].positions[idx]
    v = state.individual.get(name)
    return v.reasoning if v else ""


def _verdict_from(text: str, agent: str, phase: str) -> Verdict:
    if not text.strip():
        return failed_verdict(agent, phase, ValueError("empty agent output"))
    try:
        return parse_verdict(text)
    except Exception as e:  # degradation, never crash the run
        return failed_verdict(agent, phase, e)


def _fixed_tier(state: RunState) -> str:
    if state.planned_review_depth > 0 or state.planned_debate_rounds >= 2:
        return "thorough"
    if state.planned_debate_rounds >= 1 or len(state.panel) >= 2:
        return "standard"
    return "fast"


def _synthesize_final(
    state: RunState,
    configs: dict[str, ReviewerConfig],
    individual: list[Verdict],
    finals: list[Verdict] | None,
    stability_degraded: bool,
    reviewers: list[str] | None = None,
) -> None:
    """Synthesize the final verdict. ``reviewers`` names the verdict
    contributors (defaults to the full panel); weights are paired 1:1 with
    the verdict list — never divided across the whole panel."""
    names = reviewers if reviewers is not None else state.panel
    assert len(names) == len(finals if finals is not None else individual)
    panel_cfgs = [configs[n] for n in names]
    final_list = finals if finals is not None else individual
    state.verdict = synthesize_verdict(final_list, panel_cfgs, state.content)
    state.consensus_score = compute_consensus(final_list)
    if stability_degraded or finals is None:
        state.stability_score = 1.0
        state.stability_degraded = True
        state.conformity_warnings = []
    else:
        state.stability_score = compute_stability(individual, finals)
        state.stability_degraded = False
        state.conformity_warnings = detect_conformity(individual, finals)


def _finalize(state: RunState) -> None:
    assert state.verdict is not None
    state.verdict = EscalationRouter(state.threshold).annotate(state.verdict)
    state.stage = Stage.DONE
    state.route_reason = _route_reason(state)


def _route_reason(state: RunState) -> str:
    if state.gated:
        if state.early_stopped:
            return (
                f"渐进式审查: {state.token_count} tok → 哨兵单审; "
                f"早停 ({state.gate1_reason})"
            )
        head = (
            f"渐进式审查: {state.token_count} tok → 3 人面板起跑(长内容)"
            if state.start_panel >= 3
            else f"渐进式审查: {state.token_count} tok → 哨兵单审 → 面板扩张"
        )
        return f"{head}; {state.tier} 续跑 ({state.gate2_reason})"
    return (
        f"显式参数: panel={state.panel}, rounds={state.planned_debate_rounds}, "
        f"depth={state.planned_review_depth}"
    )


# --- output adapters -------------------------------------------------------


def build_result(state: RunState) -> DebateResult:
    """Adapt the terminal state into a DebateResult for the output renderers."""
    individual = [state.individual[n] for n in state.panel if n in state.individual]
    finals = (
        [state.final_verdicts[n] for n in state.panel if n in state.final_verdicts]
        or individual
    )
    assert state.verdict is not None
    return DebateResult(
        individual_verdicts=individual,
        debate_rounds=[r.positions for r in state.debate_rounds],
        final_verdicts=finals,
        final_verdict=state.verdict,
        consensus_score=state.consensus_score,
        stability_score=state.stability_score,
        stability_degraded=state.stability_degraded,
        conformity_warnings=state.conformity_warnings,
    )


def build_meta_result(state: RunState) -> DebateResult | None:
    """Mini DebateResult for the last meta layer (output parity with v1)."""
    if state.meta_verdict is None or not state.meta_individual:
        return None
    individual = list(state.meta_individual.values())
    return DebateResult(
        individual_verdicts=individual,
        debate_rounds=[],
        final_verdicts=individual,
        final_verdict=state.meta_verdict,
        consensus_score=compute_consensus(individual),
        stability_score=1.0,
        stability_degraded=True,
    )


def build_route_decision(state: RunState) -> RouteDecision:
    """Auditable route record for the verdict (progressive or fixed).

    (B-4 fix) On early stop only the sentinel actually reviewed — the audit
    trail reports exactly the reviewers with a collected verdict, never the
    full pre-planned panel.
    """
    profile = state.tier or "standard"
    participants = [n for n in state.panel if n in state.individual]
    return RouteDecision(
        content_type=state.content_type,
        complexity=(
            "low"
            if state.early_stopped
            else "high" if profile == "thorough" else "medium"
        ),
        profile=profile,
        reviewer_names=participants or list(state.panel),
        reason=state.route_reason,
        token_count=state.token_count,
        early_stopped=state.early_stopped,
        gate_reason=state.gate1_reason if state.early_stopped else state.gate2_reason,
    )
