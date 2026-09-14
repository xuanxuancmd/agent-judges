#!/usr/bin/env python
"""agent-judges e2e 手动运行器（CI/裸机回退路径）— 对 tests/project/ 下的真实需求文档跑完整对抗审查。

注意: 这是 `--llm litellm` 直连的回退路径,需 API key 凭证;主路径为宿主驱动
(judge-manager + 实体 reviewer Agent,零 API key),见 README「E2E 测试 · 手动 · 主路径」。

模拟 judge-manager 驱动协议(agent 模式 prepare/resume),把每一轮任务交给
真实 LLM(--llm litellm,默认)或固定应答(--llm mock,零 token 冒烟)回答,
终态产物落在 reports/e2e/<project>/<target>/(verdict.json + report.md + 全程审计文件)。

用法示例:

    python scripts/e2e_review.py                              # 两个项目 x spec/plan,真实 LLM
    python scripts/e2e_review.py --project todo-app --target spec
    python scripts/e2e_review.py --llm mock                  # 零 token 冒烟(固定应答)
    python scripts/e2e_review.py --profile thorough --max-calls 200
    python scripts/e2e_review.py --model openai/gpt-4o --base-url http://127.0.0.1:4010

前提: ``pip install -e .``;真实 LLM 模式需要环境变量凭证(同 tests/test_integration.py)。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from fixtures.e2e_driver import (  # noqa: E402
    PROJECTS_DIR,
    LitellmAnswerer,
    MockScenarioAnswerer,
    drive_review,
)

DEFAULT_PROJECTS = ("todo-app", "graphify-gitnexus")
TARGETS = ("spec", "plan")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="agent-judges e2e 手动运行器(真实需求文档 × 完整审查链路)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--project", action="append", choices=DEFAULT_PROJECTS,
        help="要审查的项目(可多次;默认全部)",
    )
    parser.add_argument(
        "--target", action="append", choices=TARGETS,
        help="要审查的文档(可多次;默认 spec+plan;plan 自动以 spec 为上下文)",
    )
    parser.add_argument(
        "--llm", choices=("litellm", "mock"), default="litellm",
        help="回答后端: litellm=真实 LLM | mock=固定应答(零 token 冒烟)",
    )
    parser.add_argument(
        "--scenario", choices=("clean", "problem"), default="problem",
        help="mock 模式的固定应答场景",
    )
    parser.add_argument(
        "--model", default=None,
        help="litellm 模式使用的模型(默认 anthropic/claude-sonnet-4-20250514)",
    )
    parser.add_argument("--base-url", default=None, help="LLM API 网关地址")
    parser.add_argument(
        "--max-calls", type=int, default=120,
        help="单次审查最大 LLM 调用数(安全阀,防止流程异常导致失控计费)",
    )
    parser.add_argument(
        "--profile", choices=("auto", "fast", "standard", "thorough"), default="auto",
        help="审查档位: auto=零参数渐进式门控 | 其余为显式档位",
    )
    parser.add_argument("--threshold", type=float, default=0.8, help="置信度阈值")
    parser.add_argument(
        "--reports-dir", default="reports/e2e", help="报告输出根目录"
    )
    parser.add_argument(
        "--force", action="store_true", help="目标目录已存在时先删除再跑"
    )
    args = parser.parse_args()
    if args.llm == "mock" and (args.model or args.base_url):
        parser.error("--model/--base-url 仅在 --llm litellm 模式下有效")
    return args


def _run_one(args: argparse.Namespace, project: str, target: str) -> int:
    doc = PROJECTS_DIR / project / f"{target}.md"
    if not doc.is_file():
        print(f"[FAIL] {project}/{target}: 文档不存在: {doc}")
        return 1
    context = (PROJECTS_DIR / project / "spec.md") if target == "plan" else None

    run_dir = Path(args.reports_dir) / project / target
    if run_dir.exists():
        if args.force:
            shutil.rmtree(run_dir)
        else:
            print(
                f"[SKIP] {project}/{target}: {run_dir} 已存在"
                f"(加 --force 重跑)"
            )
            return 0

    if args.llm == "mock":
        answerer = MockScenarioAnswerer(args.scenario)
    else:
        answerer = LitellmAnswerer(
            model=args.model or "anthropic/claude-sonnet-4-20250514",
            base_url=args.base_url,
            max_calls=args.max_calls,
        )

    flow_args: list[str] = []
    if args.profile != "auto":
        flow_args += ["--profile", args.profile]
    flow_args += ["--threshold", str(args.threshold)]

    print(f"\n=== {project}/{target} ===")
    print(f"文档: {doc}")
    if context is not None:
        print(f"上下文: {context}")
    try:
        outcome = drive_review(
            doc, answerer,
            context_file=context, extra_args=flow_args, verbose=True,
        )
    except Exception as exc:  # noqa: BLE001 — manual runner: report, keep going
        print(f"[FAIL] {project}/{target}: {exc}")
        return 1

    payload = outcome.verdict
    v = payload["verdict"]
    route = payload["route"]
    conf = (
        v["calibrated_confidence"]
        if v["calibrated_confidence"] is not None
        else v["confidence"]
    )
    print(f"--- 结果 ({answerer.stats()}) ---")
    print(
        f"severity={v['severity']}  confidence={conf}  "
        f"escalate_to_human={v['escalate_to_human']}"
    )
    print(
        f"route: profile={route['profile']}  reviewers={route['reviewer_names']}"
    )
    print(f"      {route['reason']}")
    if v["findings"]:
        print(f"findings ({len(v['findings'])}):")
        for i, f in enumerate(v["findings"], 1):
            print(f"  {i}. [{f['severity']}] {f['description']}")
    else:
        print("findings: (无)")
    # copy evidence to the reports dir for archival
    run_dir.mkdir(parents=True, exist_ok=True)
    import shutil as _shutil
    for name in ("verdict.json", "report.md"):
        src = outcome.evidence_dir / name
        if src.is_file():
            _shutil.copy2(src, run_dir / name)
    print(f"报告: {run_dir / 'report.md'}")
    print(f"verdict: {run_dir / 'verdict.json'}")
    if v["escalate_to_human"]:
        print(f">>> 置信度 {conf} 低于阈值 {args.threshold},需要人工裁决(见报告)。")
    return 0


def main() -> int:
    args = _parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 — best-effort console encoding
            pass

    projects = args.project or list(DEFAULT_PROJECTS)
    targets = args.target or list(TARGETS)
    print(
        f"agent-judges e2e | llm={args.llm}"
        + (f" model={args.model}" if args.llm == "litellm" else "")
        + f" | projects={projects} targets={targets}",
        flush=True,
    )

    failures = 0
    for project in projects:
        for target in targets:
            failures += _run_one(args, project, target)

    print(f"\n完成: {'全部成功' if failures == 0 else f'{failures} 个目标失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断")
        sys.exit(130)
