"""Router tests: RouteDecision, PROFILE_MAP, deterministic zero-LLM
reviewer selection (classify_content / deterministic_panel)."""

from __future__ import annotations

import pytest

from adversarial_judge.router import (
    PROFILE_MAP,
    RouteDecision,
    classify_content,
    deterministic_panel,
    generic_reviewer_combo,
)

AVAILABLE = [
    "spec-reviewer",
    "design-reviewer",
    "requirement-elicitation-reviewer",
    "requirement-clarification-reviewer",
    "meta-reviewer",
    "meta-reviewer-2",
]


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


class TestGenericCombo:
    def test_meta_reviewers_never_selected_by_default(self):
        combo = generic_reviewer_combo(AVAILABLE, 3)
        assert not any(n.startswith("meta-") for n in combo)
        assert combo == [
            "spec-reviewer",
            "design-reviewer",
            "requirement-elicitation-reviewer",
        ]

    def test_count_respected(self):
        assert generic_reviewer_combo(AVAILABLE, 2) == AVAILABLE[:2]


class TestClassifyContent:
    def test_spec_filename(self):
        content_type, preferred = classify_content("spec.md", "任何内容")
        assert content_type == "spec"
        assert preferred == ["spec-reviewer"]

    def test_design_filename(self):
        content_type, preferred = classify_content("design.md", "")
        assert content_type == "design"
        assert preferred == ["design-reviewer"]

    def test_content_heading(self):
        content_type, preferred = classify_content(None, "# 系统设计文档\n正文")
        assert content_type == "design"
        assert preferred == ["design-reviewer"]

    def test_filename_beats_content(self):
        # filename is the stronger signal: spec.md wins over 设计 in content
        content_type, _ = classify_content("spec.md", "# 系统设计文档")
        assert content_type == "spec"

    def test_feature_file_routes_to_test(self):
        content_type, preferred = classify_content("login.feature", "Feature: ...")
        assert content_type == "test"
        assert preferred[0] == "integration-test-reviewer"

    def test_no_match_returns_other(self):
        assert classify_content("notes.txt", "random words") == ("other", [])

    def test_empty_inputs(self):
        assert classify_content(None, "") == ("other", [])


class TestDeterministicPanel:
    def test_preferred_reviewer_is_sentinel(self):
        content_type, panel = deterministic_panel(
            AVAILABLE, 3, filename="spec.md", content="x"
        )
        assert content_type == "spec"
        assert panel[0] == "spec-reviewer"  # sentinel position

    def test_filled_to_size_without_meta(self):
        _, panel = deterministic_panel(AVAILABLE, 3, filename="spec.md")
        assert len(panel) == 3
        assert not any(n.startswith("meta-") for n in panel)

    def test_unavailable_preferred_falls_back_to_generic(self):
        content_type, panel = deterministic_panel(
            ["design-reviewer", "meta-reviewer"], 2, filename="spec.md"
        )
        assert content_type == "spec"  # classification still reported
        assert panel == ["design-reviewer"]  # spec-reviewer not in pool → skipped

    def test_size_one_returns_single_sentinel(self):
        _, panel = deterministic_panel(AVAILABLE, 1, filename="spec.md")
        assert panel == ["spec-reviewer"]

    def test_content_hint_selects_panel(self):
        _, panel = deterministic_panel(AVAILABLE, 2, content="# 需求澄清清单")
        assert panel[0] == "requirement-clarification-reviewer"
        assert len(panel) == 2


class TestRouteDecisionSchema:
    def test_profile_pattern_rejects_invalid(self):
        with pytest.raises(Exception):
            RouteDecision(profile="ultra", reviewer_names=["a"], reason="r")

    def test_minimal_construction(self):
        d = RouteDecision(profile="fast", reviewer_names=["a"], reason="r")
        assert d.content_type == "other"
        assert d.complexity == "medium"

    def test_progressive_audit_fields_default_off(self):
        d = RouteDecision(profile="standard", reviewer_names=["a"], reason="r")
        assert d.token_count is None
        assert d.early_stopped is False
        assert d.gate_reason is None
