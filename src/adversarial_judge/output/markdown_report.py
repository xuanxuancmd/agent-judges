"""Human-readable Markdown report rendering (FR-9).

The report is the **evidence** artifact (``.harness/evidence/judges/<run_id>/report.md``)
consumed by humans or downstream agents. It is NOT a log dump — internal
reasoning, debate transcripts, and raw agent outputs belong in
``.harness/logs/judges/<run_id>/`` (state.json, tasks/, results/).

Design rules (FR-9 revision):

1. **Findings sorted by confidence ascending** — low confidence = machine is
   uncertain = human should check first. High-confidence findings can be
   auto-fixed or batch-confirmed.
2. **No reasoning / debate transcripts** — the ``reasoning`` field and
   ``debate_rounds`` are internal process artifacts; they bloat the report
   and are already persisted in logs/results/. The report shows *what was
   found*, not *how it was deliberated*. Raw agent outputs (including
   reasoning) are preserved in ``logs/results/<id>.md`` for tool self-tuning.
3. **No merged individual-verdict dump** — the final synthesized verdict is
   the authoritative result. Individual verdicts are available in
   ``verdict.json`` (machine-readable) and ``results/`` (raw agent output).
   Re-dumping them as Markdown duplicates findings and inflates size.
4. **Empty suggestion → "需人工排查"** — when a reviewer couldn't prescribe
   a fix, the finding is shown with "排查方向: 需人工排查" instead of a
   suggestion, signalling that human investigation is required.
5. **Compact** — the report should fit on one screen for a typical review
   (5–20 findings). Route info is kept (auditable).
"""

from ..debate import DebateResult
from ..router import RouteDecision
from ..types import Finding, Verdict

__all__ = ["render_markdown"]


def _fmt_confidence(v: Verdict) -> str:
    if v.calibrated_confidence is not None:
        return (
            f"{v.calibrated_confidence:.2f}"
            f" (原始 {v.confidence:.2f}, 元审查校准后)"
        )
    return f"{v.confidence:.2f}"


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings by confidence ascending — lowest first.

    Low confidence = machine is uncertain = human should check first.
    Secondary sort by severity descending (critical before minor at same
    confidence level).
    """
    return sorted(
        findings,
        key=lambda f: (f.confidence, -f.severity.rank),
    )


def _findings_section(findings: list[Finding], level: int) -> list[str]:
    """Render findings sorted by confidence ascending (low → high).

    Each finding is a pointer to a location in the reviewed content:
    ``evidence`` cites the original text, ``confidence`` is the machine's
    certainty that the issue is real, ``suggestion`` is the fix.

    When ``suggestion`` is empty, the reviewer couldn't prescribe a fix —
    the finding is shown with "需人工排查" instead of "建议", signalling
    that human investigation is required for that finding.
    """
    if not findings:
        return []
    lines = [f"{'#' * level} 发现 ({len(findings)})", ""]
    lines.append(
        "> 按置信度升序排列（低置信度 = 机器不确定 = 人工优先检查）。"
    )
    lines.append("")
    for i, f in enumerate(_sorted_findings(findings), 1):
        lines.append(
            f"{i}. **[{f.severity.value}]** (置信度: {f.confidence:.2f})"
        )
        if f.description:
            lines.append(f"   - 问题: {f.description}")
        lines.append(f"   - 依据: {f.evidence}")
        if f.suggestion.strip():
            lines.append(f"   - 建议: {f.suggestion}")
        else:
            lines.append("   - 排查方向: 需人工排查（reviewer 未给出修复建议）")
        lines.append("")
    return lines


def _verdict_section(title: str, v: Verdict, level: int = 2) -> list[str]:
    """Render a verdict: summary + findings. No reasoning (that's in logs)."""
    lines = [f"{'#' * level} {title}", ""]
    lines.append(f"- **严重程度**: {v.severity.value}")
    lines.append(f"- **置信度**: {_fmt_confidence(v)}")
    lines.append(f"- **是否通过**: {'✅ 是' if v.satisfied else '❌ 否'}")
    if v.escalate_to_human:
        lines.append("- **⚠️ 需要人工介入** (`escalate_to_human: true`)")
    lines.append("")
    lines.extend(_findings_section(v.findings, level + 1))
    return lines


def render_markdown(
    result: DebateResult,
    confidence_threshold: float,
    meta_result: DebateResult | None = None,
    route: RouteDecision | None = None,
) -> str:
    """Render a human-readable Markdown report.

    The report contains **only actionable information**: the final verdict,
    its findings (sorted by confidence ascending), metrics, and terminal-state
    summary if applicable. Reasoning, debate transcripts, and individual-verdict
    dumps are excluded — they belong in ``.harness/logs/``.
    """
    v = result.final_verdict
    lines: list[str] = ["# 对抗审查报告", ""]

    # route info (auditable, FR-2)
    if route is not None:
        lines.append(f"> 路由档位: **{route.profile}** — {route.reason}")
        lines.append("")

    lines.extend(_verdict_section("最终裁决", v, level=2))
    if v.escalate_to_human:
        eff = v.calibrated_confidence if v.calibrated_confidence is not None else v.confidence
        lines.append(
            f"> ⚠️ 置信度 {eff:.2f} 低于阈值 {confidence_threshold},"
            f"建议人工复核低置信度发现。"
        )
        lines.append("")

    lines.append("## 指标")
    lines.append("")
    lines.append(f"- 共识度 (consensus): {result.consensus_score}")
    stable = (
        f"{result.stability_score} (degraded — 单 reviewer 快检形态)"
        if result.stability_degraded
        else f"{result.stability_score}"
    )
    lines.append(f"- 稳定性 (stability): {stable}")
    if result.conformity_warnings:
        lines.append(f"- ⚠️ 从众警示 (conformity): {len(result.conformity_warnings)} 个 reviewer 翻转立场但无新发现")
        for w in result.conformity_warnings:
            lines.append(f"  - {w}")
    lines.append("")

    # meta-review summary (compact: calibration result only, no reasoning)
    if meta_result is not None and v.calibrated_confidence is not None:
        lines.append("## 元审查校准")
        lines.append("")
        lines.append(
            f"- 校准后置信度: {v.calibrated_confidence:.2f}"
            f" (原始 {v.confidence:.2f})"
        )
        mv = meta_result.final_verdict
        lines.append(f"- 元审查严重程度: {mv.severity.value}")
        lines.append(
            f"- 元审查置信度: {mv.confidence:.2f}"
        )
        if v.confidence_adjustment is not None:
            lines.append(f"- 置信度调整: {v.confidence_adjustment:+.2f}")
        lines.append("")

    return "\n".join(lines)
