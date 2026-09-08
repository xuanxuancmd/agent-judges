"""Auto-router tests: RouteDecision, PROFILE_MAP, fallbacks (plan 8-5)."""

from __future__ import annotations

import pytest

from adversarial_judge.llm.broker import LLMBroker
from adversarial_judge.router import (
    PROFILE_MAP,
    RouteDecision,
    generic_reviewer_combo,
    route,
)

from fixtures.mock_llm import MockLLM, MockLLMBroker

AVAILABLE = [
    "spec-reviewer",
    "design-reviewer",
    "requirement-elicitation-reviewer",
    "meta-reviewer",
    "meta-reviewer-2",
]


def _broker_for(response: str):
    return MockLLMBroker(MockLLM(responses={"审查流程路由器": response}))


class TestProfileMap:
    def test_three_profiles_defined(self):
        assert set(PROFILE_MAP) == {"fast", "standard", "thorough"}

    def test_fast_is_one_call(self):
        p = PROFILE_MAP["fast"]
        assert p == {"reviewers": 1, "debate_rounds": 0, "meta_review": False}

    def test_standard(self):
        p = PROFILE_MAP["standard"]
        assert p["reviewers"] == 2
        assert p["debate_rounds"] == 1
        assert p["meta_review"] is False

    def test_thorough_includes_meta_review(self):
        p = PROFILE_MAP["thorough"]
        assert p["reviewers"] == 3
        assert p["debate_rounds"] == 2
        assert p["meta_review"] is True


class TestRoute:
    def test_valid_json_response(self):
        broker = _broker_for(
            '{"content_type": "spec", "complexity": "high", "profile": "thorough",'
            ' "reviewer_names": ["spec-reviewer", "design-reviewer",'
            ' "requirement-elicitation-reviewer"], "reason": "复杂规格文档"}'
        )
        d = route(broker, "长规格文档内容", AVAILABLE)
        assert isinstance(d, RouteDecision)
        assert d.profile == "thorough"
        assert d.content_type == "spec"
        assert d.reason == "复杂规格文档"
        assert d.reviewer_names == [
            "spec-reviewer",
            "design-reviewer",
            "requirement-elicitation-reviewer",
        ]

    def test_fenced_json_response(self):
        broker = _broker_for(
            '```json\n{"content_type": "requirement", "complexity": "low",'
            ' "profile": "fast", "reviewer_names": ["spec-reviewer"],'
            ' "reason": "短文本"}\n```'
        )
        d = route(broker, "短需求", AVAILABLE)
        assert d.profile == "fast"
        assert d.reviewer_names == ["spec-reviewer"]

    def test_unknown_reviewers_filtered(self):
        broker = _broker_for(
            '{"profile": "standard", "reviewer_names": ["ghost-reviewer",'
            ' "spec-reviewer"], "reason": "r"}'
        )
        d = route(broker, "content", AVAILABLE)
        assert d.reviewer_names == ["spec-reviewer"]  # ghost filtered out

    def test_reviewer_count_capped_to_profile(self):
        broker = _broker_for(
            '{"profile": "fast", "reviewer_names": ["spec-reviewer",'
            ' "design-reviewer", "requirement-elicitation-reviewer"],'
            ' "reason": "r"}'
        )
        d = route(broker, "content", AVAILABLE)
        assert len(d.reviewer_names) == 1  # fast caps at 1

    def test_meta_reviewers_never_selected_by_default(self):
        # generic combo excludes meta-*
        combo = generic_reviewer_combo(AVAILABLE, 3)
        assert not any(n.startswith("meta-") for n in combo)
        assert combo == [
            "spec-reviewer",
            "design-reviewer",
            "requirement-elicitation-reviewer",
        ]

    def test_garbage_response_falls_back_to_standard(self):
        broker = _broker_for("完全不是 JSON 的回复")
        d = route(broker, "content", AVAILABLE)
        assert d.profile == "standard"
        assert len(d.reviewer_names) == 2
        assert "fallback" in d.reason or "degraded" in d.reason

    def test_invalid_profile_falls_back_to_standard(self):
        broker = _broker_for(
            '{"profile": "ultra", "reviewer_names": ["spec-reviewer"], "reason": "r"}'
        )
        d = route(broker, "content", AVAILABLE)
        assert d.profile == "standard"

    def test_llm_failure_falls_back_to_standard(self):
        broker = MockLLMBroker(
            MockLLM(raise_on={"审查流程路由器": RuntimeError("api down")})
        )
        d = route(broker, "content", AVAILABLE)
        assert d.profile == "standard"
        assert "failed" in d.reason

    def test_empty_reviewer_names_falls_back_to_combo(self):
        broker = _broker_for('{"profile": "fast", "reviewer_names": []}')
        d = route(broker, "content", AVAILABLE)
        assert len(d.reviewer_names) == 1


class TestRouteDecisionSchema:
    def test_profile_pattern_rejects_invalid(self):
        with pytest.raises(Exception):
            RouteDecision(
                profile="ultra", reviewer_names=["a"], reason="r"
            )

    def test_minimal_construction(self):
        d = RouteDecision(profile="fast", reviewer_names=["a"], reason="r")
        assert d.content_type == "other"
        assert d.complexity == "medium"
