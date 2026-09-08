"""EscalationRouter tests (plan 8-8)."""

from __future__ import annotations

from adversarial_judge.escalation import EscalationRouter
from adversarial_judge.types import Severity

from fixtures.helpers import make_verdict


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
