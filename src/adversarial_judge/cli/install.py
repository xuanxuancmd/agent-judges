"""``agent-judges install`` — install judge-manager + reviewer agents (FR-10).

Artifacts are **compiled products**: the reviewer sources (``reviewers/*.md``)
and the in-package templates (``adversarial_judge/integrations/``) are the
single source of truth; re-run install after editing sources.

Per host:
- claude-code: global ``~/.claude/agents/``, project ``.claude/agents/``
- opencode:   global ``~/.config/opencode/agent/``, project ``.opencode/agent/``

Generated reviewer agents carry a "do not invoke directly" description
prefix and the system-fixed judge frame merged into the persona body;
engine-only frontmatter keys (checklist/weight/majority_vote/skills) are
stripped — they live in the engine-side sources.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from ..prompts.judge_system import build_system_prompt
from ..reviewer import ReviewerRegistry
from . import app

__all__ = ["install"]

#: in-package templates (shipped with the wheel)
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "integrations"

_HOSTS = ("claude-code", "opencode")

_NO_DIRECT_INVOKE_PREFIX = (
    "内部审查组件,由 judge-manager 经 agent-judges 引擎编排调用,请勿直接触发。"
)


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


def _detect_host() -> str:
    home = Path.home()
    claude = (home / ".claude").is_dir()
    opencode = (home / ".config" / "opencode").is_dir()
    if claude and not opencode:
        return "claude-code"
    if opencode and not claude:
        return "opencode"
    if claude and opencode:
        raise typer.BadParameter(
            "检测到多个宿主(~/.claude 与 ~/.config/opencode 并存),请用 "
            "--host claude-code 或 --host opencode 显式指定。"
        )
    raise typer.BadParameter(
        "未检测到宿主(无 ~/.claude 或 ~/.config/opencode),请用 --host 显式指定。"
    )


def _agent_dir(host: str, project: bool) -> Path:
    if project:
        return Path(".claude/agents") if host == "claude-code" else Path(".opencode/agent")
    home = Path.home()
    return (
        (home / ".claude" / "agents")
        if host == "claude-code"
        else (home / ".config" / "opencode" / "agent")
    )


def _generate_reviewer_agent_md(name: str, description: str, model: str | None,
                                persona: str, host: str) -> str:
    """Compile one reviewer source into a host agent definition."""
    fm: dict = {
        "name": name,
        "description": _NO_DIRECT_INVOKE_PREFIX + description,
    }
    if model:
        fm["model"] = model  # host namespace, passed through verbatim
    if host == "opencode":
        fm["mode"] = "subagent"
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {_yaml_inline(value)}")
    lines.append("---")
    # persona + system-fixed judge frame (the anonymous-slot constraint)
    body = build_system_prompt(persona)
    return "\n".join(lines) + "\n\n" + body + "\n"


def _yaml_inline(value) -> str:
    if isinstance(value, str):
        if any(ch in value for ch in ":#{}[]\"'"):
            return '"' + value.replace('"', '\\"') + '"'
        return value
    return str(value)


@app.command()
def install(
    host: str = typer.Option(
        "auto", "--host", help="claude-code | opencode | auto(按已存在目录探测)"
    ),
    project: bool = typer.Option(
        False, "--project", help="安装到项目级目录而非用户全局目录"
    ),
    reviewers_dir: Path = typer.Option(
        Path("reviewers"), "--reviewers-dir", help="reviewer 源目录"
    ),
    skills_dir: Path | None = typer.Option(
        None, "--skills-dir", help="审查 skill 目录(默认: ./skills 若存在)"
    ),
):
    """安装 judge-manager 与全部 reviewer Agent 到宿主(编译产物,改源后重装生效)"""
    resolved_host = host if host != "auto" else _detect_host()
    if resolved_host not in _HOSTS:
        _echo_err(f"Error: 未知 --host '{resolved_host}'。可用: {'|'.join(_HOSTS)}")
        raise typer.Exit(1)

    template = TEMPLATES_DIR / resolved_host / "agent" / "judge-manager.md"
    if not template.is_file():
        _echo_err(f"Error: judge-manager 模板缺失: {template}")
        raise typer.Exit(1)

    resolved_skills = skills_dir or (
        Path("skills") if Path("skills").is_dir() else None
    )
    try:
        registry = ReviewerRegistry(reviewers_dir, skills_dir=resolved_skills)
    except (FileNotFoundError, ValueError) as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e

    target = _agent_dir(resolved_host, project)
    target.mkdir(parents=True, exist_ok=True)

    # 1) judge-manager (verbatim template copy)
    dest = target / "judge-manager.md"
    shutil.copy2(template, dest)
    typer.echo(f"installed: {dest}")

    # 2) reviewer agents (compiled from sources)
    count = 0
    for cfg in sorted(registry.list_all(), key=lambda c: c.name):
        agent_md = _generate_reviewer_agent_md(
            name=cfg.name,
            description=cfg.description,
            model=cfg.model,
            persona=cfg.system_prompt,
            host=resolved_host,
        )
        dest = target / f"{cfg.name}.md"
        dest.write_text(agent_md, encoding="utf-8")
        count += 1
        typer.echo(f"installed: {dest}")

    typer.echo(
        f"\n完成: judge-manager + {count} 个 reviewer Agent → {target}\n"
        f"(编译产物;修改 {reviewers_dir}/ 或模板后重新 install 生效)"
    )
