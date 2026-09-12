"""Deterministic flow helpers (design.md 4.8, revised: progressive review).

The former L1 LLM entry router was replaced by the progressive
sentinel-gated pipeline (see ``progressive.py``): flow strength is now
decided by measured Phase-1 results, not by an a-priori classification.
This module keeps:

- ``RouteDecision`` — the auditable route record rendered into the
  JSON/markdown ``route`` field (classic ``--profile`` routing and the
  progressive gates both produce one)
- ``PROFILE_MAP`` — profile semantics used by ``--profile`` and the gates
- ``generic_reviewer_combo`` — deterministic fallback panel
- ``classify_content`` / ``deterministic_panel`` — zero-LLM reviewer
  selection: filename/content-head hints → preferred reviewers, generic
  fill to the requested size
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

__all__ = [
    "RouteDecision",
    "PROFILE_MAP",
    "generic_reviewer_combo",
    "classify_content",
    "deterministic_panel",
]


class RouteDecision(BaseModel):
    """Result of the flow decision (auditable).

    ``token_count`` / ``early_stopped`` / ``gate_reason`` are populated by
    the progressive gates; classic ``--profile`` routing leaves them unset.
    """

    content_type: str = "other"  # requirement / spec / design / code / test / agent_log / review_report / other
    complexity: str = "medium"  # low / medium / high
    profile: str = Field(pattern="^(fast|standard|thorough)$")
    reviewer_names: list[str]
    reason: str
    # progressive-mode audit fields (None for classic --profile routing)
    token_count: int | None = None
    early_stopped: bool = False
    gate_reason: str | None = None


PROFILE_MAP: dict[str, dict] = {
    "fast": {"reviewers": 1, "debate_rounds": 0, "meta_review": False},
    "standard": {"reviewers": 2, "debate_rounds": 1, "meta_review": False},
    "thorough": {"reviewers": 3, "debate_rounds": 2, "meta_review": True},
}


#: reviewers excluded from the generic fill pool. Process-level reviewers
#: (agent-log scanners) are only relevant for log content and the example
#: template is documentation, not a production reviewer.
_GENERIC_EXCLUDE = {
    "my-security-auditor",          # custom_example.md — example, not production
    "dangerous-operation-scanner",  # process-level (agent log)
    "deception-detector",           # process-level (agent log)
    "process-compliance-reviewer",  # process-level (agent log)
}


def generic_reviewer_combo(available: list[str], count: int) -> list[str]:
    """Generic deterministic reviewer combo: first ``count`` non-meta,
    non-process-level, non-example reviewers (document review pool)."""
    pool = [
        r
        for r in available
        if not r.startswith("meta-") and r not in _GENERIC_EXCLUDE
    ] or available
    if not pool:
        raise ValueError("No available reviewers to route to")
    return pool[:count]


# ---------------------------------------------------------------------------
# Zero-LLM reviewer selection: filename/content hints → preferred reviewers
# ---------------------------------------------------------------------------

#: (content_type, regex, preferred reviewers in order). Checked top to
#: bottom; first match wins. Filenames are stronger signals than content,
#: so filename hits are preferred over content hits.
_CONTENT_HINTS: list[tuple[str, re.Pattern[str], list[str]]] = [
    (
        "review_report",
        re.compile(r"code[-_ ]?review|检视报告|review[-_ ]?report", re.IGNORECASE),
        ["external-code-review-auditor"],
    ),
    (
        "agent_log",
        re.compile(r"trajectory|执行日志|agent[-_ ]?log", re.IGNORECASE),
        ["process-compliance-reviewer", "deception-detector"],
    ),
    (
        "deployment",
        re.compile(r"dockerfile|\biac\b|\bk8s\b|helm|部署", re.IGNORECASE),
        ["deployment-config-reviewer"],
    ),
    (
        "test",
        re.compile(r"test[-_ ]?plan|测试计划|测试方案", re.IGNORECASE),
        ["test-plan-reviewer"],
    ),
    (
        "test",
        re.compile(r"unit[-_ ]?test|单元测试", re.IGNORECASE),
        ["unit-test-reviewer"],
    ),
    (
        "test",
        re.compile(
            r"integration[-_ ]?test|集成测试|\.feature\b|gherkin|cucumber",
            re.IGNORECASE,
        ),
        ["integration-test-reviewer", "requirement-acceptance-reviewer"],
    ),
    (
        "spec",
        re.compile(r"\bspec\b|规格", re.IGNORECASE),
        ["spec-reviewer"],
    ),
    (
        "design",
        re.compile(r"\bdesign\b|设计|架构", re.IGNORECASE),
        ["design-reviewer"],
    ),
    (
        "requirement",
        re.compile(r"requirement|需求", re.IGNORECASE),
        ["requirement-clarification-reviewer", "requirement-acceptance-reviewer"],
    ),
    (
        "documentation",
        re.compile(r"readme|api[-_ ]?doc|文档", re.IGNORECASE),
        ["documentation-reviewer"],
    ),
]

_HINT_CONTENT_CHARS = 4000  # headings/titles live at the top of the content


def _match_hints(text: str) -> tuple[str, list[str]] | None:
    for content_type, pattern, preferred in _CONTENT_HINTS:
        if pattern.search(text):
            return content_type, list(preferred)
    return None


def classify_content(
    filename: str | None, content: str
) -> tuple[str, list[str]]:
    """Deterministic content classification (zero LLM calls).

    Matches the filename first (strongest signal — ``spec.md`` → spec),
    then the head of the content. Returns ``(content_type,
    preferred_reviewers)``; unmatched content returns ``("other", [])``
    and the caller falls back to the generic combo.
    """
    if filename:
        hit = _match_hints(filename)
        if hit is not None:
            return hit
    if content:
        hit = _match_hints(content[:_HINT_CONTENT_CHARS])
        if hit is not None:
            return hit
    return "other", []


def deterministic_panel(
    available: list[str],
    size: int,
    filename: str | None = None,
    content: str = "",
) -> tuple[str, list[str]]:
    """Deterministic panel selection: classified preferences first, generic
    fill to ``size``. Returns ``(content_type, panel)``.

    ``panel[0]`` is the sentinel (preferred reviewer first, then registry
    order) — the progressive flow relies on this for the sentinel-first run.
    """
    content_type, preferred = classify_content(filename, content)
    panel: list[str] = [n for n in preferred if n in available]
    for n in generic_reviewer_combo(available, len(available)):
        if len(panel) >= size:
            break
        if n not in panel:
            panel.append(n)
    return content_type, panel[:size]
