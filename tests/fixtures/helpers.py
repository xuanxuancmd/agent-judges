"""Test helpers: in-memory registry/config/verdict builders + canned responses."""

from __future__ import annotations

from adversarial_judge.reviewer import ChecklistItem, ReviewerConfig, ReviewerRegistry
from adversarial_judge.types import Finding, Severity, Verdict

__all__ = [
    "make_registry",
    "make_config",
    "make_verdict",
    "make_finding",
    "VERDICT_JSON_SATISFIED",
    "VERDICT_JSON_UNSATISFIED",
]


def make_registry(*configs: ReviewerConfig) -> ReviewerRegistry:
    """Build an in-memory registry containing only the given configs."""
    return ReviewerRegistry.__new__(ReviewerRegistry) if not configs else _build(configs)


def _build(configs) -> ReviewerRegistry:
    registry = object.__new__(ReviewerRegistry)
    registry.reviewers = {c.name: c for c in configs}
    return registry


def make_config(
    name: str = "test-reviewer",
    model: str | None = None,
    weight: float = 1.0,
    majority_vote: int = 1,
    system_prompt: str | None = None,
) -> ReviewerConfig:
    return ReviewerConfig(
        name=name,
        description=f"test config for {name}",
        model=model,
        system_prompt=system_prompt or f"你是 {name} 审查者。",
        checklist=[ChecklistItem(criteria="内容完整")],
        weight=weight,
        majority_vote=majority_vote,
    )


def make_finding(
    severity: Severity = Severity.MAJOR, confidence: float = 0.7
) -> Finding:
    return Finding(
        description="a finding",
        severity=severity,
        confidence=confidence,
        evidence="some evidence",
        suggestion="some suggestion",
    )


def make_verdict(
    severity: Severity = Severity.MAJOR,
    confidence: float = 0.8,
    satisfied: bool | None = None,
    findings: list[Finding] | None = None,
    reasoning: str = "reasoning",
) -> Verdict:
    return Verdict(
        severity=severity,
        confidence=confidence,
        reasoning=reasoning,
        findings=findings or [],
        satisfied=satisfied if satisfied is not None else severity == Severity.PASS,
    )


VERDICT_JSON_SATISFIED = """```json
{"severity": "pass", "confidence": 0.92, "reasoning": "all good",
 "findings": [], "satisfied": true}
```"""

VERDICT_JSON_UNSATISFIED = """```json
{"severity": "critical", "confidence": 0.85, "reasoning": "bad",
 "findings": [{"description": "missing metric", "severity": "major",
   "confidence": 0.7, "evidence": "no QPS", "suggestion": "add QPS"}],
 "satisfied": false}
```"""
