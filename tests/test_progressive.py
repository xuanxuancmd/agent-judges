"""Progressive review tests: gates, decisions, resolve_flow, orchestration
(zero real LLM calls — MockLLM only)."""

from __future__ import annotations

import pytest

from agent_judges.cli.review_flow import FlowError, FlowRequest, resolve_flow
from agent_judges.consensus import failed_verdict
from agent_judges.debate import DebateOrchestrator
from agent_judges.progressive import (
    LONG_CONTENT_TOKENS,
    ProgressiveDecision,
    escalation_tier,
    should_early_stop,
    start_panel_size,
)
from agent_judges.types import Severity
from agent_judges.utils.truncate import count_tokens

from fixtures.helpers import (
    VERDICT_JSON_SATISFIED,
    VERDICT_JSON_UNSATISFIED,
    make_config,
    make_finding,
    make_registry,
    make_verdict,
)
from fixtures.mock_llm import MockLLM, MockLLMBroker

MAJOR_VERDICT_JSON = """```json
{"severity": "major", "confidence": 0.85, "reasoning": "r",
 "findings": [{"description": "d", "severity": "major", "confidence": 0.7,
   "evidence": "e", "suggestion": "s"}],
 "satisfied": false}
```"""


# ---------------------------------------------------------------------------
# Gate rules (pure functions)
# ---------------------------------------------------------------------------


class TestStartPanelSize:
    def test_short_content_sentinel(self):
        assert start_panel_size(100) == 1

    def test_boundary(self):
        assert start_panel_size(LONG_CONTENT_TOKENS - 1) == 1
        assert start_panel_size(LONG_CONTENT_TOKENS) == 3


class TestGate1EarlyStop:
    def test_clean_high_confidence_pass_stops(self):
        v = make_verdict(Severity.PASS, confidence=0.92, satisfied=True)
        stop, reason = should_early_stop([v])
        assert stop is True
        assert "干净通过" in reason

    def test_low_confidence_continues(self):
        v = make_verdict(Severity.PASS, confidence=0.85, satisfied=True)
        stop, reason = should_early_stop([v])
        assert stop is False
        assert "置信度" in reason

    def test_major_severity_continues(self):
        v = make_verdict(Severity.MAJOR, confidence=0.95, satisfied=False)
        assert should_early_stop([v])[0] is False

    def test_major_finding_continues(self):
        # defensive: verdict severity minor but a finding is major (LLM
        # inconsistency) — the stricter signal must win
        v = make_verdict(
            Severity.MINOR, confidence=0.95, findings=[make_finding(Severity.MAJOR)]
        )
        stop, reason = should_early_stop([v])
        assert stop is False
        assert "≥major" in reason

    def test_minor_finding_with_high_confidence_stops(self):
        v = make_verdict(
            Severity.MINOR,
            confidence=0.95,
            findings=[make_finding(Severity.MINOR)],
        )
        assert should_early_stop([v])[0] is True

    def test_failed_verdict_continues(self):
        # degraded reviewer call (confidence 0.0) must never trigger a stop
        v = failed_verdict("r", "independent review", RuntimeError("boom"))
        assert should_early_stop([v])[0] is False


class TestGate2EscalationTier:
    def test_critical_escalates_thorough(self):
        reviewers = [make_config("r1"), make_config("r2"), make_config("r3")]
        verdicts = [
            make_verdict(Severity.CRITICAL, confidence=0.9, satisfied=False)
            for _ in range(3)
        ]
        tier, reason = escalation_tier(verdicts, reviewers)
        assert tier == "thorough"
        assert "critical" in reason

    def test_critical_finding_escalates(self):
        reviewers = [make_config("r1")]
        v = make_verdict(
            Severity.MAJOR, confidence=0.9, findings=[make_finding(Severity.CRITICAL)]
        )
        assert escalation_tier([v], reviewers)[0] == "thorough"

    def test_low_weighted_confidence_escalates(self):
        reviewers = [make_config("r1"), make_config("r2")]
        verdicts = [
            make_verdict(Severity.MAJOR, confidence=0.6, satisfied=False),
            make_verdict(Severity.MAJOR, confidence=0.7, satisfied=False),
        ]
        tier, reason = escalation_tier(verdicts, reviewers)
        assert tier == "thorough"
        assert "加权置信度" in reason

    def test_major_only_continues_standard(self):
        reviewers = [make_config("r1"), make_config("r2"), make_config("r3")]
        verdicts = [
            make_verdict(Severity.MAJOR, confidence=0.85, satisfied=False)
            for _ in range(3)
        ]
        assert escalation_tier(verdicts, reviewers)[0] == "standard"


