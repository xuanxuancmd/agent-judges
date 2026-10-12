"""Skill system tests: SKILL.md parsing, registry, injection, ad-hoc reviewer."""

from __future__ import annotations

import pytest

from agent_judges.reviewer import ReviewerConfig, ReviewerRegistry
from agent_judges.skill import SkillConfig, SkillFileError, SkillRegistry

from fixtures.helpers import make_config

DIR_FORM = """---
name: dir-form-skill
description: directory layout skill
checklist:
  - "检查项 A"
  - criteria: "检查项 B"
    weight: 0.5
---

# 目录式 skill 正文

知识内容……
"""

FLAT_FORM = """---
name: flat-form-skill
description: flat layout skill
---

# 平铺式 skill 正文

知识内容……
"""


@pytest.fixture
def skills_dir(tmp_path):
    (tmp_path / "pkg" / "nested").mkdir(parents=True)  # ensure parents exist
    pkg = tmp_path / "pkg"
    (pkg / "SKILL.md").write_text(DIR_FORM, encoding="utf-8")
    (tmp_path / "flat-form-skill.md").write_text(FLAT_FORM, encoding="utf-8")
    return tmp_path


class TestSkillRegistry:
    def test_loads_both_layouts(self, skills_dir):
        registry = SkillRegistry(skills_dir)
        names = {s.name for s in registry.list_all()}
        assert {"dir-form-skill", "flat-form-skill"} <= names

    def test_frontmatter_checklist_normalized(self, skills_dir):
        skill = SkillRegistry(skills_dir).get("dir-form-skill")
        assert len(skill.checklist) == 2
        assert skill.checklist[0].criteria == "检查项 A"
        assert skill.checklist[1].weight == 0.5

    def test_body_and_description_parsed(self, skills_dir):
        skill = SkillRegistry(skills_dir).get("flat-form-skill")
        assert skill.description == "flat layout skill"
        assert "平铺式 skill 正文" in skill.body

    def test_get_unknown_raises_with_available(self, skills_dir):
        with pytest.raises(KeyError) as exc_info:
            SkillRegistry(skills_dir).get("nope")
        assert "dir-form-skill" in str(exc_info.value)

    def test_missing_frontmatter_raises(self, tmp_path):
        (tmp_path / "bad.md").write_text("# no frontmatter\n", encoding="utf-8")
        with pytest.raises(SkillFileError, match="frontmatter"):
            SkillRegistry(tmp_path)

    def test_empty_body_raises(self, tmp_path):
        (tmp_path / "empty.md").write_text(
            "---\nname: empty-skill\n---\n", encoding="utf-8"
        )
        with pytest.raises(SkillFileError, match="body is empty"):
            SkillRegistry(tmp_path)

    def test_invalid_name_raises(self, tmp_path):
        (tmp_path / "x.md").write_text(
            "---\nname: has spaces\n---\nbody", encoding="utf-8"
        )
        with pytest.raises(SkillFileError, match="slug"):
            SkillRegistry(tmp_path)

    def test_name_falls_back_to_file_stem(self, tmp_path):
        (tmp_path / "stem-named.md").write_text(
            "---\ndescription: d\n---\nbody", encoding="utf-8"
        )
        assert "stem-named" in SkillRegistry(tmp_path).skills

    def test_duplicate_name_raises(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "---\nname: dup\n---\nbody", encoding="utf-8"
        )
        dup_dir = tmp_path / "dup"
        dup_dir.mkdir()
        (dup_dir / "SKILL.md").write_text(
            "---\nname: dup\n---\nbody", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            SkillRegistry(tmp_path)

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SkillRegistry(tmp_path / "nope")


class TestAsReviewer:
    def test_skill_adopts_full_perspective(self, skills_dir):
        skill = SkillRegistry(skills_dir).get("dir-form-skill")
        reviewer = SkillRegistry(skills_dir).as_reviewer("dir-form-skill")
        assert reviewer.name == "skill-dir-form-skill"
        assert reviewer.system_prompt == skill.body  # persona = skill body
        assert len(reviewer.checklist) == 2

    def test_generic_checklist_when_skill_has_none(self, skills_dir):
        reviewer = SkillRegistry(skills_dir).as_reviewer("flat-form-skill")
        assert len(reviewer.checklist) == 1  # generic default


class TestReviewerIntegration:
    def test_referenced_skill_injected_into_persona(self, tmp_path, skills_dir):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "uses_skill.yaml").write_text(
            """
name: uses-skill
description: references a skill
system_prompt: |
  你是某领域审查者。
skills:
  - dir-form-skill
checklist:
  - criteria: c1
""",
            encoding="utf-8",
        )
        registry = ReviewerRegistry(reviewers, skills_dir=skills_dir)
        config = registry.get("uses-skill")
        assert "已加载审查 skill" in config.system_prompt
        assert "目录式 skill 正文" in config.system_prompt
        assert "## skill: dir-form-skill" in config.system_prompt
        assert "你是某领域审查者。" in config.system_prompt  # persona preserved

    def test_skill_reference_without_skills_dir_raises(self, tmp_path):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "uses_skill.yaml").write_text(
            """
name: uses-skill
description: references a skill
system_prompt: persona
skills: [some-skill]
checklist:
  - criteria: c1
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="skills"):
            ReviewerRegistry(reviewers)

    def test_unknown_skill_reference_raises_at_load(self, tmp_path, skills_dir):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "uses_skill.yaml").write_text(
            """
name: uses-skill
description: references an unknown skill
system_prompt: persona
skills: [ghost-skill]
checklist:
  - criteria: c1
""",
            encoding="utf-8",
        )
        with pytest.raises(KeyError, match="ghost-skill"):
            ReviewerRegistry(reviewers, skills_dir=skills_dir)

    def test_skill_prefix_adhoc_reviewer(self, tmp_path, skills_dir):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "dummy.yaml").write_text(
            "name: dummy\ndescription: d\nsystem_prompt: p\n"
            "checklist:\n  - criteria: c\n",
            encoding="utf-8",
        )
        registry = ReviewerRegistry(reviewers, skills_dir=skills_dir)
        reviewer = registry.get("skill:flat-form-skill")
        assert isinstance(reviewer, ReviewerConfig)
        assert reviewer.name == "skill-flat-form-skill"
        assert "平铺式 skill 正文" in reviewer.system_prompt

    def test_skill_prefix_without_skills_dir_raises(self, tmp_path):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "dummy.yaml").write_text(
            "name: dummy\ndescription: d\nsystem_prompt: p\n"
            "checklist:\n  - criteria: c\n",
            encoding="utf-8",
        )
        registry = ReviewerRegistry(reviewers)
        with pytest.raises(KeyError, match="skills"):
            registry.get("skill:whatever")

    def test_explicit_missing_skills_dir_raises_file_not_found(self, tmp_path):
        reviewers = tmp_path / "reviewers"
        reviewers.mkdir()
        (reviewers / "dummy.yaml").write_text(
            "name: dummy\ndescription: d\nsystem_prompt: p\n"
            "checklist:\n  - criteria: c\n",
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError, match="Skills directory"):
            ReviewerRegistry(reviewers, skills_dir=tmp_path / "nope")

    def test_stock_scanner_references_dangerous_operations_skill(
        self, stock_registry
    ):
        scanner = stock_registry.get("dangerous-operation-scanner")
        assert scanner.skills == ["dangerous-operations"]
        assert "危险操作模式清单" in scanner.system_prompt

    def test_stock_skills_loadable_as_reviewers(self, stock_registry):
        reviewer = stock_registry.get("skill:owasp-top10")
        assert reviewer.name == "skill-owasp-top10"
        assert len(reviewer.checklist) == 10


class TestSkillConfigModel:
    def test_frozen(self):
        skill = SkillConfig(name="s", body="b")
        with pytest.raises(Exception):
            setattr(skill, "name", "other")
