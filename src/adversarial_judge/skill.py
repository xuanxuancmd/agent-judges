"""External skill packages loaded by anonymous reviewer slots (FR-6).

A *skill* is a user-defined review knowledge/instruction package in
SKILL.md format (Markdown body + YAML frontmatter, compatible with the
industry skill convention). Two on-disk layouts are discovered:

    skills/<name>/SKILL.md     (directory form)
    skills/<name>.md           (flat form)

Pure-LLM paradigm (design.md 1.4/1.6): a skill injects *knowledge* —
rubrics, pattern catalogs, domain checklists — into an anonymous slot's
prompt. It cannot define tools, debate behaviour, or output formats; those
stay system-controlled.

Two usage modes:
1. **Referenced by a reviewer template** — ``skills: [name, ...]`` in the
   reviewer YAML: skill bodies are appended to that reviewer's persona at
   registry-load time.
2. **Loaded directly as an ad-hoc reviewer** — ``-r skill:<name>``: the
   anonymous slot adopts the skill as its complete review perspective.
"""

import logging
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from .reviewer import ChecklistItem, ReviewerConfig

logger = logging.getLogger(__name__)

__all__ = ["SkillConfig", "SkillRegistry"]

# --- boundary parse models (frontmatter is untrusted input) ---------------


class _SkillChecklistItem(BaseModel):
    """A checklist entry inside skill frontmatter."""

    model_config = ConfigDict(extra="forbid")

    criteria: str
    weight: float = 1.0


class _SkillMeta(BaseModel):
    """Parsed YAML frontmatter of a skill file."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str = ""
    checklist: list[str | _SkillChecklistItem] = []


class SkillConfig(BaseModel):
    """A parsed skill package (boundary-parsed, then read-only)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    checklist: list[ChecklistItem] = []
    body: str
    source: str = ""  # originating file path, for error messages

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("skill name must be a slug (alphanumeric + -/_)")
        return v


class SkillFileError(ValueError):
    """A skill file is structurally invalid (typed error for boundary parse)."""

    def __init__(self, path: Path, reason: str):
        super().__init__(f"invalid skill file {path}: {reason}")
        self.path = path
        self.reason = reason


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _to_checklist(raw: list[str | _SkillChecklistItem]) -> list[ChecklistItem]:
    """Normalize frontmatter checklist entries (str or mapping) into models."""
    return [
        ChecklistItem(criteria=entry)
        if isinstance(entry, str)
        else ChecklistItem(criteria=entry.criteria, weight=entry.weight)
        for entry in raw
    ]


def _parse_skill_file(path: Path) -> SkillConfig:
    """Parse one SKILL.md-format file into a SkillConfig (parse, don't validate)."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise SkillFileError(path, "missing YAML frontmatter ('---\\nname: ...\\n---')")
    try:
        meta = _SkillMeta.model_validate(yaml.safe_load(match.group(1)) or {})
    except yaml.YAMLError as exc:
        raise SkillFileError(path, f"frontmatter is not valid YAML: {exc}") from exc
    body = match.group(2).strip()
    if not body:
        raise SkillFileError(path, "skill body is empty")
    fallback_name = (
        path.parent.name if path.name.lower() == "skill.md" else path.stem
    )
    try:
        return SkillConfig(
            name=meta.name or fallback_name,
            description=meta.description,
            checklist=_to_checklist(meta.checklist),
            body=body,
            source=str(path),
        )
    except ValueError as exc:
        raise SkillFileError(path, str(exc)) from exc


class SkillRegistry:
    """Load all skill packages from a directory (both layouts)."""

    def __init__(self, skills_dir: Path):
        skills_dir = Path(skills_dir)
        if not skills_dir.is_dir():
            raise FileNotFoundError(f"Skills directory not found: {skills_dir}")
        self.skills: dict[str, SkillConfig] = {}
        files: list[Path] = []
        # case-insensitive filesystems make "SKILL.md" also match "skill.md";
        # dedupe explicitly so a file is never registered twice
        for pattern in ("*/SKILL.md", "*/skill.md", "*.md"):
            for found in sorted(skills_dir.glob(pattern)):
                if found not in files:
                    files.append(found)
        for skill_file in files:
            config = _parse_skill_file(skill_file)
            if config.name in self.skills:
                raise ValueError(
                    f"Duplicate skill name '{config.name}' "
                    f"(defined again in {skill_file})"
                )
            self.skills[config.name] = config

    def get(self, name: str) -> SkillConfig:
        if name not in self.skills:
            raise KeyError(
                f"Skill '{name}' not found. Available: {sorted(self.skills)}"
            )
        return self.skills[name]

    def list_all(self) -> list[SkillConfig]:
        return list(self.skills.values())

    def as_reviewer(self, skill_name: str) -> ReviewerConfig:
        """Adopt a skill as a complete review perspective for one anonymous
        slot (the ``-r skill:<name>`` ad-hoc reviewer mode)."""
        skill = self.get(skill_name)
        checklist = skill.checklist or [
            ChecklistItem(criteria="按 skill 指令完成审查")
        ]
        return ReviewerConfig(
            name=f"skill-{skill.name}",
            description=skill.description or f"skill: {skill.name}",
            system_prompt=skill.body,
            checklist=checklist,
        )
