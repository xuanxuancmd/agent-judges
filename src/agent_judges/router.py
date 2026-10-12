"""Deterministic flow helpers (design.md 4.8, revised: scene-based routing).

The former L1 LLM entry router and the _CONTENT_HINTS regex table were
replaced by scene-based routing: the user (or file-extension fallback)
declares a review scene (document / code / review-report), and reviewers
are filtered by their ``scenes`` frontmatter field.

This module keeps:

- ``RouteDecision`` — the auditable route record rendered into the
  JSON/markdown ``route`` field (classic ``--profile`` routing and the
  progressive gates both produce one)
- ``PROFILE_MAP`` — profile semantics used by ``--profile`` and the gates
- ``SCENES`` — the three valid scene values
- ``filter_by_scene`` — filter available reviewers by scene tag
- ``infer_scene_from_filename`` — file-extension fallback for --scene
- ``generic_reviewer_combo`` — deterministic fallback panel
- ``deterministic_panel`` — pick ``size`` reviewers from a (pre-filtered) pool
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "RouteDecision",
    "PROFILE_MAP",
    "SCENES",
    "filter_by_scene",
    "infer_scene_from_filename",
    "generic_reviewer_combo",
    "deterministic_panel",
]


#: The three valid review scenes.
SCENES = ("document", "code", "review-report")


class RouteDecision(BaseModel):
    """Result of the flow decision (auditable).

    ``content_type`` stores the review scene (document/code/review-report).
    ``token_count`` / ``early_stopped`` / ``gate_reason`` are populated by
    the progressive gates; classic ``--profile`` routing leaves them unset.
    """

    content_type: str = "document"  # document / code / review-report
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
}


#: File extensions that indicate code files (used for --scene fallback).
_CODE_EXTENSIONS = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs",
    ".go", ".rs", ".java", ".kt", ".scala", ".clj",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".cs", ".rb", ".php", ".swift", ".dart", ".lua",
    ".zig", ".ex", ".exs", ".hs", ".jl", ".ml", ".fs",
})


def infer_scene_from_filename(filename: str | None) -> str:
    """Infer the review scene from a file extension.

    Returns "code" for code files, "document" for everything else
    (including .md, .txt, unknown extensions, or None).
    """
    if not filename:
        return "document"
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext in _CODE_EXTENSIONS:
        return "code"
    return "document"


def filter_by_scene(
    available: list[str],
    scenes_map: dict[str, list[str]],
    scene: str,
) -> list[str]:
    """Filter available reviewers to those matching the scene.

    ``scenes_map`` maps reviewer name → its ``scenes`` frontmatter list.
    Reviewers with an empty ``scenes`` list are excluded (they are
    system-internal, e.g. meta-reviewer). If no reviewer matches the
    scene, the full ``available`` list is returned as fallback.
    """
    pool = [n for n in available if scene in scenes_map.get(n, [])]
    return pool or available


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


def deterministic_panel(
    available: list[str],
    size: int,
    strategies: dict[str, str] | None = None,
) -> list[str]:
    """Select ``size`` reviewers from a (scene-pre-filtered) pool.

    ``panel[0]`` is the sentinel — the progressive flow relies on this
    for the sentinel-first run. The pool is expected to be already
    filtered by scene by the caller.

    Reasoning-strategy diversity (落地项 2): when ``strategies`` maps
    reviewer names to their ``reasoning_strategy``, the filler slots
    (panel[1:]) are greedily filled to maximize strategy diversity —
    at least 2 distinct strategies when ``size >= 2``. Unknown or
    missing strategies default to ``"checklist"``.
    """
    panel = generic_reviewer_combo(available, len(available))
    if size <= 1 or strategies is None:
        return panel[:size]

    # Greedy diversity fill: sentinel is panel[0], then prefer strategies
    # not yet represented in the panel.
    selected: list[str] = [panel[0]]
    used = {_strategy_of(panel[0], strategies)}

    # First pass: prefer reviewers whose strategy is not yet used
    for name in panel[1:]:
        if len(selected) >= size:
            break
        strat = _strategy_of(name, strategies)
        if strat not in used:
            selected.append(name)
            used.add(strat)

    # Second pass: fill remaining slots from the pool order
    for name in panel[1:]:
        if len(selected) >= size:
            break
        if name not in selected:
            selected.append(name)

    return selected[:size]


def _strategy_of(name: str, strategies: dict[str, str] | None) -> str:
    """Get the reasoning strategy for a reviewer, defaulting to checklist."""
    if strategies is None:
        return "checklist"
    return strategies.get(name, "checklist")
