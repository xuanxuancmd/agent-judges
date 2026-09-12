"""Confidence-calibration evaluation utilities.

Extracted from AaaJ's ``scripts/evaluate_confidence.py`` (highest-value
overlooked asset, plan.md 5.2) and generalized away from the DevAI
benchmark layout:

- :func:`auroc` — Mann-Whitney U rank-based AUROC, tie-aware, pure Python
  (no ML dependencies). Validates that "high-confidence judgements are
  actually more accurate".
- :func:`infer_confidence` — multi-level degradation chain for recovering
  a confidence value from a judgement record.
- :func:`build_pairs` / :func:`accuracy` / :func:`mean_confidence` —
  evaluation pipeline helpers.
- :func:`load_judgement_records` / :func:`format_evaluation_report` —
  CLI-facing entry points behind ``agent-judges evaluate``.

See ``reports/technical_guide_confidence_estimation.md`` (upstream) for the
methodology: AUROC degradation diagnosis and calibration checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

__all__ = [
    "auroc",
    "infer_confidence",
    "build_pairs",
    "accuracy",
    "mean_confidence",
    "load_judgement_records",
    "format_evaluation_report",
]

Pair = Tuple[int, float]  # (is_correct, confidence)


class JudgementFileError(ValueError):
    """A judgement file has an unsupported shape (typed boundary error)."""

    def __init__(self, path: Path, reason: str):
        super().__init__(f"unsupported judgement file {path}: {reason}")
        self.path = path
        self.reason = reason


def load_judgement_records(path: Path) -> tuple[list[dict], list[dict]]:
    """Load a predictions/labels JSON file.

    Accepted shapes:
    - JSON array of records: ``[{"satisfied": true, "confidence": 0.9}, ...]``
    - AaaJ format: ``{"requirements": [...], "judge_stats": [...]}``
      (labels may omit ``judge_stats``)

    Returns ``(records, judge_stats)``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("requirements"), list):
        return list(data["requirements"]), list(data.get("judge_stats", []))
    if isinstance(data, list):
        return data, []
    raise JudgementFileError(path, "expected a JSON array or an object with a 'requirements' list")


def format_evaluation_report(pairs: List[Pair]) -> str:
    """Render the ``agent-judges evaluate`` human-readable report."""
    return "\n".join(
        [
            "置信度校准评估",
            "=" * 40,
            f"样本数        : {len(pairs)}",
            f"Accuracy      : {accuracy(pairs):.4f}",
            f"Mean confidence: {mean_confidence(pairs):.4f}",
            f"AUROC         : {auroc(pairs):.4f}",
        ]
    )


def _average_rank(sorted_values: List[Tuple[float, int]], start: int, end: int) -> float:
    """Average (1-indexed) rank for a tie group spanning [start, end].

    Note: fixes an off-by-half bug in upstream ``evaluate_confidence.py``
    which returned ``(start + 1 + end) / 2`` — that systematically
    underestimates every group's average rank by 0.5 and skews AUROC.
    Correct: ranks span ``start+1 .. end+1``, so the average is
    ``(start + end + 2) / 2``.
    """
    return (start + end + 2) / 2.0


def auroc(pairs: List[Pair]) -> float:
    """Rank-based AUROC (Mann-Whitney U), tie-aware.

    ``pairs`` is a list of ``(is_correct, confidence)``. Returns the
    probability that a randomly chosen correct judgement has higher
    confidence than a randomly chosen incorrect one (ties count 0.5).
    Degenerate cases (all-correct / all-incorrect) return 0.5.
    """
    positives = sum(label for label, _ in pairs)
    negatives = len(pairs) - positives
    if positives == 0 or negatives == 0:
        return 0.5

    scored = [(conf, label) for label, conf in pairs]
    scored.sort(key=lambda x: x[0])

    rank_sum_pos = 0.0
    i = 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        avg_rank = _average_rank(scored, i, j)
        pos_in_group = sum(1 for k in range(i, j + 1) if scored[k][1] == 1)
        rank_sum_pos += avg_rank * pos_in_group
        i = j + 1

    return (rank_sum_pos - positives * (positives + 1) / 2.0) / (positives * negatives)


def infer_confidence(
    record: dict, judge_stats: list | None = None, index: int = 0
) -> float:
    """Recover a confidence value from a judgement record, degrading:

    1. explicit ``confidence`` field
    2. ``satisfied_ratio`` via AaaJ formula ``max(r, 1-r)``
    3. per-requirement judge stats (``llm_stats``) — confidence or
       satisfied_ratio
    4. legacy fallback when only one vote is available: 1.0
    """
    conf = record.get("confidence")
    if conf is not None:
        return float(conf)

    sat_ratio = record.get("satisfied_ratio")
    if sat_ratio is not None:
        sat_ratio = float(sat_ratio)
        return max(sat_ratio, 1.0 - sat_ratio)

    if judge_stats and index < len(judge_stats):
        stats = judge_stats[index].get("llm_stats", {})
        if "confidence" in stats:
            return float(stats["confidence"])
        if "satisfied_ratio" in stats:
            sat_ratio = float(stats["satisfied_ratio"])
            return max(sat_ratio, 1.0 - sat_ratio)

    # Legacy fallback when only one vote is available.
    return 1.0


def build_pairs(
    predictions: list[dict], human_labels: list[dict], judge_stats: list | None = None
) -> List[Pair]:
    """Zip system predictions against human labels into (is_correct, confidence) pairs.

    Each prediction may carry ``satisfied`` / ``confidence`` /
    ``satisfied_ratio``; each human label carries ``satisfied``. Records
    missing either label are skipped.
    """
    if judge_stats is None:
        judge_stats = []

    pairs: List[Pair] = []
    for i, (pred, human) in enumerate(zip(predictions, human_labels)):
        p_label = pred.get("satisfied")
        h_label = human.get("satisfied")
        if p_label is None or h_label is None:
            continue
        is_correct = 1 if bool(p_label) == bool(h_label) else 0
        confidence = infer_confidence(pred, judge_stats, i)
        pairs.append((is_correct, confidence))

    return pairs


def accuracy(pairs: List[Pair]) -> float:
    return sum(label for label, _ in pairs) / len(pairs) if pairs else 0.0


def mean_confidence(pairs: List[Pair]) -> float:
    return sum(conf for _, conf in pairs) / len(pairs) if pairs else 0.0
