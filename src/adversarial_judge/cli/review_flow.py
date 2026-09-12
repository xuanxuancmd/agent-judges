"""Pure helpers for the review command: input loading and the three-tier
flow decision — kept free of typer so they stay unit-testable.

Three-tier decision (revised): explicit fine-grained params > ``--profile``
> progressive review (sentinel-gated; see ``progressive.py``).
Zero-parameter calls no longer pre-classify content with an LLM — the
sentinel review and deterministic gates decide the flow strength from
measured Phase-1 results. Partial manual params (e.g. only ``-r``) are
filled deterministically with standard defaults.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..router import (
    PROFILE_MAP,
    RouteDecision,
    deterministic_panel,
    generic_reviewer_combo,
)

__all__ = [
    "FlowRequest",
    "ResolvedFlow",
    "FlowError",
    "load_review_content",
    "resolve_flow",
]


class FlowError(ValueError):
    """Flow resolution failed with a user-facing message (typed boundary error)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class FlowRequest:
    """Inputs to the three-tier flow decision."""

    reviewers: list[str] | None = None
    debate_rounds: int | None = None
    review_depth: int | None = None
    profile: str | None = None
    review_content: str = ""
    available: list[str] = field(default_factory=list)
    filename: str | None = None  # --file basename (deterministic classification)


@dataclass(frozen=True, slots=True)
class ResolvedFlow:
    """Fully resolved execution parameters for one review run."""

    reviewers: list[str]
    debate_rounds: int
    review_depth: int
    route_decision: RouteDecision | None  # None = fully manual or progressive
    progressive: bool = False  # sentinel-gated mode: params decided mid-run


def load_review_content(
    content: str | None, content_file: Path | None
) -> tuple[str, bool]:
    """Load review content from ``--content`` / ``--file`` / stdin.

    (L-4) ``.json`` verdict files have their reasoning extracted as the
    review text (meta-review scenario). Returns ``(text, came_from_stdin)``.
    """
    if content:
        return content, False
    if content_file:
        raw = content_file.read_text(encoding="utf-8")
        if content_file.suffix == ".json":
            try:
                data = json.loads(raw)
                extracted = (
                    data.get("reasoning")
                    or (data.get("verdict") or {}).get("reasoning")
                    or raw
                )
                return extracted, False
            except json.JSONDecodeError:
                return raw, False
        return raw, False
    if sys.stdin.isatty() is False:
        return sys.stdin.read(), True
    return "", False


def resolve_flow(request: FlowRequest) -> ResolvedFlow:
    """Flow decision: manual > explicit profile > progressive > deterministic fill."""
    if not request.available:
        raise FlowError("reviewers 目录中无可用(非 meta-)reviewer 模板。")

    # zero flow params at all → progressive sentinel-gated mode; the panel,
    # rounds and depth are decided by the gates after Phase 1
    if (
        request.reviewers is None
        and request.profile is None
        and request.debate_rounds is None
        and request.review_depth is None
    ):
        return ResolvedFlow(
            reviewers=[],
            debate_rounds=0,
            review_depth=0,
            route_decision=None,
            progressive=True,
        )

    if request.profile is not None:
        if request.profile not in PROFILE_MAP:
            raise FlowError(
                f"未知 profile '{request.profile}'。可用: {list(PROFILE_MAP)}"
            )
        settings = PROFILE_MAP[request.profile]
        route_decision = RouteDecision(
            content_type="other",
            complexity="medium",
            profile=request.profile,
            reviewer_names=request.reviewers
            or generic_reviewer_combo(request.available, settings["reviewers"]),
            reason=f"explicit profile: {request.profile}",
        )
        return ResolvedFlow(
            reviewers=route_decision.reviewer_names,
            debate_rounds=(
                request.debate_rounds
                if request.debate_rounds is not None
                else settings["debate_rounds"]
            ),
            review_depth=(
                request.review_depth
                if request.review_depth is not None
                else int(settings["meta_review"])
            ),
            route_decision=route_decision,
        )

    # partial manual params: fill gaps deterministically (no LLM call)
    reviewers = request.reviewers
    if reviewers is None:
        _, panel = deterministic_panel(
            request.available,
            PROFILE_MAP["standard"]["reviewers"],
            filename=request.filename,
            content=request.review_content,
        )
        reviewers = panel
    return ResolvedFlow(
        reviewers=reviewers,
        debate_rounds=(
            request.debate_rounds
            if request.debate_rounds is not None
            else PROFILE_MAP["standard"]["debate_rounds"]
        ),
        review_depth=request.review_depth or 0,
        route_decision=None,
    )
