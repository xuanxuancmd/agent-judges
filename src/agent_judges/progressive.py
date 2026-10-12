"""Progressive review gates: result-driven flow control (sentinel-first).

Replaces the former LLM entry router: instead of classifying content
complexity BEFORE any review (a prediction), the pipeline runs a cheap
sentinel review first and lets deterministic gate rules read the ACTUAL
Phase-1 signals (severity / confidence / consensus) to decide whether to
stop early or continue into the full debate pipeline (a measurement).

- ``start_panel_size``  — deterministic token-count rule: long content
  starts with a full 3-reviewer panel (no sentinel single-pass)
- ``should_early_stop`` — Gate 1: clean high-confidence sentinel pass
  → the content is simple, stop before any debate
- ``escalation_tier``   — Gate 2: measured panel signals pick the
  continuation strength ("thorough" | "standard")
- ``ProgressiveDecision`` — audit record; converts to a ``RouteDecision``
  for the JSON/markdown ``route`` field

Both gates are pure functions over existing Verdict fields — zero LLM
calls, zero new output schemas for the reviewers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .consensus import synthesize_verdict
from .reviewer import ReviewerConfig
from .router import RouteDecision
from .types import Severity, Verdict

__all__ = [
    "LONG_CONTENT_TOKENS",
    "EARLY_STOP_MIN_CONFIDENCE",
    "THOROUGH_MAX_CONFIDENCE",
    "TIER_RANK",
    "ProgressiveDecision",
    "start_panel_size",
    "should_early_stop",
    "escalation_tier",
]

#: At/above this token count the content starts with a full 3-reviewer
#: panel — a single sentinel pass cannot meaningfully cover very long input
LONG_CONTENT_TOKENS = 8000

#: Gate 1: a single sentinel verdict may only stop the flow early when its
#: confidence is at least this high AND it reports nothing ≥ major
EARLY_STOP_MIN_CONFIDENCE = 0.9

#: Gate 2: a weighted confidence below this escalates to the thorough
#: continuation (2 debate rounds + blind final + meta review)
THOROUGH_MAX_CONFIDENCE = 0.8

TIER_RANK = {"fast": 0, "standard": 1, "thorough": 2}


def start_panel_size(token_count: int) -> int:
    """Deterministic start rule: long content skips the sentinel phase."""
    return 3 if token_count >= LONG_CONTENT_TOKENS else 1


def _worst_finding_severity(verdicts: list[Verdict]) -> Severity | None:
    worst: Severity | None = None
    for v in verdicts:
        for f in v.findings:
            if worst is None or f.severity.rank > worst.rank:
                worst = f.severity
    return worst


def should_early_stop(verdicts: list[Verdict]) -> tuple[bool, str]:
    """Gate 1 (pure rule): a clean, high-confidence sentinel pass means the
    content is simple — stop before any debate.

    Conservative by design: the stop-price asymmetry favours continuing
    (an unnecessary continuation costs ~10 calls; a wrong stop misses
    issues). Returns ``(stop, reason)``; the reason feeds the audit trail.
    """
    v = verdicts[0]
    if v.confidence < EARLY_STOP_MIN_CONFIDENCE:
        return False, f"哨兵置信度 {v.confidence:.2f} < {EARLY_STOP_MIN_CONFIDENCE}"
    if v.severity.rank >= Severity.MAJOR.rank:
        return False, f"哨兵判定 severity={v.severity.value}"
    worst = _worst_finding_severity(verdicts)
    if worst is not None and worst.rank >= Severity.MAJOR.rank:
        return False, f"存在 ≥major 发现 (severity={worst.value})"
    return True, (
        f"干净通过: severity={v.severity.value}, confidence={v.confidence:.2f}"
        f" ≥ {EARLY_STOP_MIN_CONFIDENCE}, 无 ≥major 发现"
    )


def escalation_tier(
    verdicts: list[Verdict], reviewers: list[ReviewerConfig]
) -> tuple[str, str]:
    """Gate 2 (pure rule): measured panel signals pick the continuation
    strength. Reuses the Phase-4 weighted synthesis — no duplicated formula.

    Returns ``("thorough" | "standard", reason)``.
    """
    synth = synthesize_verdict(verdicts, reviewers, "")
    critical = synth.severity == Severity.CRITICAL or any(
        f.severity == Severity.CRITICAL for f in synth.findings
    )
    if critical or synth.confidence < THOROUGH_MAX_CONFIDENCE:
        why = (
            "存在 critical 发现"
            if critical
            else f"加权置信度 {synth.confidence:.2f} < {THOROUGH_MAX_CONFIDENCE}"
        )
        return "thorough", (
            f"{why} (severity={synth.severity.value}, "
            f"加权置信度={synth.confidence:.2f})"
        )
    return "standard", (
        f"major 级发现或分歧 (severity={synth.severity.value}, "
        f"加权置信度={synth.confidence:.2f})"
    )


@dataclass(frozen=True)
class ProgressiveDecision:
    """Audit record of one progressive (sentinel-gated) review run."""

    token_count: int
    start_panel: int  # 1 (sentinel first) or 3 (full panel, long content)
    early_stopped: bool
    tier: str  # "fast" (early stop) | "standard" | "thorough"
    gate1_reason: str | None
    gate2_reason: str | None
    content_type: str
    reviewers: list[str]
    debate_rounds: int
    review_depth: int

    @property
    def reason(self) -> str:
        if self.early_stopped:
            return (
                f"渐进式审查: {self.token_count} tok → 哨兵单审; "
                f"早停 ({self.gate1_reason})"
            )
        if self.start_panel >= 3:
            head = f"渐进式审查: {self.token_count} tok → 3 人面板起跑(长内容)"
        else:
            head = f"渐进式审查: {self.token_count} tok → 哨兵单审 → 面板扩张"
        return f"{head}; {self.tier} 续跑 ({self.gate2_reason})"

    def to_route_decision(self) -> RouteDecision:
        """Convert to the auditable route field (output-layer contract)."""
        return RouteDecision(
            content_type=self.content_type,
            complexity=(
                "low"
                if self.early_stopped
                else "high" if self.tier == "thorough" else "medium"
            ),
            profile=self.tier,
            reviewer_names=list(self.reviewers),
            reason=self.reason,
            token_count=self.token_count,
            early_stopped=self.early_stopped,
            gate_reason=(
                self.gate1_reason if self.early_stopped else self.gate2_reason
            ),
        )
