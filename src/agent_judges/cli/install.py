"""``agent-judges install`` — install judge-manager + anonymous reviewer agent (FR-10).

Artifacts are **compiled products**: the in-package templates
(``agent_judges/integrations/``) are the single source of truth; re-run
install after editing templates.

Per platform — everything is namespaced under a ``judges/`` subdirectory so the
installed agents stay visually separate from the user's own agents:
- codeagent:   global ``~/.cac/agents/judges/``,  project ``.cac/agents/judges/``
  (identity comes from the ``name`` frontmatter — same mechanism as claude-code)
- claude-code: global ``~/.claude/agents/judges/``, project ``.claude/agents/judges/``
  (identity comes from the ``name`` frontmatter — the subdirectory does NOT
  change agent names)
- opencode:   global ``~/.config/opencode/agents/judges/``, project ``.opencode/agents/judges/``
  (identity comes from the file PATH — agents register as ``judges/<name>``)

Only two agents are installed:
- **judge-manager** — the externally visible entry-point agent
- **reviewer** — an anonymous, persona-less reviewer slot; the engine compiles
  each reviewer's persona + system-fixed judge frame into the task prompt at
  runtime, so no per-reviewer agent files are needed
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from . import app

__all__ = ["install"]

#: in-package templates (shipped with the wheel)
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "integrations"

#: supported platforms (codeagent is the default — claude-compatible, .cac dir)
_PLATFORMS = ("codeagent", "claude-code", "opencode")

#: the two agents installed per platform
_AGENT_FILES = ("judge-manager", "reviewer")

#: install namespace: all judge agents live in a ``judges/`` subdirectory of
#: the platform's agent dir, keeping them separate from the user's own agents
_SUBDIR = "judges"


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


def _detect_platform() -> str:
    """Auto-detect platform by checking for known host directories."""
    home = Path.home()
    cac = (home / ".cac").is_dir()
    claude = (home / ".claude").is_dir()
    opencode = (home / ".config" / "opencode").is_dir()
    found = [
        p for p, exists in [
            ("codeagent", cac), ("claude-code", claude), ("opencode", opencode),
        ] if exists
    ]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise typer.BadParameter(
            f"检测到多个平台宿主({', '.join(found)}),请用 "
            f"--platform <{'|'.join(_PLATFORMS)}> 显式指定。"
        )
    raise typer.BadParameter(
        "未检测到平台宿主(无 ~/.cac / ~/.claude / ~/.config/opencode),"
        "请用 --platform 显式指定。"
    )


def _agent_dir(platform: str, project: bool) -> Path:
    if platform in ("codeagent", "claude-code"):
        dir_name = ".cac" if platform == "codeagent" else ".claude"
        base = (
            Path(f"{dir_name}/agents") if project
            else Path.home() / dir_name / "agents"
        )
    else:  # opencode
        base = (
            Path(".opencode/agents")
            if project
            else Path.home() / ".config" / "opencode" / "agents"
        )
    return base / _SUBDIR


@app.command()
def install(
    platform: str = typer.Option(
        "codeagent",
        "--platform",
        "--host",  # backward-compat alias (deprecated)
        help="codeagent(默认,claude 兼容机制,.cac 目录) | claude-code | opencode | auto",
    ),
    project: bool = typer.Option(
        False, "--project", help="安装到项目级目录而非用户全局目录"
    ),
):
    """安装 judge-manager + 匿名 reviewer Agent 到平台宿主(编译产物,改模板后重装生效)"""
    resolved = platform if platform != "auto" else _detect_platform()
    if resolved not in _PLATFORMS:
        _echo_err(
            f"Error: 未知 --platform '{resolved}'。可用: {'|'.join(_PLATFORMS)}"
        )
        raise typer.Exit(1)

    target = _agent_dir(resolved, project)
    target.mkdir(parents=True, exist_ok=True)

    # install judge-manager + anonymous reviewer (verbatim template copies)
    for name in _AGENT_FILES:
        template = TEMPLATES_DIR / resolved / "agent" / f"{name}.md"
        if not template.is_file():
            _echo_err(f"Error: 模板缺失: {template}")
            raise typer.Exit(1)
        dest = target / f"{name}.md"
        shutil.copy2(template, dest)
        typer.echo(f"installed: {dest}")

    typer.echo(
        f"\n完成: judge-manager + reviewer Agent → {target}"
    )
