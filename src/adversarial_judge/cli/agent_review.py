"""``agent-judges review`` — agent-driven mode (default, FR-5/FR-11).

prepare: initialize a run directory pair (logs + evidence), emit the first
task batch, exit.
resume: consume driver-written results, advance the state machine, emit
the next batch or produce the terminal verdict/report.

Run artifacts are split across two roots:

    .harness/logs/judges/<run_id>/      state, tasks/, results/
    .harness/evidence/judges/<run_id>/  verdict.json, report.md

The judge-manager driver agent follows this loop (see
``integrations/<host>/agent/judge-manager.md``):
prepare → run each pending task's agent with the verbatim prompt → write
``results/<id>.md`` → resume → repeat until ``verdict.json`` appears.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import typer

from ..engine import (
    META_REVIEWERS,
    advance,
    build_meta_result,
    build_result,
    build_route_decision,
    prepare_fixed,
    prepare_progressive,
)
from ..output import render_json, render_markdown
from ..reviewer import ReviewerRegistry
from ..run_state import (
    copy_run_output,
    find_latest_run,
    load_state,
    new_run,
    read_results,
    run_dir_layout,
    save_state,
    write_task,
)
from .review_flow import FlowError, FlowRequest, resolve_flow

logger = logging.getLogger(__name__)

__all__ = ["run_agent_review"]


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", text).strip("-").lower()
    return slug[:32] or "content"


def _manifest(
    run_id: str, stage: str, tasks: list, done: bool
) -> dict:
    paths = run_dir_layout(run_id)
    return {
        "done": done,
        "run_id": run_id,
        "logs_dir": str(paths["logs_dir"]),
        "evidence_dir": str(paths["evidence_dir"]),
        "stage": stage,
        "tasks": [
            {
                "task_id": t.task_id,
                "agent": t.agent,
                "kind": t.kind.value,
                "prompt_file": f"tasks/{t.task_id}.md",
                "result_file": f"results/{t.task_id}.md",
            }
            for t in tasks
        ],
    }


def _write_tasks(run_id: str, tasks: list) -> None:
    for t in tasks:
        write_task(run_id, t)


def run_agent_review(
    registry: ReviewerRegistry,
    reviewers_dir: Path,
    content: str,
    filename: str | None,
    context: str | None,
    profile: str | None,
    reviewers: list[str] | None,
    debate_rounds: int | None,
    review_depth: int | None,
    meta_review: bool,
    threshold: float,
    resume: bool,
    output_format: str,
    output_dir: Path | None,
) -> None:
    """Agent-driven prepare/resume; raises typer.Exit on user errors."""
    if output_format not in ("markdown", "json", "both"):
        _echo_err(f"Error: 未知输出格式 '{output_format}'。可用: markdown/json/both")
        raise typer.Exit(1)
    configs = {r.name: r for r in registry.list_all()}
    available = [n for n in configs if not n.startswith("meta-")]

    # ------------------------------------------------------------------ #
    if resume:
        run_id = find_latest_run()
        if run_id is None:
            _echo_err("Error: --resume 未找到可恢复的运行(无未完成的 run)。")
            raise typer.Exit(1)
        state = load_state(run_id)
        results = read_results(run_id)
        state, tasks = advance(state, results, configs)
        save_state(run_id, state)
        _write_tasks(run_id, tasks)
        if state.stage != "done":
            print(
                json.dumps(
                    _manifest(run_id, state.stage, tasks, done=False),
                    ensure_ascii=False,
                )
            )
            _echo_err(
                f"resume: run_id={run_id} | stage={state.stage}, "
                f"待执行任务 {len(tasks)} 个 (已有结果 {len(results)} 份)"
            )
            return
        _emit_final(run_id, state, output_format, output_dir)
        return

    # ------------------------------------------------------------------ #
    # prepare (fresh run)
    if any(r.startswith("skill:") for r in (reviewers or [])):
        _echo_err(
            "Error: agent 模式不支持 -r skill:<name>(知识包无实体宿主 Agent)。"
            "请改用 --llm litellm 直接模式。"
        )
        raise typer.Exit(1)

    meta_available = all(n in configs for n in META_REVIEWERS)
    zero_flow_params = (
        reviewers is None
        and profile is None
        and debate_rounds is None
        and review_depth is None
        and not meta_review
    )

    if zero_flow_params:
        state, tasks = prepare_progressive(
            content=content,
            context=context,
            filename=filename,
            configs=configs,
            available=available,
            threshold=threshold,
            max_tier="thorough" if meta_available else "standard",
        )
    else:
        if meta_review:
            review_depth = max(review_depth or 0, 1)
        try:
            flow = resolve_flow(
                FlowRequest(
                    reviewers=reviewers,
                    debate_rounds=debate_rounds,
                    review_depth=review_depth,
                    profile=profile,
                    review_content=content,
                    available=available,
                    filename=filename,
                )
            )
        except FlowError as e:
            _echo_err(f"Error: {e.message}")
            raise typer.Exit(1) from e
        if flow.review_depth >= 1 and not meta_available:
            _echo_err(
                f"Error: 元审查需要模板 {META_REVIEWERS}(在 {reviewers_dir} 中未找到)。"
            )
            raise typer.Exit(1)
        state, tasks = prepare_fixed(
            content=content,
            context=context,
            filename=filename,
            configs=configs,
            panel=flow.reviewers,
            debate_rounds=flow.debate_rounds,
            review_depth=flow.review_depth,
            threshold=threshold,
        )

    # run directory pair (logs + evidence)
    label = _slugify(filename or "content")
    run_id = new_run(label=label)
    state.run_id = run_id
    save_state(run_id, state)
    _write_tasks(run_id, tasks)

    print(
        json.dumps(
            _manifest(run_id, state.stage, tasks, done=False), ensure_ascii=False
        )
    )
    _echo_err(
        f"prepare: run_id={run_id} | stage={state.stage} | "
        f"任务 {len(tasks)} 个"
        + (
            f" | 哨兵={state.panel[0]} (token={state.token_count})"
            if state.stage == "awaiting_sentinel"
            else f" | 面板={state.panel}"
        )
    )


def _emit_final(
    run_id: str, state, output_format: str, output_dir: Path | None
) -> None:
    """Write verdict.json + report.md to the evidence directory; stdout carries
    the driver manifest (``done: true`` — the judge-manager then reads the
    artifacts to report)."""
    result = build_result(state)
    meta_result = build_meta_result(state)
    route = build_route_decision(state)
    paths = run_dir_layout(run_id)

    json_out = render_json(result, state.threshold, meta_result, None, route)
    md = render_markdown(result, state.threshold, meta_result, route)
    paths["verdict"].write_text(json_out, encoding="utf-8")
    paths["report"].write_text(md, encoding="utf-8")

    print(
        json.dumps(
            {
                "done": True,
                "run_id": run_id,
                "logs_dir": str(paths["logs_dir"]),
                "evidence_dir": str(paths["evidence_dir"]),
                "stage": "done",
                "verdict_file": "verdict.json",
                "report_file": "report.md",
            },
            ensure_ascii=False,
        )
    )

    if output_format == "both":
        if output_dir is None:
            _echo_err("Error: --output both 需要 --output-dir")
            raise typer.Exit(1)
        copy_run_output(run_id, output_dir)

    v = state.verdict
    assert v is not None
    _echo_err(
        f"done: severity={v.severity.value} confidence={v.confidence}"
        + (
            f" calibrated={v.calibrated_confidence}"
            if v.calibrated_confidence is not None
            else ""
        )
        + f" escalate_to_human={v.escalate_to_human} | route: {route.reason}"
    )
