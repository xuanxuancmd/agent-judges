"""DebateOrchestrator tests: synthesis, consensus, stability, parallel
degradation, fast-check mode, budget short-circuit (plan 8-4)."""

from __future__ import annotations

import time

from adversarial_judge.consensus import (
    compute_consensus,
    compute_stability,
    synthesize_verdict,
)
from adversarial_judge.debate import DebateOrchestrator
from adversarial_judge.types import Severity

from fixtures.helpers import (
    VERDICT_JSON_SATISFIED,
    VERDICT_JSON_UNSATISFIED,
    make_config,
    make_finding,
    make_registry,
    make_verdict,
)
from fixtures.mock_llm import MockLLM, MockLLMBroker


def _orchestrator(mock_llm, *reviewers, debate_rounds=2, max_budget_usd=None):
    broker = MockLLMBroker(mock_llm, max_budget_usd=max_budget_usd)
    registry = make_registry(*reviewers)
    return DebateOrchestrator(
        registry=registry, broker=broker, debate_rounds=debate_rounds
    )


class TestSynthesize:
    def test_max_severity_uses_rank_not_lexicographic(self):
        # B-1 regression: lexicographic max("critical", "minor") == "minor"
        reviewers = [make_config("r1"), make_config("r2")]
        verdicts = [make_verdict(Severity.CRITICAL), make_verdict(Severity.MINOR)]
        result = synthesize_verdict(verdicts, reviewers, "content")
        assert result.severity == Severity.CRITICAL

    def test_weighted_confidence(self):
        reviewers = [make_config("r1", weight=1.0), make_config("r2", weight=3.0)]
        verdicts = [make_verdict(Severity.PASS, confidence=1.0),
                    make_verdict(Severity.PASS, confidence=0.5)]
        result = synthesize_verdict(verdicts, reviewers, "content")
        # (1.0*1 + 0.5*3) / 4 = 0.625
        assert result.confidence == 0.625

    def test_satisfied_requires_all_pass(self):
        reviewers = [make_config("r1")]
        verdicts = [make_verdict(Severity.PASS), make_verdict(Severity.MINOR)]
        result = synthesize_verdict(verdicts, reviewers, "content")
        assert result.satisfied is False

    def test_original_content_populated(self):
        # (L-3)
        result = synthesize_verdict([make_verdict(Severity.PASS)], [make_config("r1")], "the-content")
        assert result.original_content == "the-content"

    def test_findings_aggregated(self):
        reviewers = [make_config("r1"), make_config("r2")]
        verdicts = [
            make_verdict(Severity.MINOR, findings=[make_finding(Severity.MINOR)]),
            make_verdict(Severity.MAJOR, findings=[make_finding(Severity.MAJOR)]),
        ]
        result = synthesize_verdict(verdicts, reviewers, "c")
        assert len(result.findings) == 2

    def test_confidence_adjustment_propagated(self):
        # (B-4) meta-reviewer adjustments survive aggregation (weighted avg)
        reviewers = [make_config("r1"), make_config("r2")]
        v1 = make_verdict(Severity.PASS)
        v1.confidence_adjustment = -0.4
        v2 = make_verdict(Severity.PASS)
        v2.confidence_adjustment = -0.2
        result = synthesize_verdict([v1, v2], reviewers, "c")
        assert result.confidence_adjustment == -0.3


class TestConsensus:
    def test_unanimous(self):
        verdicts = [make_verdict(Severity.PASS, satisfied=True) for _ in range(4)]
        assert compute_consensus(verdicts) == 1.0

    def test_three_of_four(self):
        verdicts = [make_verdict(Severity.PASS, satisfied=True) for _ in range(3)]
        verdicts.append(make_verdict(Severity.MAJOR, satisfied=False))
        assert compute_consensus(verdicts) == 0.5

    def test_perfect_split(self):
        verdicts = [
            make_verdict(Severity.PASS, satisfied=True),
            make_verdict(Severity.MAJOR, satisfied=False),
        ]
        assert compute_consensus(verdicts) == 0.0

    def test_all_unsatisfied_is_consensus(self):
        verdicts = [make_verdict(Severity.MAJOR, satisfied=False) for _ in range(3)]
        assert compute_consensus(verdicts) == 1.0


class TestStability:
    def test_no_flip(self):
        individual = [make_verdict(Severity.PASS, satisfied=True),
                      make_verdict(Severity.MAJOR, satisfied=False)]
        final = [make_verdict(Severity.PASS, satisfied=True),
                 make_verdict(Severity.MAJOR, satisfied=False)]
        assert compute_stability(individual, final) == 1.0

    def test_half_flip(self):
        individual = [make_verdict(Severity.PASS, satisfied=True),
                      make_verdict(Severity.MAJOR, satisfied=False)]
        final = [make_verdict(Severity.PASS, satisfied=True),
                 make_verdict(Severity.PASS, satisfied=True)]
        assert compute_stability(individual, final) == 0.5

    def test_empty(self):
        assert compute_stability([], []) == 1.0