class TestProgressiveDecisionRoute:
    def test_early_stop_maps_to_fast(self):
        d = ProgressiveDecision(
            token_count=100,
            start_panel=1,
            early_stopped=True,
            tier="fast",
            gate1_reason="干净通过",
            gate2_reason=None,
            content_type="document",
            reviewers=["spec-reviewer"],
            debate_rounds=0,
            review_depth=0,
        )
        rd = d.to_route_decision()
        assert rd.profile == "fast"
        assert rd.early_stopped is True
        assert rd.complexity == "low"
        assert rd.token_count == 100
        assert rd.gate_reason == "干净通过"
        assert "早停" in rd.reason

    def test_thorough_continuation_maps(self):
        d = ProgressiveDecision(
            token_count=100,
            start_panel=1,
            early_stopped=False,
            tier="thorough",
            gate1_reason=None,
            gate2_reason="存在 critical 发现",
            content_type="document",
            reviewers=["a", "b", "c"],
            debate_rounds=2,
            review_depth=1,
        )
        rd = d.to_route_decision()
        assert rd.profile == "thorough"
        assert rd.complexity == "high"
        assert rd.early_stopped is False
        assert "thorough 续跑" in rd.reason


# ---------------------------------------------------------------------------
# resolve_flow: progressive / profile / partial-params decisions
# ---------------------------------------------------------------------------


class TestResolveFlow:
    def test_zero_params_progressive(self):
        flow = resolve_flow(FlowRequest(available=["a"]))
        assert flow.progressive is True
        assert flow.reviewers == []
        assert flow.route_decision is None

    def test_fully_manual_not_progressive(self):
        flow = resolve_flow(
            FlowRequest(
                debate_rounds=0, review_depth=0, available=["a"]
            )
        )
        assert flow.progressive is False

    def test_profile_not_progressive(self):
        flow = resolve_flow(FlowRequest(profile="fast", available=["a"]))
        assert flow.progressive is False
        assert flow.route_decision is not None
        assert flow.route_decision.profile == "fast"

    def test_partial_params_filled_with_standard_defaults(self):
        flow = resolve_flow(FlowRequest(review_depth=0, available=["a"]))
        assert flow.progressive is False
        assert flow.debate_rounds == 1  # standard default, no LLM routing
        assert flow.review_depth == 0

    def test_no_available_errors(self):
        with pytest.raises(FlowError):
            resolve_flow(FlowRequest(available=[]))


# ---------------------------------------------------------------------------
# run_progressive orchestration (MockLLM)
# ---------------------------------------------------------------------------


def _orchestrator(mock_llm: MockLLM, names: tuple[str, ...]) -> DebateOrchestrator:
    broker = MockLLMBroker(mock_llm)
    registry = make_registry(*[make_config(n) for n in names])
    return DebateOrchestrator(registry=registry, broker=broker, debate_rounds=2)


_THREE = ("sentinel-reviewer", "second-reviewer", "third-reviewer")


