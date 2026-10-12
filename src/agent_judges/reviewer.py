"""Pluggable reviewer definitions loaded from external Markdown files (FR-6).

Source format (v2): ``reviewers/*.md`` — YAML frontmatter (orchestration
metadata) + Markdown body (the persona, formerly ``system_prompt``). Legacy
``*.yaml`` files are still loaded during the transition period.

Constraint model (design.md 1.6): the system provides *anonymous* debater
slots with a fixed behaviour frame; user templates only inject a review
perspective (persona + checklist). Debate behaviour, output schema and
pipeline orchestration are system-controlled. ``agent-judges install``
compiles these sources into host agent definitions (FR-10).
"""

import logging
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

__all__ = ["ChecklistItem", "ReviewerConfig", "ReviewerRegistry"]

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class ChecklistItem(BaseModel):
    """One checklist dimension of a review perspective."""

    criteria: str
    weight: float = Field(default=1.0, gt=0)  # checklist-item weight


class ReviewerConfig(BaseModel):
    """A review perspective template (anonymous slot + injected perspective).

    ``model`` is optional (M-4): when unset, the broker default model is used.
    ``majority_vote`` (G-5): N same-model calls with vote aggregation —
    AaaJ's lightweight anti-hallucination mechanism.
    ``skills``: names of skill packages (knowledge injection) whose bodies
    are appended to this reviewer's system prompt at registry-load time.
    ``scenes``: applicable review scenes (document/code/review-report).
    Empty list = not routed by scene (e.g. meta-reviewer, system-internal).

    Mutable by design: the CLI overrides ``model`` at runtime
    (``--override-model``) and the registry appends resolved skill bodies
    to ``system_prompt``; the mutation purpose is documented here.
    """

    name: str  # unique slug identifier
    description: str
    model: str | None = None
    system_prompt: str
    checklist: list[ChecklistItem]
    weight: float = Field(default=1.0, gt=0)
    majority_vote: int = Field(default=1, ge=1)
    skills: list[str] = []
    scenes: list[str] = []
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_strategy: str | None = None  # 落地项 2: checklist/inverse/transform/counterfactual/falsification

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("name must be a slug (alphanumeric + -/_)")
        return v


class ReviewerRegistry:
    """Load all reviewer perspective templates from a directory.

    ``skills_dir`` (optional) enables skill support: templates referencing
    skills via their ``skills:`` field get the skill bodies injected into
    their system prompt, and ``get("skill:<name>")`` adopts a skill as an
    ad-hoc reviewer.
    """

    SKILL_PREFIX = "skill:"

    def __init__(self, reviewers_dir: Path, skills_dir: Path | None = None):
        reviewers_dir = Path(reviewers_dir)
        if not reviewers_dir.is_dir():
            raise FileNotFoundError(
                f"Reviewers directory not found: {reviewers_dir}"
            )
        # lazy import: skill.py imports this module at top level
        from .skill import SkillRegistry

        self.skills: SkillRegistry | None = None
        if skills_dir is not None:
            # an explicitly configured skills dir must exist (fail fast);
            # the CLI only auto-detects existing dirs and passes None otherwise
            if not Path(skills_dir).is_dir():
                raise FileNotFoundError(f"Skills directory not found: {skills_dir}")
            self.skills = SkillRegistry(skills_dir)
        self.reviewers: dict[str, ReviewerConfig] = {}
        # MD is the v2 source format; YAML remains loadable during the
        # transition. True same-name conflicts raise a duplicate error.
        md_files = sorted(reviewers_dir.glob("*.md"))
        legacy_yaml = sorted(reviewers_dir.glob("*.y*ml"))
        for source in md_files + legacy_yaml:
            if source.suffix.lower() == ".md":
                data = self._parse_markdown(source)
            else:
                data = yaml.safe_load(source.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(
                    f"Invalid reviewer file (not a mapping): {source}"
                )
            config = ReviewerConfig(**data)
            if config.name in self.reviewers:
                raise ValueError(
                    f"Duplicate reviewer name '{config.name}' "
                    f"(defined again in {source})"
                )
            self.reviewers[config.name] = config
        for config in self.reviewers.values():
            self._resolve_skills(config)

    @staticmethod
    def _parse_markdown(path: Path) -> dict:
        """Parse a reviewer MD file: frontmatter metadata + persona body."""
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        if match is None:
            raise ValueError(
                f"Invalid reviewer file {path}: "
                f"missing YAML frontmatter ('---\\nname: ...\\n---')"
            )
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid frontmatter YAML in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Invalid frontmatter (not a mapping) in {path}")
        persona = match.group(2).strip()
        if not persona:
            raise ValueError(f"Invalid reviewer file {path}: persona body is empty")
        data["system_prompt"] = persona
        return data

    def _resolve_skills(self, config: ReviewerConfig) -> None:
        """Inject referenced skill bodies into the reviewer's persona."""
        if not config.skills:
            return
        if self.skills is None:
            raise ValueError(
                f"reviewer '{config.name}' 引用了 skills {config.skills},"
                f"但未配置 skills 目录(--skills-dir)"
            )
        blocks = [config.system_prompt.rstrip(), "", "# 已加载审查 skill(知识注入)"]
        for skill_name in config.skills:
            skill = self.skills.get(skill_name)
            header = f"## skill: {skill.name}"
            if skill.description:
                header += f" — {skill.description}"
            blocks.append(f"{header}\n\n{skill.body}")
        config.system_prompt = "\n\n".join(blocks)

    def get(self, name: str) -> ReviewerConfig:
        if name.startswith(self.SKILL_PREFIX):
            if self.skills is None:
                raise KeyError(
                    "'skill:' 前缀需要配置 skills 目录(--skills-dir)"
                )
            return self.skills.as_reviewer(name[len(self.SKILL_PREFIX):])
        if name not in self.reviewers:
            raise KeyError(
                f"Reviewer '{name}' not found. Available: {sorted(self.reviewers)}"
            )
        return self.reviewers[name]

    def list_all(self) -> list[ReviewerConfig]:
        return list(self.reviewers.values())
