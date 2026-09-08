"""Meta-review: reviewing the review result itself (FR-8).

(B-3) At least two meta-reviewers (different models/perspectives) run a
real debate — a single meta-reviewer debating itself has no adversarial
value.

(B-4) Calibration uses an *explicit formula*, never a blind overwrite of
the original confidence by the meta-reviewer's own confidence:

    calibrated = original_confidence × (1 - meta_penalty)

with meta_penalty from the meta-verdict's most severe severity:
critical → 0.5, major → 0.3, minor → 0.1, pass → 0.0.

If the meta-reviewer emits an explicit ``confidence_adjustment``
(-1.0 ~ +1.0), the values are blended:

    adjusted = clamp(original + adjustment, 0, 1)
    calibrated = (calibrated + adjusted) / 2
"""

import logging

from .debate import DebateOrchestrator, DebateResult
from .types import Severity, Verdict

logger = logging.getLogger(__name__)

__all__ = ["MetaReviewer"]

_SEVERITY_PENALTY: dict[Severity, float] = {
    Severity.CRITICAL: 0.5,
    Severity.MAJOR: 0.3,
    Severity.MINOR: 0.1,
    Severity.PASS: 0.0,
}


class MetaReviewer:
    """Re-reviews a first-level review verdict and calibrates its confidence.

    (B-3): uses at least 2 meta-reviewers to form a real adversarial debate.
    """

    DEFAULT_META_REVIEWERS = ["meta-reviewer", "meta-reviewer-2"]

    def __init__(
        self,
        orchestrator: DebateOrchestrator,
        meta_reviewer_names: list[str] | None = None,
    ):
        self.orchestrator = orchestrator
        self.meta_reviewer_names = (
            meta_reviewer_names or self.DEFAULT_META_REVIEWERS
        )

    def review(
        self,
        original_content: str,
        original_verdict: Verdict,
    ) -> tuple[Verdict, DebateResult]:
        """Returns (calibrated original verdict, meta-review DebateResult)."""
        verdict_text = self._serialize_verdict(original_verdict, original_content)

        # (B-3) multiple meta-reviewers debate (usually 1 round is enough)
        meta_result = self.orchestrator.run(
            content=verdict_text,
            reviewer_names=self.meta_reviewer_names,
            context=original_content,  # original content for evidence backtracking
        )

        # (B-4) explicit calibration formula
        calibrated = self._calibrate_confidence(
            original_verdict, meta_result.final_verdict
        )
        original_verdict.calibrated_confidence = calibrated
        return original_verdict, meta_result

    def _calibrate_confidence(
        self,
        original_verdict: Verdict,
        meta_verdict: Verdict,
    ) -> float:
        """(B-4) Explicit calibration formula — see module docstring."""
        original = original_verdict.confidence

        penalty = _SEVERITY_PENALTY.get(meta_verdict.severity, 0.0)
        calibrated = original * (1.0 - penalty)

        # blend in the meta-reviewer's explicit adjustment suggestion, if any
        if meta_verdict.confidence_adjustment is not None:
            adjustment = meta_verdict.confidence_adjustment
            adjusted = max(0.0, min(1.0, original + adjustment))
            calibrated = (calibrated + adjusted) / 2.0

        return round(max(0.0, min(1.0, calibrated)), 4)

    def _serialize_verdict(self, verdict: Verdict, original_content: str) -> str:
        """Serialize a Verdict to text for meta-review (serialization pattern
        borrowed from AaaJ ``memory.py:_format_judgment``)."""
        findings_text = "\n".join(
            f"  - [{f.severity.value}] {f.description} (置信度:{f.confidence})\n"
            f"    依据: {f.evidence}\n"
            f"    建议: {f.suggestion}"
            for f in verdict.findings
        )
        return (
            f"# 原始被审查内容\n{original_content}\n\n"
            f"# 审查报告(Verdict)\n"
            f"整体严重程度: {verdict.severity.value}\n"
            f"置信度: {verdict.confidence}\n"
            f"通过: {verdict.satisfied}\n"
            f"推理: {verdict.reasoning}\n\n"
            f"发现列表:\n{findings_text}\n\n"
            f"# 你的任务\n"
            f"作为元审查者,请判断上述审查报告是否可信。"
            f"输出 confidence_adjustment (-1.0 ~ +1.0) 表示对原始置信度的调整建议。"
        )
