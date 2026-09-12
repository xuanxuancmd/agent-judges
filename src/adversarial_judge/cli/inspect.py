"""``agent-judges list-reviewers`` / ``agent-judges list-skills`` / ``agent-judges inspect-reviewer`` —
inspect available templates, skill packages, and the fully assembled
anonymous-agent prompt.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ..prompts.judge_system import build_system_prompt
from ..reviewer import ReviewerRegistry
from ..skill import SkillRegistry
from . import app


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


def _resolve_skills_dir(skills_dir: Path | None) -> Path | None:
    return skills_dir or (Path("skills") if Path("skills").is_dir() else None)


@app.command("list-reviewers")
def list_reviewers(
    reviewers_dir: Path = typer.Option(
        Path("reviewers"), "--reviewers-dir", help="reviewer 定义目录"
    ),
    skills_dir: Path | None = typer.Option(
        None, "--skills-dir", help="审查 skill 目录(默认: ./skills 若存在)"
    ),
):
    """列出所有可用的 reviewer(含引用的 skill)"""
    try:
        registry = ReviewerRegistry(
            reviewers_dir, skills_dir=_resolve_skills_dir(skills_dir)
        )
    except (FileNotFoundError, ValueError) as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e
    for r in registry.list_all():
        model_str = r.model or "(用默认模型)"
        skills_str = f" [skills: {','.join(r.skills)}]" if r.skills else ""
        typer.echo(f"  {r.name:40s} [{model_str}]{skills_str}  {r.description}")


@app.command("list-skills")
def list_skills(
    skills_dir: Path = typer.Option(
        Path("skills"), "--skills-dir", help="审查 skill 目录"
    ),
):
    """列出所有可用的审查 skill(可通过 -r skill:<name> 即席加载)"""
    try:
        registry = SkillRegistry(skills_dir)
    except FileNotFoundError as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e
    for s in registry.list_all():
        checklist_str = f" ({len(s.checklist)} 项 checklist)" if s.checklist else ""
        typer.echo(f"  {s.name:40s}  {s.description}{checklist_str}")
    _echo_err(
        "\n用法: agent-judges review --llm litellm -r skill:<name> 直接加载,或在 reviewer MD 中通过"
        " skills: [<name>] 引用"
    )


@app.command("inspect-reviewer")
def inspect_reviewer(
    name: str = typer.Argument(
        ..., help="reviewer 名称(支持 skill:<name> 即席形式)"
    ),
    reviewers_dir: Path = typer.Option(
        Path("reviewers"), "--reviewers-dir", help="reviewer 定义目录"
    ),
    skills_dir: Path | None = typer.Option(
        None, "--skills-dir", help="审查 skill 目录(默认: ./skills 若存在)"
    ),
):
    """显示匿名 agent 的完整组装提示词(persona + 已拉起的 skill + 审查框架)

    用于验证 reviewer MD 引用的 skill 是否被正确注入到匿名槽位。
    """
    try:
        registry = ReviewerRegistry(
            reviewers_dir, skills_dir=_resolve_skills_dir(skills_dir)
        )
    except (FileNotFoundError, ValueError) as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e
    try:
        config = registry.get(name)
    except KeyError as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e

    typer.echo(f"# reviewer : {config.name}")
    typer.echo(f"# model    : {config.model or '(CLI --model 默认)'}")
    typer.echo(f"# skills   : {', '.join(config.skills) if config.skills else '(无)'}")
    typer.echo(f"# checklist:")
    for item in config.checklist:
        typer.echo(f"#   - {item.criteria}")
    typer.echo("")
    typer.echo(build_system_prompt(config.system_prompt))
