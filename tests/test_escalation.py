"""EscalationRouter tests (plan 8-8) + 3-tier action layer (落地项 4)."""

from __future__ import annotations

from agent_judges.escalation import EscalationRouter
from agent_judges.types import Finding, Severity

from fixtures.helpers import make_finding, make_verdict


class TestEscalation:
    def test_low_confidence_escalates(self):
        router = EscalationRouter(confidence_threshold=0.8)
        v = make_verdict(Severity.MAJOR, confidence=0.5, satisfied=False)
        assert router.should_escalate(v) is True

    def test_high_confidence_does_not_escalate(self):
        router = EscalationRouter(confidence_threshold=0.8)
        v = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        assert router.should_escalate(v) is False

    def test_boundary_not_below_threshold(self):
        router = EscalationRouter(confidence_threshold=0.8)
        v = make_verdict(Severity.PASS, confidence=0.8, satisfied=True)
        assert router.should_escalate(v) is False  # strictly below escalates

    def test_calibrated_confidence_takes_priority(self):
        router = EscalationRouter(confidence_threshold=0.8)
        v = make_verdict(Severity.PASS, confidence=0.95, satisfied=True)
        v.calibrated_confidence = 0.6  # meta-review lowered it
        assert router.should_escalate(v) is True

    def test_annotate_sets_flag(self):
        router = EscalationRouter(confidence_threshold=0.8)
        v = make_verdict(Severity.MAJOR, confidence=0.3, satisfied=False)
        assert v.escalate_to_human is False
        annotated = router.annotate(v)
        assert annotated.escalate_to_human is True
        assert annotated is v


class TestActionTier:
    """落地项 4: 3-tier action layer (green/yellow/red)."""

    def test_red_low_confidence(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MAJOR, confidence=0.5, satisfied=False)
        v.findings = [make_finding(Severity.MAJOR)]
        annotated = router.annotate(v)
        assert annotated.action_level == "red"
        assert annotated.escalate_to_human is True
        assert annotated.auto_fix_eligible is False

    def test_red_critical_severity(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.CRITICAL, confidence=0.95, satisfied=False)
        v.findings = [make_finding(Severity.CRITICAL)]
        annotated = router.annotate(v)
        assert annotated.action_level == "red"
        assert annotated.escalate_to_human is True

    def test_green_minor_high_confidence_all_suggestions(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MINOR, confidence=0.95, satisfied=False)
        v.findings = [make_finding(Severity.MINOR)]
        annotated = router.annotate(v)
        assert annotated.action_level == "green"
        assert annotated.auto_fix_eligible is True
        assert annotated.escalate_to_human is False

    def test_green_pass_no_findings(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.PASS, confidence=0.95, satisfied=True)
        annotated = router.annotate(v)
        assert annotated.action_level == "green"
        assert annotated.auto_fix_eligible is True

    def test_yellow_major_findings(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MAJOR, confidence=0.85, satisfied=False)
        v.findings = [make_finding(Severity.MAJOR)]
        annotated = router.annotate(v)
        assert annotated.action_level == "yellow"
        assert annotated.auto_fix_eligible is False
        assert annotated.escalate_to_human is False

    def test_yellow_missing_suggestions(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MINOR, confidence=0.95, satisfied=False)
        v.findings = [
            Finding(
                description="issue",
                severity=Severity.MINOR,
                confidence=0.9,
                evidence="evidence",
                suggestion="",  # empty → not green
            )
        ]
        annotated = router.annotate(v)
        assert annotated.action_level == "yellow"

    def test_yellow_confidence_between_thresholds(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MINOR, confidence=0.85, satisfied=False)
        v.findings = [make_finding(Severity.MINOR)]
        annotated = router.annotate(v)
        assert annotated.action_level == "yellow"

    def test_calibrated_confidence_used_for_action(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.PASS, confidence=0.95, satisfied=True)
        v.calibrated_confidence = 0.5  # meta-review lowered it to red
        annotated = router.annotate(v)
        assert annotated.action_level == "red"

    def test_action_reasoning_populated(self):
        router = EscalationRouter(confidence_threshold=0.8, auto_fix_confidence=0.9)
        v = make_verdict(Severity.MAJOR, confidence=0.5, satisfied=False)
        v.findings = [make_finding(Severity.MAJOR)]
        annotated = router.annotate(v)
        assert annotated.action_reasoning is not None
        assert "0.50" in annotated.action_reasoning


class TestRecommendThreshold:
    """落地项 4: threshold recommendation from calibration data."""

    def test_empty_pairs_returns_default(self):
        from agent_judges.evaluation import recommend_threshold

        assert recommend_threshold([]) == 0.8

    def test_all_correct_returns_default(self):
        from agent_judges.evaluation import recommend_threshold

        pairs = [(1, 0.9), (1, 0.8), (1, 0.7)]
        assert recommend_threshold(pairs) == 0.8

    def test_perfect_separation(self):
        from agent_judges.evaluation import recommend_threshold

        # correct verdicts have confidence 0.9-1.0, incorrect have 0.3-0.5
        pairs = [
            (1, 0.95), (1, 0.90), (1, 0.85),
            (0, 0.50), (0, 0.40), (0, 0.30),
        ]
        threshold = recommend_threshold(pairs)
        # The optimal threshold should separate correct from incorrect
        assert 0.5 <= threshold <= 0.85
