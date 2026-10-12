"""Router tests: RouteDecision, PROFILE_MAP, deterministic zero-LLM
reviewer selection (filter_by_scene / infer_scene_from_filename /
deterministic_panel)."""

from __future__ import annotations

import pytest

from agent_judges.router import (
    PROFILE_MAP,
    SCENES,
    RouteDecision,
    deterministic_panel,
    filter_by_scene,
    generic_reviewer_combo,
    infer_scene_from_filename,
)

AVAILABLE = [
    "spec-reviewer",
    "design-reviewer",
    "documentation-reviewer",
    "test-plan-reviewer",
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


class TestScenes:
    def test_three_scenes_defined(self):
        assert SCENES == ("document", "code", "review-report")


class TestGenericCombo:
    def test_meta_reviewers_never_selected_by_default(self):
        combo = generic_reviewer_combo(AVAILABLE, 3)
        assert not any(n.startswith("meta-") for n in combo)
        assert combo == [
            "spec-reviewer",
            "design-reviewer",
            "documentation-reviewer",
        ]

    def test_count_respected(self):
        assert generic_reviewer_combo(AVAILABLE, 2) == AVAILABLE[:2]


class TestInferSceneFromFilename:
    def test_code_extension_py(self):
        assert infer_scene_from_filename("engine.py") == "code"

    def test_code_extension_ts(self):
        assert infer_scene_from_filename("app.tsx") == "code"

    def test_code_extension_go(self):
        assert infer_scene_from_filename("main.go") == "code"

    def test_prose_extension_md(self):
        assert infer_scene_from_filename("spec.md") == "document"

    def test_prose_extension_txt(self):
        assert infer_scene_from_filename("notes.txt") == "document"

    def test_unknown_extension(self):
        assert infer_scene_from_filename("data.xyz") == "document"

    def test_none_filename(self):
        assert infer_scene_from_filename(None) == "document"

    def test_empty_filename(self):
        assert infer_scene_from_filename("") == "document"

    def test_no_extension(self):
        assert infer_scene_from_filename("README") == "document"


class TestFilterByScene:
    def _scenes_map(self):
        return {
            "spec-reviewer": ["document"],
            "design-reviewer": ["document"],
            "unit-test-reviewer": ["code"],
            "integration-test-reviewer": ["code"],
            "meta-reviewer": [],  # system-internal, not routed by scene
        }

    def test_filters_to_document_reviewers(self):
        available = ["spec-reviewer", "unit-test-reviewer", "meta-reviewer"]
        pool = filter_by_scene(available, self._scenes_map(), "document")
        assert pool == ["spec-reviewer"]

    def test_filters_to_code_reviewers(self):
        available = ["spec-reviewer", "unit-test-reviewer", "meta-reviewer"]
        pool = filter_by_scene(available, self._scenes_map(), "code")
        assert pool == ["unit-test-reviewer"]

    def test_empty_scenes_excluded(self):
        # reviewers with empty scenes list are system-internal, excluded
        available = ["meta-reviewer", "spec-reviewer"]
        pool = filter_by_scene(available, self._scenes_map(), "document")
        assert pool == ["spec-reviewer"]

    def test_no_match_returns_available_as_fallback(self):
        available = ["meta-reviewer"]  # only system-internal, no scene match
        pool = filter_by_scene(available, self._scenes_map(), "document")
        assert pool == ["meta-reviewer"]  # fallback to full available

    def test_multiple_matches_preserve_order(self):
        available = [
            "spec-reviewer",
            "design-reviewer",
            "unit-test-reviewer",
        ]
        pool = filter_by_scene(available, self._scenes_map(), "document")
        assert pool == ["spec-reviewer", "design-reviewer"]


class TestDeterministicPanel:
    def test_returns_list_not_tuple(self):
        panel = deterministic_panel(AVAILABLE, 3)
        assert isinstance(panel, list)

    def test_first_reviewer_is_sentinel(self):
        panel = deterministic_panel(AVAILABLE, 3)
        assert panel[0] == "spec-reviewer"  # sentinel position

    def test_filled_to_size_without_meta(self):
        panel = deterministic_panel(AVAILABLE, 3)
        assert len(panel) == 3
        assert not any(n.startswith("meta-") for n in panel)

    def test_size_one_returns_single_sentinel(self):
        panel = deterministic_panel(AVAILABLE, 1)
        assert panel == ["spec-reviewer"]

    def test_size_two_returns_two(self):
        panel = deterministic_panel(AVAILABLE, 2)
        assert panel == ["spec-reviewer", "design-reviewer"]

    def test_excludes_generic_excluded_reviewers(self):
        # my-security-auditor is in _GENERIC_EXCLUDE (example, not production)
        pool = [
            "spec-reviewer",
            "my-security-auditor",
            "design-reviewer",
        ]
        panel = deterministic_panel(pool, 3)
        assert "my-security-auditor" not in panel
        assert panel == ["spec-reviewer", "design-reviewer"]

    def test_pool_smaller_than_size_returns_pool(self):
        panel = deterministic_panel(["spec-reviewer"], 3)
        assert panel == ["spec-reviewer"]


class TestRouteDecisionSchema:
    def test_profile_pattern_rejects_invalid(self):
        with pytest.raises(Exception):
            RouteDecision(profile="ultra", reviewer_names=["a"], reason="r")

    def test_minimal_construction(self):
        d = RouteDecision(profile="fast", reviewer_names=["a"], reason="r")
        assert d.content_type == "document"
        assert d.complexity == "medium"

    def test_progressive_audit_fields_default_off(self):
        d = RouteDecision(profile="standard", reviewer_names=["a"], reason="r")
        assert d.token_count is None
        assert d.early_stopped is False
        assert d.gate_reason is None
