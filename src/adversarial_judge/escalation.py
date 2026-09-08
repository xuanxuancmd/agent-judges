"""Confidence-threshold escalation routing (FR-4).

Verdicts whose effective confidence (``calibrated_confidence`` when present,
else ``confidence``) falls below the threshold are annotated with
``escalate_to_human = True``.
"""

from .types import Verdict

__all__ = ["EscalationRouter"]


class EscalationRouter:
    """Confidence threshold → human escalation routing."""

    def __init__(self, confidence_threshold: float = 0.8):
        self.threshold = confidence_threshold

    def should_escalate(self, verdict: Verdict) -> bool:
        """True when effective confidence is below the threshold.

        Uses ``calibrated_confidence`` when the verdict went through
        meta-review; otherwise the original ``confidence``.
        """
        effective = (
            verdict.calibrated_confidence
            if verdict.calibrated_confidence is not None
            else verdict.confidence
        )
        return effective < self.threshold

    def annotate(self, verdict: Verdict) -> Verdict:
        verdict.escalate_to_human = self.should_escalate(verdict)
        return verdict
