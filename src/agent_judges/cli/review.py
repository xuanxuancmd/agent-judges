"""``agent-judges review`` — the adversarial-review command (FR-5).

Agent-driven mode only: prepare/resume state machine driven by the
judge-manager agent in the host (Claude Code / OpenCode). The LLM
capability comes from the host's reviewer agents — no direct LLM calls,
no litellm, no API keys.
"""

from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

from . import app
from .review_flow import load_review_content
from ..reviewer import ReviewerRegistry

__all__ = ["review"]


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


@app.command()
def review(
    content: str | None = typer.Option(
        None, "--content", "-c", help="被审查内容(直接传入文本)"
    ),
    content_file: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="从文件读取被审查内容(.json 自动提取 verdict 字段)",
    ),
    context: str | None = typer.Option(
        None, "--context", help="背景上下文(需求文档/设计文档等)"
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="预设档位: fast/standard/thorough。不指定且无细粒度参数时走 auto 路由",
    ),
    scene: str = typer.Option(
        None, "--scene", "-s",
        help="审查场景: document(文档) / code(代码) / review-report(检视报告)。不指定时按后缀判断(.py→code, .md→document)"
    ),
    reviewers_dir: Path = typer.Option(
        Path("reviewers"), "--reviewers-dir", help="reviewer 定义目录"
    ),
    skills_dir: Path | None = typer.Option(
        None, "--skills-dir", help="审查 skill 目录(默认: ./skills 若存在)"
    ),
    output_format: str = typer.Option(
        "markdown", "--output", "-o", help="输出格式: markdown/json/both"
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="输出目录(--output both 时必须)"
    ),
    confidence_threshold: float = typer.Option(
        0.8, "--threshold", "-t", help="置信度阈值,低于此值标记人工审查"
    ),
    debate_rounds: int | None = typer.Option(
        None, "--debate-rounds", help="辩论轮次(不指定时由 profile/auto 决定)"
    ),
    meta_review: bool = typer.Option(
        False, "--meta-review", help="启用元审查(等价于 --review-depth 1)"
    ),
    review_depth: int | None = typer.Option(
        None, "--review-depth", help="元审查递归深度(默认由 profile 决定,硬上限 2)"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="从最新运行目录恢复推进(agent 模式,自动查找未完成的 run)"
    ),
):
    """对抗审查: 对 AI 生成的内容进行多 agent 辩论式审查"""

    load_dotenv()

    # (B-2) review_depth hard cap; --meta-review == --review-depth 1
    if review_depth is not None and review_depth > 2:
        _echo_err("Error: --review-depth 上限为 2")
        raise typer.Exit(1)
    if meta_review:
        review_depth = max(review_depth or 0, 1)

    # ---- input: --content / --file / stdin ---------------------------
    # (--resume skips input entirely: the content snapshot lives in the run dir)
    review_content, content_from_stdin = load_review_content(content, content_file)
    if not resume and not review_content.strip():
        _echo_err("Error: 无审查内容。请通过 --content / --file / stdin 传入。")
        raise typer.Exit(1)

    # ---- registry ----------------------------------------------------
    resolved_skills_dir = skills_dir or (
        Path("skills") if Path("skills").is_dir() else None
    )
    try:
        registry = ReviewerRegistry(reviewers_dir, skills_dir=resolved_skills_dir)
    except (FileNotFoundError, ValueError) as e:
        # ValueError covers unresolvable skill references and malformed
        # reviewer/skill files — all are user-facing config errors
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e

    # ---- agent-driven mode (default, FR-5/FR-11) ----------------------
    from .agent_review import run_agent_review

    run_agent_review(
        registry=registry,
        reviewers_dir=reviewers_dir,
        content=review_content,
        filename=content_file.name if content_file else None,
        context=context,
        profile=profile,
        scene=scene,
        debate_rounds=debate_rounds,
        review_depth=review_depth,
        meta_review=meta_review,
        threshold=confidence_threshold,
        resume=resume,
        output_format=output_format,
        output_dir=output_dir,
    )
