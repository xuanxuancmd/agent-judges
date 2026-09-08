"""Verdict aggregation: synthesis, consensus and stability (M-5, NFR-5).

- ``synthesize_verdict`` — Phase 4 weighted aggregation (B-1: max severity
  via ``Severity.rank``, never string comparison; L-3: ``original_content``
  populated; B-4: meta-reviewer ``confidence_adjustment`` propagated)
- ``failed_verdict`` — degradation verdict for a failed reviewer call
- ``compute_consensus`` — reviewer agreement on the satisfied verdict,
  NOT the aggregated confidence
- ``compute_stability`` — how little reviewers flipped across the debate
"""

from .reviewer import ReviewerConfig
from .types import Severity, Verdict

__all__ = [
    "synthesize_verdict",
    "failed_verdict",
    "compute_consensus",
    "compute_stability",
]


def failed_verdict(reviewer_name: str, phase: str, error: Exception) -> Verdict:
    """Degradation verdict for a failed reviewer call (does not crash the batch)."""
    return Verdict(
        severity=Severity.MAJOR,
        confidence=0.0,
        reasoning=f"[REVIEWER FAILED ({phase}): {reviewer_name}: {error}]",
        findings=[],
        satisfied=False,
    )


def synthesize_verdict(
    verdicts: list[Verdict],
    reviewers: list[ReviewerConfig],
    content: str,
) -> Verdict:
    """Weighted aggregation of reviewer verdicts (Phase 4).

    (B-1) max severity uses ``Severity.rank``, never string comparison.
    (L-3) ``original_content`` is populated for meta-review backtracking.
    (B-4) meta-reviewer adjustment suggestions propagate as a weighted
    average so the calibration formula can use them after aggregation.
    """
    total_weight = sum(r.weight for r in reviewers)
    weighted_confidence = sum(
        v.confidence * r.weight for v, r in zip(verdicts, reviewers)
    ) / total_weight

    max_severity = max(verdicts, key=lambda v: v.severity.rank).severity

    all_findings = [f for v in verdicts for f in v.findings]

    all_satisfied = all(v.severity == Severity.PASS for v in verdicts)

    adjustments = [
        (v.confidence_adjustment, r.weight)
        for v, r in zip(verdicts, reviewers)
        if v.confidence_adjustment is not None
    ]
    if adjustments:
        adj_weight = sum(w for _, w in adjustments)
        confidence_adjustment = round(
            sum(a * w for a, w in adjustments) / adj_weight, 4
        )
    else:
        confidence_adjustment = None

    return Verdict(
        severity=max_severity,
        confidence=round(weighted_confidence, 4),
        reasoning="\n---\n".join(v.reasoning for v in verdicts),
        findings=all_findings,
        satisfied=all_satisfied,
        original_content=content,
        confidence_adjustment=confidence_adjustment,
    )


def compute_consensus(verdicts: list[Verdict]) -> float:
    """Consensus = agreement ratio on the satisfied judgement.

    Mapped to [0, 1] via ``2 × |ratio − 0.5|``:
    4/4 or 0/4 agree → 1.0; 3/4 → 0.5; 2/4 (perfect split) → 0.0.
    """
    if not verdicts:
        return 0.0
    satisfied_count = sum(1 for v in verdicts if v.satisfied)
    total = len(verdicts)
    ratio = satisfied_count / total
    return round(2 * abs(ratio - 0.5), 4)


def compute_stability(
    individual: list[Verdict], final: list[Verdict]
) -> float:
    """Stability = share of reviewers whose satisfied position did not flip
    between the independent review (Phase 1) and the blind final (Phase 3).

    1.0 = nobody flipped; 0.0 = everybody flipped.
    """
    if not individual or not final:
        return 1.0
    unchanged = sum(
        1 for i, f in zip(individual, final) if i.satisfied == f.satisfied
    )
    return round(unchanged / len(individual), 4)
