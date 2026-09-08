"""L1 entry router (design.md 4.8): one lightweight LLM classification call
(temperature=0, auditable via ``reason``) decides the profile and reviewer
combination. The pipeline body stays deterministic (L0 rules).

Decision model:
- L1 auto routing (default): route() decides profile + reviewers
- L0 deterministic rules: the debate pipeline itself (see debate.py)
- L2 human override: ``--profile`` or fine-grained CLI parameters

Parse failures degrade to the ``standard`` profile with a generic reviewer
combination (rule-based fallback, never an error — routing is an
optimization, not a dependency).
"""

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from .llm.broker import LLMBroker
from .utils.truncate import truncate_string

logger = logging.getLogger(__name__)

__all__ = ["RouteDecision", "PROFILE_MAP", "route", "generic_reviewer_combo"]

VALID_PROFILES = ("fast", "standard", "thorough")


class RouteDecision(BaseModel):
    """Result of the L1 entry routing (auditable)."""

    content_type: str = "other"  # requirement / spec / design / code / test / agent_log / review_report / other
    complexity: str = "medium"  # low / medium / high
    profile: str = Field(pattern="^(fast|standard|thorough)$")
    reviewer_names: list[str]
    reason: str


ROUTER_SYSTEM_PROMPT = """你是审查流程路由器。分析输入内容的类型与复杂度,返回 JSON:
{"content_type": "...", "complexity": "...", "profile": "fast|standard|thorough", "reviewer_names": ["..."], "reason": "..."}
规则:
- 短文本(<500字)/单一维度 → fast; 常规文档 → standard; 长文档/多维度/关键交付 → thorough
- reviewer_names 从可用列表中选择与内容类型匹配的组合(每档 1/2/3 个)
- reason 说明路由理由(可审计)
- 只输出 JSON,不要其他内容"""

PROFILE_MAP: dict[str, dict] = {
    "fast": {"reviewers": 1, "debate_rounds": 0, "meta_review": False},
    "standard": {"reviewers": 2, "debate_rounds": 1, "meta_review": False},
    "thorough": {"reviewers": 3, "debate_rounds": 2, "meta_review": True},
}


def generic_reviewer_combo(available: list[str], count: int) -> list[str]:
    """Generic deterministic reviewer combo: first ``count`` non-meta reviewers."""
    non_meta = [r for r in available if not r.startswith("meta-")]
    pool = non_meta or available
    if not pool:
        raise ValueError("No available reviewers to route to")
    return pool[:count]


def _default_reviewer_combo(available: list[str]) -> list[str]:
    """Standard-profile fallback combo."""
    return generic_reviewer_combo(available, PROFILE_MAP["standard"]["reviewers"])


def _validate_reviewer_names(names: list, available: list[str], profile: str) -> list[str]:
    """Keep only known reviewers, dedupe (preserve order), cap to the
    profile's reviewer count, ensure at least one."""
    seen: set[str] = set()
    ordered: list[str] = []
    for n in names:
        if n in available and n not in seen:
            seen.add(n)
            ordered.append(n)
    cap = PROFILE_MAP[profile]["reviewers"]
    ordered = ordered[:cap]
    return ordered


def _parse_route(response: str, available: list[str]) -> RouteDecision:
    """Parse the router LLM's JSON response with degradation:
    ```json block → bare JSON → rule-based standard fallback."""
    data = None
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            data = None
    if data is None:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None

    if isinstance(data, dict):
        profile = str(data.get("profile", "standard"))
        if profile not in VALID_PROFILES:
            profile = "standard"
        names = data.get("reviewer_names") or []
        if isinstance(names, str):
            names = [names]
        reviewer_names = _validate_reviewer_names(names, available, profile)
        if not reviewer_names:
            reviewer_names = generic_reviewer_combo(
                available, PROFILE_MAP[profile]["reviewers"]
            )
        return RouteDecision(
            content_type=str(data.get("content_type", "other")),
            complexity=str(data.get("complexity", "medium")),
            profile=profile,
            reviewer_names=reviewer_names,
            reason=str(data.get("reason", "")),
        )

    # fallback: standard profile with a generic combo (rule degradation)
    return RouteDecision(
        content_type="other",
        complexity="medium",
        profile="standard",
        reviewer_names=_default_reviewer_combo(available),
        reason="router parse failed; degraded to standard profile (rule fallback)",
    )


def route(
    broker: LLMBroker, content: str, available_reviewers: list[str]
) -> RouteDecision:
    """Entry routing: one lightweight LLM classification (temp=0).

    The decision selects the profile + reviewer combination; the pipeline
    body remains deterministic (L0 rules in debate.py).
    """
    llm = broker.get_llm()  # default model
    # token-based preview (head matters most for type detection → tail-drop)
    content_preview = truncate_string(content, max_tokens=1500, drop_mode="tail")
    user = (
        f"可用 reviewer: {available_reviewers}\n\n"
        f"内容(截断):\n{content_preview}"
    )
    try:
        response = llm.complete(ROUTER_SYSTEM_PROMPT, user, temperature=0.0)
        decision = _parse_route(response, available_reviewers)
    except Exception as exc:
        logger.warning("auto routing failed (%s); using standard fallback", exc)
        decision = RouteDecision(
            content_type="other",
            complexity="medium",
            profile="standard",
            reviewer_names=_default_reviewer_combo(available_reviewers),
            reason=f"router call failed: {exc}; degraded to standard profile",
        )
    return decision
