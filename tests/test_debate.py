"""Pure-function tests: synthesis, consensus, stability, conformity,
prompt builders, provenance tagging, agreement intensity, reasoning strategy.

The DebateOrchestrator (in-process litellm direct mode) has been removed;
these tests cover the pure functions from consensus.py, prompts/, and
router.py that the agent-driven engine.py path also depends on.
"""

from __future__ import annotations

from agent_judges.consensus import (
    compute_consensus,
    compute_stability,
    detect_conformity,
    synthesize_verdict,
)
from agent_judges.types import Finding, Severity

from fixtures.helpers import (
    make_config,
    make_finding,
    make_verdict,
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


class TestConformity:
    """detect_conformity: flag reviewers who flip satisfied without new findings."""

    def _finding(self, desc: str = "a finding") -> Finding:
        return Finding(
            description=desc,
            severity=Severity.MAJOR,
            confidence=0.7,
            evidence="evidence",
            suggestion="suggestion",
        )

    def test_no_flip_no_warning(self):
        """Reviewers who don't change their satisfied position -> no warning."""
        individual = [make_verdict(Severity.PASS, satisfied=True),
                      make_verdict(Severity.MAJOR, satisfied=False)]
        final = [make_verdict(Severity.PASS, satisfied=True),
                 make_verdict(Severity.MAJOR, satisfied=False)]
        assert detect_conformity(individual, final) == []

    def test_flip_with_new_finding_no_warning(self):
        """Reviewer flips but adds a new finding -> not conformity."""
        ind = make_verdict(Severity.MAJOR, satisfied=False)
        fin = make_verdict(Severity.PASS, satisfied=True)
        fin.findings = [self._finding("new-issue")]
        assert detect_conformity([ind], [fin]) == []

    def test_flip_without_new_finding_warns(self):
        """Reviewer flips satisfied but adds no new finding -> warning."""
        ind = make_verdict(Severity.MAJOR, satisfied=False)
        fin = make_verdict(Severity.PASS, satisfied=True)
        warnings = detect_conformity([ind], [fin])
        assert len(warnings) == 1
        assert "False->True" in warnings[0]

    def test_flip_with_retracted_finding_only_still_warns(self):
        """Reviewer flips, removes a finding but adds none -> still warns
        (acknowledged false positive in docstring)."""
        ind = make_verdict(Severity.MAJOR, satisfied=False)
        ind.findings = [self._finding("a"), self._finding("b")]
        fin = make_verdict(Severity.PASS, satisfied=True)
        fin.findings = [self._finding("a")]  # only removed, no new
        warnings = detect_conformity([ind], [fin])
        assert len(warnings) == 1

    def test_empty_lists(self):
        assert detect_conformity([], []) == []

    def test_mixed_panel(self):
        """2 reviewers: one flips with new finding, one flips without."""
        ind1 = make_verdict(Severity.MAJOR, satisfied=False)
        ind2 = make_verdict(Severity.MAJOR, satisfied=False)
        fin1 = make_verdict(Severity.PASS, satisfied=True)
        fin1.findings = [self._finding("new")]  # justified flip
        fin2 = make_verdict(Severity.PASS, satisfied=True)  # no new finding
        warnings = detect_conformity([ind1, ind2], [fin1, fin2])
        assert len(warnings) == 1
        assert "#1" in warnings[0]


class TestPromptBuilders:
    """Blind-final prompts must carry the JSON output protocol.

    Regression (found by the agent-mode e2e on real host reviewers): in
    agent mode the reviewer Agent sees ONLY the task prompt — without the
    protocol it answers in prose and the verdict parse chain degrades to a
    failed verdict (confidence 0.0).
    """

    def test_blind_final_user_prompt_carries_json_protocol(self):
        from agent_judges.prompts.debate import build_blind_final_user_prompt

        prompt = build_blind_final_user_prompt("内容 X", "立场 Y")
        assert "```json" in prompt
        assert "severity: critical / major / minor / pass" in prompt
        assert "satisfied: bool" in prompt
        # original instruction preserved (substring stability)
        assert "请给出最终裁决" in prompt
        assert "立场 Y" in prompt

    def test_finding_severity_enum_is_enumerated_in_prompts(self):
        """Real-reviewer regression (agent-mode e2e): without the enum,
        reviewers answer findings severity with high/medium/low, which the
        lenient parser silently downgrades to minor — understating results.
        """
        from agent_judges.prompts.debate import build_blind_final_user_prompt
        from agent_judges.prompts.judge_user import build_judge_prompt

        checklist = [type("C", (), {"criteria": "c1"})()]
        phase1 = build_judge_prompt("内容", checklist)
        blind = build_blind_final_user_prompt("内容", "立场")
        for prompt in (phase1, blind):
            assert (
                "findings: [{description, severity: critical/major/minor, "
                "confidence, evidence, suggestion}]" in prompt
            )


class TestProvenanceTagging:
    """落地项 1: Phase 2 debate prompts carry tri-state provenance tags."""

    def test_debate_system_prompt_contains_provenance_instructions(self):
        from agent_judges.prompts.debate import build_debate_system_prompt

        prompt = build_debate_system_prompt("你是测试审查者。")
        assert "[✓已确认]" in prompt
        assert "[✗已反驳]" in prompt
        assert "[?未验证]" in prompt
        assert "不带认知状态标记的引用对方观点,视为无效反驳" in prompt
        assert "[?未验证]的主张不得作为你调整自己severity或confidence的依据" in prompt

    def test_debate_user_prompt_labels_content_as_verification_source(self):
        from agent_judges.prompts.debate import build_debate_user_prompt

        prompt = build_debate_user_prompt("被审查内容", "他人观点")
        assert "被审查内容(请据此验证他人主张)" in prompt

    def test_conformity_detects_unverified_provenance(self):
        """A reviewer whose final reasoning contains [?未验证] is flagged."""
        ind = make_verdict(Severity.MAJOR, satisfied=False)
        fin = make_verdict(Severity.PASS, satisfied=True)
        fin.reasoning = "基于[?未验证]的主张调整了判断"
        warnings = detect_conformity([ind], [fin])
        assert any("[?未验证]" in w for w in warnings)

    def test_conformity_no_unverified_no_provenance_warning(self):
        """A reviewer whose reasoning has no [?未验证] -> no provenance warning."""
        ind = make_verdict(Severity.MAJOR, satisfied=False)
        fin = make_verdict(Severity.PASS, satisfied=True)
        fin.reasoning = "基于确凿证据调整了判断"
        warnings = detect_conformity([ind], [fin])
        assert all("[?未验证]" not in w for w in warnings)


class TestAgreementIntensity:
    """落地项 3: auto-inferred skepticism from Phase-1 signals."""

    def test_infer_skepticism_critical_severity(self):
        from agent_judges.consensus import infer_skepticism

        verdicts = [make_verdict(Severity.CRITICAL, confidence=0.9, satisfied=False)]
        assert infer_skepticism(verdicts) == 0.9

    def test_infer_skepticism_low_consensus(self):
        from agent_judges.consensus import infer_skepticism

        verdicts = [
            make_verdict(Severity.PASS, confidence=0.9, satisfied=True),
            make_verdict(Severity.MAJOR, confidence=0.7, satisfied=False),
        ]
        assert infer_skepticism(verdicts) == 0.85

    def test_infer_skepticism_full_consensus_minor(self):
        from agent_judges.consensus import infer_skepticism

        verdicts = [
            make_verdict(Severity.MINOR, confidence=0.9, satisfied=True),
            make_verdict(Severity.MINOR, confidence=0.9, satisfied=True),
        ]
        assert infer_skepticism(verdicts) == 0.4

    def test_infer_skepticism_default_moderate(self):
        from agent_judges.consensus import infer_skepticism

        verdicts = [
            make_verdict(Severity.MAJOR, confidence=0.8, satisfied=False),
            make_verdict(Severity.MAJOR, confidence=0.7, satisfied=False),
        ]
        assert infer_skepticism(verdicts) == 0.7

    def test_infer_skepticism_empty_returns_default(self):
        from agent_judges.consensus import infer_skepticism

        assert infer_skepticism([]) == 0.7

    def test_debate_prompt_high_skepticism(self):
        from agent_judges.prompts.debate import build_debate_system_prompt

        prompt = build_debate_system_prompt("你是审查者。", skepticism=0.9)
        assert "保持高度怀疑" in prompt

    def test_debate_prompt_low_skepticism(self):
        from agent_judges.prompts.debate import build_debate_system_prompt

        prompt = build_debate_system_prompt("你是审查者。", skepticism=0.3)
        assert "优先寻找与其他审查者的共识点" in prompt

    def test_debate_prompt_default_moderate(self):
        from agent_judges.prompts.debate import build_debate_system_prompt

        prompt = build_debate_system_prompt("你是审查者。")
        assert "对其他审查者不同意的发现进行反驳" in prompt


class TestReasoningStrategy:
    """落地项 2: reasoning strategy injection + diversity-aware panel."""

    def test_system_prompt_injects_strategy(self):
        from agent_judges.prompts.judge_system import build_system_prompt

        prompt = build_system_prompt("你是审查者。", reasoning_strategy="inverse")
        assert "[推理策略 — inverse]" in prompt
        assert "假设它是必要的" in prompt

    def test_system_prompt_injects_transform_strategy(self):
        from agent_judges.prompts.judge_system import build_system_prompt

        prompt = build_system_prompt("你是审查者。", reasoning_strategy="transform")
        assert "[推理策略 — transform]" in prompt

    def test_system_prompt_no_strategy_no_injection(self):
        from agent_judges.prompts.judge_system import build_system_prompt

        prompt = build_system_prompt("你是审查者。")
        assert "[推理策略" not in prompt

    def test_system_prompt_unknown_strategy_no_injection(self):
        from agent_judges.prompts.judge_system import build_system_prompt

        prompt = build_system_prompt("你是审查者。", reasoning_strategy="unknown")
        assert "[推理策略" not in prompt

    def test_deterministic_panel_prefers_diverse_strategies(self):
        from agent_judges.router import deterministic_panel

        available = ["a", "b", "c", "d"]
        strategies = {
            "a": "checklist",
            "b": "checklist",
            "c": "transform",
            "d": "falsification",
        }
        panel = deterministic_panel(available, 3, strategies)
        assert panel[0] == "a"  # sentinel is always first
        # The second pick should prefer a different strategy
        panel_strategies = {strategies.get(n, "checklist") for n in panel}
        assert len(panel_strategies) >= 2

    def test_deterministic_panel_no_strategies_fallback(self):
        from agent_judges.router import deterministic_panel

        panel = deterministic_panel(["a", "b", "c"], 2)
        assert len(panel) == 2
