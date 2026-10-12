"""Global type definitions: Severity enum, Finding, Verdict.

(B-1) ``Severity`` is a ``StrEnum`` with an explicit ``.rank`` ordering —
``critical(3) > major(2) > minor(1) > pass(0)`` — so "most severe" aggregation
never falls back to lexicographic string comparison.
(M-6) ``Finding`` is not allowed to be ``pass``: a finding is an issue by
definition; only the overall ``Verdict`` may be ``pass``.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

__all__ = ["Severity", "Finding", "Verdict"]


class Severity(StrEnum):
    """Severity levels with explicit ordering (B-1)."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    PASS = "pass"

    @property
    def rank(self) -> int:
        """Severity ordering: critical(3) > major(2) > minor(1) > pass(0).

        Used for max-severity aggregation in ``_synthesize``.
        """
        return {self.CRITICAL: 3, self.MAJOR: 2, self.MINOR: 1, self.PASS: 0}[self]


class Finding(BaseModel):
    """A single review finding. Finding-level severity cannot be ``pass`` (M-6)."""

    description: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    suggestion: str

    @field_validator("severity")
    @classmethod
    def severity_not_pass(cls, v: Severity) -> Severity:
        if v == Severity.PASS:
            raise ValueError(
                "Finding.severity cannot be 'pass' — findings are issues by definition"
            )
        return v


class Verdict(BaseModel):
    """A review verdict. The overall Verdict *may* be ``pass``."""

    severity: Severity  # overall: critical / major / minor / pass
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    findings: list[Finding]
    satisfied: bool  # whether the review passes
    escalate_to_human: bool = False
    calibrated_confidence: float | None = None  # set by meta-review
    original_content: str | None = None  # for meta-review backtracking (L-3)
    confidence_adjustment: float | None = None  # meta-reviewer's suggested delta
    # 落地项 4: 3-tier action layer
    auto_fix_eligible: bool = False  # GREEN: AI may directly fix
    action_level: str | None = None  # "green" / "yellow" / "red"
    action_reasoning: str | None = None  # why this action level