class TestFullDebate:
    def test_two_reviewers_two_rounds_complete_result(self):
        mock = MockLLM(
            responses={
                # phase markers (from prompts/)
                "审查框架": VERDICT_JSON_UNSATISFIED,  # Phase 1
                "辩论阶段": "我认为该需求缺少量化指标,不同意...",  # Phase 2
                "辩论已结束": VERDICT_JSON_UNSATISFIED,  # Phase 3
            }
        )
        orch = _orchestrator(
            mock,
            make_config("reviewer-a"),
            make_config("reviewer-b"),
            debate_rounds=2,
        )
        result = orch.run("some content", ["reviewer-a", "reviewer-b"])

        assert len(result.individual_verdicts) == 2
        assert len(result.debate_rounds) == 2
        assert all(len(r) == 2 for r in result.debate_rounds)
        assert len(result.final_verdicts) == 2
        assert result.final_verdict.severity == Severity.CRITICAL
        assert result.stability_degraded is False
        # call count: 2 (P1) + 2*2 (P2) + 2 (P3) = 8
        assert mock.call_count == 8

    def test_single_reviewer_fast_check_skips_phase3(self):
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论阶段": "should not be called",
                "辩论已结束": "should not be called",
            }
        )
        orch = _orchestrator(
            mock, make_config("solo"), debate_rounds=2
        )
        result = orch.run("content", ["solo"])

        assert result.debate_rounds == []  # Phase 2 skipped (B-3)
        assert result.final_verdicts == result.individual_verdicts  # Phase 3 skipped
        assert result.stability_degraded is True  # honest degradation marker
        assert mock.call_count == 1  # exactly one LLM call (Phase 1 only)

    def test_debate_rounds_zero_skips_phase2(self):
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论已结束": VERDICT_JSON_UNSATISFIED,
            }
        )
        orch = _orchestrator(
            mock, make_config("r1"), make_config("r2"), debate_rounds=0
        )
        result = orch.run("content", ["r1", "r2"])
        assert result.debate_rounds == []
        # P1 (2) + P3 (2) = 4 calls
        assert mock.call_count == 4

    def test_reviewer_failure_degrades_not_crashes(self):
        mock = MockLLM(
            responses={"审查框架": VERDICT_JSON_UNSATISFIED},
            raise_on={"reviewer-b": RuntimeError("API exploded")},
        )
        orch = _orchestrator(
            mock, make_config("reviewer-a"), make_config("reviewer-b")
        )
        result = orch.run("content", ["reviewer-a", "reviewer-b"])
        assert len(result.individual_verdicts) == 2
        degraded = result.individual_verdicts[1]
        assert degraded.confidence == 0.0
        assert degraded.severity == Severity.MAJOR
        assert "REVIEWER FAILED" in degraded.reasoning
        assert result.final_verdict is not None

    def test_phase1_parallel_timing(self):
        # N reviewers ≈ max(single latency), not sum (M-8)
        mock = MockLLM(
            responses={"审查框架": VERDICT_JSON_UNSATISFIED}, delay=0.2
        )
        orch = _orchestrator(
            mock,
            make_config("r1"),
            make_config("r2"),
            make_config("r3"),
            make_config("r4"),
            debate_rounds=0,
        )
        # replace phase 3 with a no-op by asserting on a full run's wall time:
        # P1 (parallel, ~0.2s) + P3 (parallel, ~0.2s) ≈ 0.4s; serial would be 1.6s
        start = time.monotonic()
        orch.run("content", ["r1", "r2", "r3", "r4"])
        elapsed = time.monotonic() - start
        assert elapsed < 0.75, f"parallel execution too slow: {elapsed:.2f}s"

    def test_budget_shortcircuit_after_phase1(self):
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论阶段": "nope",
                "辩论已结束": "nope",
            },
            cost_per_call=0.3,
        )
        # budget 0.5: after Phase 1 (2 calls × 0.3 = 0.6) budget is exceeded
        orch = _orchestrator(
            mock,
            make_config("r1"),
            make_config("r2"),
            debate_rounds=2,
            max_budget_usd=0.5,
        )
        result = orch.run("content", ["r1", "r2"])
        assert result.debate_rounds == []
        assert result.final_verdicts == result.individual_verdicts
        assert mock.call_count == 2  # only Phase 1 ran

    def test_budget_stops_mid_debate(self):
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,
                "辩论阶段": "argument",
                "辩论已结束": VERDICT_JSON_UNSATISFIED,
            },
            cost_per_call=0.2,
        )
        # budget 0.5: P1 (2×0.2=0.4) ok; round 1 (2×0.2 → 0.8) exceeds;
        # round 1 completes (check happens BEFORE each round), then break
        orch = _orchestrator(
            mock,
            make_config("r1"),
            make_config("r2"),
            debate_rounds=3,
            max_budget_usd=0.5,
        )
        result = orch.run("content", ["r1", "r2"])
        assert len(result.debate_rounds) == 1  # round 1 ran, rounds 2-3 stopped
        # P1 (2) + round1 (2) + P3 (2) = 6
        assert mock.call_count == 6

    def test_majority_vote_inside_independent_review(self):
        mock = MockLLM(
            responses={
                "审查框架": [
                    VERDICT_JSON_UNSATISFIED,
                    VERDICT_JSON_SATISFIED,
                    VERDICT_JSON_UNSATISFIED,
                ]
            }
        )
        orch = _orchestrator(
            mock, make_config("voter", majority_vote=3), debate_rounds=0
        )
        result = orch.run("content", ["voter"])
        v = result.final_verdict
        assert v.satisfied is False  # 2/3 unsatisfied
        assert v.confidence == round(2 / 3, 4)
        assert mock.call_count == 3
