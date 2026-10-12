"""Confidence-threshold escalation routing (FR-4) + 3-tier action layer (落地项 4).

The action tier is determined from the *effective* confidence
(``calibrated_confidence`` when present, else ``confidence``) and the
max finding severity:

- **GREEN** (``auto_fix_eligible=True``): effective confidence is high
  enough AND all findings are ``minor`` or below AND every finding has a
  non-empty suggestion → the AI that produced the artifact may directly
  fix it (the fix is mechanical and well-specified).
- **YELLOW**: confidence is above the escalation threshold but major
  findings exist, or some findings lack suggestions → a human should
  confirm the repair plan before the AI executes it.
- **RED** (``escalate_to_human=True``): effective confidence is below
  the threshold, or the overall severity is ``critical`` → the review
  itself is unreliable or the problem is severe enough that human
  judgment is required.
"""

from .types import Severity, Verdict

__all__ = ["EscalationRouter"]


class EscalationRouter:
    """Confidence threshold → 3-tier human-escalation routing.

    Parameters
    ----------
    confidence_threshold:
        Below this confidence the verdict is RED (escalate to human).
        Default ``0.8``.
    auto_fix_confidence:
        The minimum confidence for GREEN (auto-fix eligible). Must be
        ≥ ``confidence_threshold``. Default ``0.9`` — the AI may only
        directly fix when it is *very* confident.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.8,
        auto_fix_confidence: float = 0.9,
    ):
        self.threshold = confidence_threshold
        self.auto_fix_confidence = auto_fix_confidence

    def _effective_confidence(self, verdict: Verdict) -> float:
        """Use calibrated confidence when available, else the original."""
        if verdict.calibrated_confidence is not None:
            return verdict.calibrated_confidence
        return verdict.confidence

    def _max_finding_severity(self, verdict: Verdict) -> Severity:
        """The severity of the most severe finding (PASS if no findings)."""
        if not verdict.findings:
            return Severity.PASS
        return max(verdict.findings, key=lambda f: f.severity.rank).severity

    def _all_have_suggestions(self, verdict: Verdict) -> bool:
        """True when every finding carries a non-empty repair suggestion."""
        if not verdict.findings:
            return True
        return all(f.suggestion.strip() for f in verdict.findings)

    def should_escalate(self, verdict: Verdict) -> bool:
        """True when the verdict is RED (effective confidence < threshold
        or overall severity is critical)."""
        effective = self._effective_confidence(verdict)
        if effective < self.threshold:
            return True
        return verdict.severity == Severity.CRITICAL

    def annotate(self, verdict: Verdict) -> Verdict:
        """Annotate the verdict with the 3-tier action decision.

        Sets ``escalate_to_human``, ``auto_fix_eligible``,
        ``action_level`` and ``action_reasoning`` on the verdict.
        """
        effective = self._effective_confidence(verdict)
        max_finding_sev = self._max_finding_severity(verdict)
        all_sug = self._all_have_suggestions(verdict)

        if effective < self.threshold or verdict.severity == Severity.CRITICAL:
            # RED — must escalate to human
            verdict.escalate_to_human = True
            verdict.auto_fix_eligible = False
            verdict.action_level = "red"
            if effective < self.threshold:
                verdict.action_reasoning = (
                    f"置信度 {effective:.2f} < 阈值 {self.threshold},需人工介入"
                )
            else:
                verdict.action_reasoning = "存在 critical 问题,需人工介入"
        elif (
            max_finding_sev.rank <= Severity.MINOR.rank
            and effective >= self.auto_fix_confidence
            and all_sug
        ):
            # GREEN — AI may directly fix
            verdict.escalate_to_human = False
            verdict.auto_fix_eligible = True
            verdict.action_level = "green"
            verdict.action_reasoning = (
                f"置信度 {effective:.2f} ≥ {self.auto_fix_confidence},"
                f"severity ≤ minor,全部 finding 有修复建议"
            )
        else:
            # YELLOW — human should confirm repair plan
            verdict.escalate_to_human = False
            verdict.auto_fix_eligible = False
            verdict.action_level = "yellow"
            verdict.action_reasoning = (
                f"置信度 {effective:.2f} 足够但存在 "
                f"{max_finding_sev.value} 级问题,需人工确认修复方案"
            )
        return verdict
