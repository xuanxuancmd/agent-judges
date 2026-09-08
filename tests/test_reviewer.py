"""ReviewerConfig / ReviewerRegistry tests (plan 8-2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adversarial_judge.reviewer import ReviewerConfig, ReviewerRegistry


def test_stock_yaml_loads_all_templates(stock_registry):
    all_reviewers = stock_registry.list_all()
    assert len(all_reviewers) >= 20
    names = {r.name for r in all_reviewers}
    # process-level templates (CyberAgent-inspired)
    assert {"process-compliance-reviewer", "deception-detector",
            "dangerous-operation-scanner"} <= names
    # both meta reviewers (B-3)
    assert {"meta-reviewer", "meta-reviewer-2"} <= names
    # requirement-analysis sub-stages (spec 2.1, omission A-1)
    assert {"requirement-elicitation-reviewer", "requirement-clarification-reviewer",
            "requirement-decomposition-reviewer", "requirement-prioritization-reviewer",
            "requirement-acceptance-reviewer"} <= names
    # post-code-generation sub-stages (spec 2.2, omission A-1)
    assert {"implementation-vs-requirement-reviewer", "unit-test-reviewer",
            "integration-test-reviewer", "deployment-config-reviewer",
            "documentation-reviewer", "test-plan-reviewer"} <= names


def test_get_returns_correct_config(stock_registry):
    r = stock_registry.get("requirement-elicitation-reviewer")
    assert r.model == "anthropic/claude-sonnet-4-20250514"
    assert "需求分析师" in r.system_prompt
    assert len(r.checklist) >= 5


def test_get_nonexistent_raises_key_error_with_available(stock_registry):
    with pytest.raises(KeyError) as exc_info:
        stock_registry.get("nonexistent")
    assert "spec-reviewer" in str(exc_info.value)  # lists available names


def test_meta_reviewer_2_uses_heterogeneous_model(stock_registry):
    assert stock_registry.get("meta-reviewer-2").model == "openai/gpt-4o"


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
