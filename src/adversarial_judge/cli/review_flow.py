"""Pure helpers for the review command: input loading and the three-tier
flow decision (design.md 4.8) — kept free of typer so they stay unit-testable.

Three-tier decision: explicit fine-grained params > ``--profile`` > auto route.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..llm.broker import LLMBroker
from ..router import PROFILE_MAP, RouteDecision, generic_reviewer_combo, route

__all__ = ["FlowRequest", "ResolvedFlow", "FlowError", "load_review_content", "resolve_flow"]


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


@dataclass(frozen=True, slots=True)
class ResolvedFlow:
    """Fully resolved execution parameters for one review run."""

    reviewers: list[str]
    debate_rounds: int
    review_depth: int
    route_decision: RouteDecision | None  # None = fully manual, no routing


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


def resolve_flow(request: FlowRequest, broker: LLMBroker) -> ResolvedFlow:
    """Three-tier flow decision: manual > explicit profile > auto route."""
    if not request.available:
        raise FlowError("reviewers 目录中无可用(非 meta-)reviewer 模板。")

    route_decision: RouteDecision | None = None
    reviewers = request.reviewers

    if reviewers and request.debate_rounds is not None and request.review_depth is not None:
        pass  # fully manual: no routing needed
    elif request.profile is not None:
        if request.profile not in PROFILE_MAP:
            raise FlowError(f"未知 profile '{request.profile}'。可用: {list(PROFILE_MAP)}")
        settings = PROFILE_MAP[request.profile]
        route_decision = RouteDecision(
            content_type="other",
            complexity="medium",
            profile=request.profile,
            reviewer_names=reviewers
            or generic_reviewer_combo(request.available, settings["reviewers"]),
            reason=f"explicit profile: {request.profile}",
        )
    else:
        # zero-decision: auto route (one lightweight LLM classification)
        route_decision = route(broker, request.review_content, request.available)

    debate_rounds = request.debate_rounds
    review_depth = request.review_depth
    if route_decision is not None:
        if not reviewers:
            reviewers = route_decision.reviewer_names
        if debate_rounds is None:
            debate_rounds = PROFILE_MAP[route_decision.profile]["debate_rounds"]
        if review_depth is None:
            review_depth = int(PROFILE_MAP[route_decision.profile]["meta_review"])

    if not reviewers:
        raise FlowError("未解析出任何 reviewer(请检查 -r 参数或路由结果)。")

    return ResolvedFlow(
        reviewers=reviewers,
        debate_rounds=debate_rounds or 0,
        review_depth=review_depth or 0,
        route_decision=route_decision,
    )
