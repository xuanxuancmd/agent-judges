"""Human-readable Markdown report rendering (FR-9)."""

from ..debate import DebateResult
from ..router import RouteDecision
from ..types import Verdict

__all__ = ["render_markdown"]


def _fmt_confidence(v: Verdict) -> str:
    if v.calibrated_confidence is not None:
        return (
            f"{v.calibrated_confidence:.2f}"
            f" (原始 {v.confidence:.2f}, 元审查校准后)"
        )
    return f"{v.confidence:.2f}"


def _verdict_section(title: str, v: Verdict, level: int = 2) -> list[str]:
    lines = [f"{'#' * level} {title}", ""]
    lines.append(f"- **严重程度**: {v.severity.value}")
    lines.append(f"- **置信度**: {_fmt_confidence(v)}")
    lines.append(f"- **是否通过**: {'✅ 是' if v.satisfied else '❌ 否'}")
    if v.escalate_to_human:
        lines.append("- **⚠️ 需要人工介入** (`escalate_to_human: true`)")
    lines.append("")
    if v.findings:
        lines.append(f"{'#' * (level + 1)} 发现 ({len(v.findings)})")
        lines.append("")
        for i, f in enumerate(v.findings, 1):
            lines.append(
                f"{i}. **[{f.severity.value}]** {f.description} "
                f"(置信度: {f.confidence:.2f})"
            )
            lines.append(f"   - 依据: {f.evidence}")
            lines.append(f"   - 建议: {f.suggestion}")
        lines.append("")
    if v.reasoning:
        lines.append(f"{'#' * (level + 1)} 推理过程")
        lines.append("")
        lines.append(v.reasoning)
        lines.append("")
    return lines


def render_markdown(
    result: DebateResult,
    confidence_threshold: float,
    meta_result: DebateResult | None = None,
    route: RouteDecision | None = None,
) -> str:
    """Render a human-readable Markdown report."""
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
            f"> ⚠️ 置信度 {eff:.2f} 低于阈值 {confidence_threshold},建议人工复核。"
        )
        lines.append("")

    lines.append(f"## 指标")
    lines.append("")
    lines.append(f"- 共识度 (consensus): {result.consensus_score}")
    stable = (
        f"{result.stability_score} (degraded — 单 reviewer 快检形态)"
        if result.stability_degraded
        else f"{result.stability_score}"
    )
    lines.append(f"- 稳定性 (stability): {stable}")
    lines.append("")

    lines.extend(_verdict_section("各 reviewer 独立判断", _merge_verdicts(result.individual_verdicts), level=2))

    if result.debate_rounds:
        lines.append(f"## 辩论过程摘要")
        lines.append("")
        for i, round_args in enumerate(result.debate_rounds, 1):
            lines.append(f"### 第 {i} 轮")
            lines.append("")
            for arg in round_args:
                short = arg if len(arg) <= 500 else arg[:500] + " …(截断)"
                lines.append(f"> {short}")
                lines.append("")
        lines.append("")

    if meta_result is not None:
        lines.append("## 元审查结果")
        lines.append("")
        mv = meta_result.final_verdict
        if v.calibrated_confidence is not None:
            lines.append(
                f"校准后置信度: {v.calibrated_confidence:.2f}"
            )
            lines.append("")
        lines.extend(_verdict_section("元审查裁决", mv, level=3))

    return "\n".join(lines)


def _merge_verdicts(verdicts: list[Verdict]) -> Verdict:
    """Merge multiple reviewer verdicts into one display verdict."""
    if len(verdicts) == 1:
        return verdicts[0]
    all_findings = [f for v in verdicts for f in v.findings]
    return Verdict(
        severity=max(verdicts, key=lambda x: x.severity.rank).severity,
        confidence=round(sum(x.confidence for x in verdicts) / len(verdicts), 4),
        reasoning="\n---\n".join(
            f"[Reviewer {i + 1}] {x.reasoning}" for i, x in enumerate(verdicts)
        ),
        findings=all_findings,
        satisfied=all(x.satisfied for x in verdicts),
    )
