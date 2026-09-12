"""``agent-judges review`` — the main adversarial-review command (FR-5).

The typer signature is declarative option wiring; behaviour lives in
``review_flow`` (input + flow decision) and the domain modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from ..debate import DebateOrchestrator
from ..escalation import EscalationRouter
from ..llm.broker import LLMBroker
from ..llm.credentials import env_api_key, is_host_provider
from ..meta_review import MetaReviewer
from ..output import render_json, render_markdown
from ..reviewer import ReviewerRegistry
from . import app
from .review_flow import FlowError, FlowRequest, load_review_content, resolve_flow


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
    reviewers: list[str] | None = typer.Option(
        None, "--reviewer", "-r", help="指定 reviewer 名称(可多次;支持 skill:<name> 即席加载)"
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
    model: str = typer.Option(
        "anthropic/claude-sonnet-4-20250514",
        "--model",
        help="默认 LLM 模型(reviewer 未指定 model 时使用)",
    ),
    override_model: str | None = typer.Option(
        None, "--override-model", help="强制覆盖所有 reviewer 的 model(用于测试)"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="LLM API 网关地址(本地/代理模型)"
    ),
    meta_review: bool = typer.Option(
        False, "--meta-review", help="启用元审查(等价于 --review-depth 1)"
    ),
    review_depth: int | None = typer.Option(
        None, "--review-depth", help="元审查递归深度(默认由 profile 决定,硬上限 2)"
    ),
    max_cost: float | None = typer.Option(
        None, "--max-cost", help="预算上限(USD),超限终止"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="低置信度时暂停等待 stdin 人工裁决(仅 --llm litellm 模式)",
    ),
    llm_backend: str = typer.Option(
        "agent",
        "--llm",
        help="执行模式: agent(默认,prepare/resume 由宿主 judge-manager 驱动) | litellm(引擎进程内直连,CI/调试用)",
    ),
    run_dir: Path | None = typer.Option(
        None, "--run-dir", help="运行目录(agent 模式;prepare 时缺省自动创建)"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="从运行目录恢复推进(agent 模式,需 --run-dir)"
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
    if interactive and content_from_stdin:
        _echo_err(
            "Error: --interactive 不可与 stdin 管道传入内容同用(会抢占 stdin)。"
            "请改用 --file 或 --content。"
        )
        raise typer.Exit(1)

    # ---- registry + broker -------------------------------------------
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

    # ---- agent-driven mode (v2 default, FR-5/FR-11) ----------------------
    if llm_backend == "agent":
        from .agent_review import run_agent_review

        run_agent_review(
            registry=registry,
            reviewers_dir=reviewers_dir,
            content=review_content,
            filename=content_file.name if content_file else None,
            context=context,
            profile=profile,
            reviewers=reviewers,
            debate_rounds=debate_rounds,
            review_depth=review_depth,
            meta_review=meta_review,
            threshold=confidence_threshold,
            run_dir_opt=run_dir,
            resume=resume,
            output_format=output_format,
            output_dir=output_dir,
        )
        return
    if llm_backend != "litellm":
        _echo_err(f"Error: 未知 --llm 模式 '{llm_backend}'。可用: agent | litellm")
        raise typer.Exit(1)

    # ---- legacy direct mode (--llm litellm, CI/调试) ----------------------
    effective_model = override_model or model
    broker = LLMBroker(
        default_model=effective_model,
        default_base_url=base_url,
        max_budget_usd=max_cost,  # api_key=None: litellm resolves per-provider env keys
    )

    # credential hint: the CLI normally inherits the calling agent session's env
    if is_host_provider(effective_model) and not (
        env_api_key(effective_model) or base_url
    ):
        _echo_err(
            f"Warning: 未检测到 {effective_model} 的凭证"
            f"(ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN/CLAUDE_CODE_OAUTH_TOKEN/"
            f"OPENAI_API_KEY)。agent-judges 由 Claude Code / OpenCode 会话调用时凭证自动继承"
            f"(Pro/Max 订阅登录除外,需 claude setup-token 或显式配置);"
            f"独立运行请配置环境变量或 .env,或用 --base-url 指向本地网关。"
        )

    # (M-4) --override-model forces every reviewer's model
    if override_model:
        for r_config in registry.list_all():
            r_config.model = override_model

    # ---- three-tier flow decision (design.md 4.8) ---------------------
    available = [
        r.name for r in registry.list_all() if not r.name.startswith("meta-")
    ]
    if registry.skills is not None:
        # skills are routable as ad-hoc reviewers (skill:<name>)
        available += [f"skill:{s.name}" for s in registry.skills.list_all()]

    filename = content_file.name if content_file else None

    try:
        flow = resolve_flow(
            FlowRequest(
                reviewers=reviewers,
                debate_rounds=debate_rounds,
                review_depth=review_depth,
                profile=profile,
                review_content=review_content,
                available=available,
                filename=filename,
            ),
        )
    except FlowError as e:
        _echo_err(f"Error: {e.message}")
        raise typer.Exit(1) from e

    if flow.route_decision is not None:
        decision = flow.route_decision
        if decision.reason.startswith("explicit"):
            _echo_err(f"profile: {decision.profile} 档, reviewer={decision.reviewer_names}")

    # meta review requires meta-reviewer templates to exist
    meta_missing = [
        n
        for n in MetaReviewer.DEFAULT_META_REVIEWERS
        if n not in registry.reviewers
    ]

    route_decision = flow.route_decision
    orchestrator = DebateOrchestrator(
        registry=registry,
        broker=broker,
        debate_rounds=flow.debate_rounds,
    )

    # ---- run the debate ------------------------------------------------
    if flow.progressive:
        # zero flow params: sentinel-gated progressive review (FR-2)
        result, prog = orchestrator.run_progressive(
            content=review_content,
            context=context,
            filename=filename,
            candidates=available,
            max_tier="thorough" if not meta_missing else "standard",
        )
        route_decision = prog.to_route_decision()
        review_depth = prog.review_depth
        _echo_err(f"渐进式审查: {prog.reason}")
        _echo_err(
            f"使用 reviewer: {prog.reviewers} | 辩论轮次: {prog.debate_rounds} "
            f"| 元审查深度: {review_depth}"
        )
    else:
        # pre-validate reviewer/skill names → clean CLI error, not a traceback
        for name in flow.reviewers:
            try:
                registry.get(name)
            except KeyError as e:
                _echo_err(f"Error: {e}")
                raise typer.Exit(1) from e

        _echo_err(
            f"使用 reviewer: {flow.reviewers} | 辩论轮次: {flow.debate_rounds} "
            f"| 元审查深度: {flow.review_depth}"
        )

        if flow.review_depth >= 1 and meta_missing:
            _echo_err(
                f"Error: 元审查需要模板 {meta_missing}(在 {reviewers_dir} 中未找到)。"
            )
            raise typer.Exit(1)

        result = orchestrator.run(
            content=review_content,
            reviewer_names=flow.reviewers,
            context=context,
            filename=filename,
        )
        review_depth = flow.review_depth

    # ---- meta review (FR-8), recursive depth control --------------------
    meta_result = None
    current_depth = 0
    while current_depth < review_depth:
        result.final_verdict, meta_result = MetaReviewer(orchestrator).review(
            original_content=review_content,
            original_verdict=result.final_verdict,
        )
        current_depth += 1
        # next round's "original content" is the current verdict's reasoning
        review_content = result.final_verdict.reasoning
        _echo_err(
            f"元审查第 {current_depth} 层完成: "
            f"calibrated_confidence={result.final_verdict.calibrated_confidence}"
        )

    # ---- escalation routing (FR-4) --------------------------------------
    escalation_router = EscalationRouter(confidence_threshold=confidence_threshold)
    result.final_verdict = escalation_router.annotate(result.final_verdict)

    # ---- interactive mode (FR-5): pause for human decision ---------------
    if interactive and result.final_verdict.escalate_to_human:
        effective_conf = (
            result.final_verdict.calibrated_confidence
            if result.final_verdict.calibrated_confidence is not None
            else result.final_verdict.confidence
        )
        _echo_err(
            f"\n⚠️  置信度 {effective_conf:.2f} 低于阈值 {confidence_threshold},"
            f"需要人工介入。\n"
            f"请输入人工裁决 (pass/fail + 备注), 或按 Enter 跳过:"
        )
        human_input = sys.stdin.readline().strip()
        if human_input:
            _echo_err(f"人工裁决已记录: {human_input}")
            result.final_verdict.reasoning += f"\n\n[人工裁决]: {human_input}"

    # ---- budget warning ---------------------------------------------------
    if max_cost is not None and not broker.check_budget():
        _echo_err(
            f"Warning: 预算超限 (${broker.get_total_cost():.4f} >= ${max_cost}),"
            f"部分阶段可能已跳过"
        )

    # ---- output (M-7: JSON never to stderr) --------------------------------
    if output_format not in ("markdown", "json", "both"):
        _echo_err(f"Error: 未知输出格式 '{output_format}'。可用: markdown/json/both")
        raise typer.Exit(1)

    if output_format in ("markdown", "both"):
        md = render_markdown(
            result, confidence_threshold, meta_result, route_decision
        )
        if output_format == "markdown":
            print(md)
    if output_format in ("json", "both"):
        json_out = render_json(
            result, confidence_threshold, meta_result, broker, route_decision
        )
        if output_format == "json":
            print(json_out)

    if output_format == "both":
        if output_dir is None:
            _echo_err("Error: --output both 需要 --output-dir")
            raise typer.Exit(1)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.md").write_text(md, encoding="utf-8")
        (output_dir / "verdict.json").write_text(json_out, encoding="utf-8")
        _echo_err(f"报告已写入: {output_dir / 'report.md'}")
        _echo_err(f"JSON 已写入: {output_dir / 'verdict.json'}")
