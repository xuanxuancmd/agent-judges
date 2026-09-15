"""ReviewerConfig / ReviewerRegistry tests (plan 8-2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adversarial_judge.reviewer import ReviewerConfig, ReviewerRegistry


def test_stock_yaml_loads_all_templates(stock_registry):
    all_reviewers = stock_registry.list_all()
    assert len(all_reviewers) >= 14
    names = {r.name for r in all_reviewers}
    # adversarial / process-level
    assert {"deception-detector",
            "dangerous-operation-scanner"} <= names
    # both meta reviewers (B-3)
    assert {"meta-reviewer", "meta-reviewer-2"} <= names
    # document reviewers
    assert {"spec-reviewer", "design-reviewer", "documentation-reviewer",
            "test-plan-reviewer"} <= names
    # post-code-generation sub-stages (spec 2.2, omission A-1)
    assert {"implementation-vs-requirement-reviewer", "unit-test-reviewer",
            "integration-test-reviewer", "deployment-config-reviewer"} <= names


def test_get_returns_correct_config(stock_registry):
    r = stock_registry.get("spec-reviewer")
    # v2: model values were removed during the MD migration (host default);
    # users opt into a host-namespace model per reviewer when wanted
    assert r.model is None
    assert "规格" in r.system_prompt
    assert len(r.checklist) >= 5


def test_get_nonexistent_raises_key_error_with_available(stock_registry):
    with pytest.raises(KeyError) as exc_info:
        stock_registry.get("nonexistent")
    assert "spec-reviewer" in str(exc_info.value)  # lists available names


def test_meta_reviewer_2_model_unset_after_md_migration(stock_registry):
    # v2 migration: no litellm model strings; host-namespace model is opt-in
    assert stock_registry.get("meta-reviewer-2").model is None


def test_model_none_loads_fine(stock_registry):
    assert stock_registry.get("external-code-review-auditor").model is None


def test_missing_name_raises_validation_error():
    with pytest.raises(ValidationError):
        ReviewerConfig(
            description="no name",
            system_prompt="x",
            checklist=[{"criteria": "c"}],
        )


def test_name_with_spaces_raises_validation_error():
    with pytest.raises(ValidationError):
        ReviewerConfig(
            name="has spaces",
            description="d",
            system_prompt="x",
            checklist=[{"criteria": "c"}],
        )


def test_majority_vote_must_be_positive():
    with pytest.raises(ValidationError):
        ReviewerConfig(
            name="bad-vote",
            description="d",
            system_prompt="x",
            checklist=[{"criteria": "c"}],
            majority_vote=0,
        )


def test_yml_suffix_supported(tmp_path):
    (tmp_path / "r1.yml").write_text(
        """
name: yml-reviewer
description: loaded from .yml
system_prompt: persona
checklist:
  - criteria: c1
""",
        encoding="utf-8",
    )
    registry = ReviewerRegistry(tmp_path)
    assert "yml-reviewer" in registry.reviewers


def test_markdown_format_loads(tmp_path):
    # v2 source format: frontmatter metadata + persona body
    (tmp_path / "r1.md").write_text(
        """---
name: md-reviewer
description: loaded from markdown
# model: opus    # optional host-namespace model (commented = host default)
weight: 1.5
checklist:
  - criteria: c1
  - criteria: c2
    weight: 0.5
---

你是一位审查者,关注质量。
""",
        encoding="utf-8",
    )
    registry = ReviewerRegistry(tmp_path)
    r = registry.get("md-reviewer")
    assert r.system_prompt == "你是一位审查者,关注质量。"
    assert r.model is None
    assert r.weight == 1.5
    assert [c.criteria for c in r.checklist] == ["c1", "c2"]
    assert r.checklist[1].weight == 0.5


def test_markdown_model_field_parsed(tmp_path):
    (tmp_path / "r1.md").write_text(
        """---
name: modelled-reviewer
description: d
model: opus
checklist:
  - criteria: c1
---

persona body
""",
        encoding="utf-8",
    )
    assert ReviewerRegistry(tmp_path).get("modelled-reviewer").model == "opus"


def test_markdown_missing_frontmatter_errors(tmp_path):
    (tmp_path / "bad.md").write_text("just a persona, no frontmatter", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter"):
        ReviewerRegistry(tmp_path)


def test_markdown_empty_body_errors(tmp_path):
    (tmp_path / "empty.md").write_text(
        """---
name: empty-reviewer
description: d
checklist:
  - criteria: c1
---
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="persona body is empty"):
        ReviewerRegistry(tmp_path)


def test_markdown_wins_over_same_stem_yaml(tmp_path):
    (tmp_path / "r1.yaml").write_text(
        "name: from-yaml\ndescription: d\nsystem_prompt: yaml persona\n"
        "checklist:\n  - criteria: c\n",
        encoding="utf-8",
    )
    (tmp_path / "r1.md").write_text(
        "---\nname: from-md\ndescription: d\nchecklist:\n  - criteria: c\n---\n\nmd persona\n",
        encoding="utf-8",
    )
    registry = ReviewerRegistry(tmp_path)
    assert set(registry.reviewers) == {"from-yaml", "from-md"}


def test_duplicate_name_raises(tmp_path):
    body = """
name: dup-reviewer
description: d
system_prompt: persona
checklist:
  - criteria: c1
"""
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        ReviewerRegistry(tmp_path)


def test_missing_dir_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReviewerRegistry(tmp_path / "nope")