class TestRunProgressive:
    def test_early_stop_costs_one_call(self):
        mock = MockLLM(responses={"审查框架": VERDICT_JSON_SATISFIED})
        orch = _orchestrator(mock, _THREE)
        result, decision = orch.run_progressive("短内容", candidates=list(_THREE))
        assert mock.call_count == 1
        assert decision.early_stopped is True
        assert decision.tier == "fast"
        assert decision.reviewers == ["sentinel-reviewer"]
        assert decision.review_depth == 0
        assert result.stability_degraded is True
        assert result.debate_rounds == []
        assert len(result.individual_verdicts) == 1
        assert result.final_verdict.severity == Severity.PASS

    def test_sentinel_failure_escalates_thorough(self):
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论阶段": "我坚持存在量化指标缺失问题",
                "辩论已结束": VERDICT_JSON_UNSATISFIED,
            }
        )
        orch = _orchestrator(mock, _THREE)
        result, decision = orch.run_progressive("短内容", candidates=list(_THREE))
        assert decision.early_stopped is False
        assert decision.tier == "thorough"
        assert decision.debate_rounds == 2
        assert decision.review_depth == 1
        # sentinel verdict kept + 2 expansion reviewers, no re-computation
        assert len(result.individual_verdicts) == 3
        assert len(result.debate_rounds) == 2
        # 1 sentinel + 2 expansion + 3×2 debate + 3 blind final = 12
        assert mock.call_count == 12

    def test_major_only_continues_standard(self):
        mock = MockLLM(
            responses={
                "审查框架": MAJOR_VERDICT_JSON,
                "辩论阶段": "argue",
                "辩论已结束": MAJOR_VERDICT_JSON,
            }
        )
        orch = _orchestrator(mock, _THREE)
        result, decision = orch.run_progressive("短内容", candidates=list(_THREE))
        assert decision.tier == "standard"
        assert decision.debate_rounds == 1
        assert decision.review_depth == 0
        # 3 phase-1 + 3 debate (1 round) + 3 blind final = 9
        assert mock.call_count == 9
        assert result.final_verdict.severity == Severity.MAJOR

    def test_max_tier_caps_escalation(self):
        # e.g. meta-reviewer templates unavailable → thorough capped at standard
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论阶段": "argue",
                "辩论已结束": VERDICT_JSON_UNSATISFIED,
            }
        )
        orch = _orchestrator(mock, _THREE)
        result, decision = orch.run_progressive(
            "短内容", candidates=list(_THREE), max_tier="standard"
        )
        assert decision.tier == "standard"
        assert decision.review_depth == 0
        assert len(result.debate_rounds) == 1

    def test_long_content_starts_full_panel(self):
        content = "详细规格内容。"
        while count_tokens(content) < LONG_CONTENT_TOKENS + 100:
            content *= 2
        assert count_tokens(content) >= LONG_CONTENT_TOKENS
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_SATISFIED,
                "辩论阶段": "agree",
                "辩论已结束": VERDICT_JSON_SATISFIED,
            }
        )
        orch = _orchestrator(mock, _THREE)
        result, decision = orch.run_progressive(content, candidates=list(_THREE))
        assert decision.start_panel == 3
        assert decision.early_stopped is False  # gate 1 skipped entirely
        assert decision.gate1_reason is None
        assert len(result.individual_verdicts) == 3
        # all-pass conf 0.92 → gate 2 standard (weighted conf ≥ 0.8)
        assert decision.tier == "standard"
        assert result.final_verdict.severity == Severity.PASS

    def test_single_reviewer_pool_degrades_gracefully(self):
        # pool of one: sentinel is the whole panel; a non-clean verdict
        # continues through the single-reviewer fast-check form
        mock = MockLLM(responses={"审查框架": MAJOR_VERDICT_JSON})
        orch = _orchestrator(mock, ("only-reviewer",))
        result, decision = orch.run_progressive(
            "短内容", candidates=["only-reviewer"]
        )
        assert decision.early_stopped is False
        assert decision.reviewers == ["only-reviewer"]
        assert result.stability_degraded is True
        assert result.final_verdict.severity == Severity.MAJOR
