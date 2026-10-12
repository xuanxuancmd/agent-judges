"""Machine-readable JSON verdict rendering (FR-9).

The verdict.json is the **evidence** artifact (``.harness/evidence/judges/<run_id>/verdict.json``)
consumed by downstream agents and tools. It contains only **results**, not
process data — reasoning, debate transcripts, and raw agent outputs belong in
``.harness/logs/judges/<run_id>/`` (state.json, tasks/, results/).

Design rules (FR-9 revision):

1. **Final verdict is authoritative** — the synthesized verdict (with all
   findings, confidence, severity, escalation flag) is the single result.
2. **Findings sorted by confidence ascending** — lowest confidence first,
   matching report.md and fix-guide.md. Low confidence = machine uncertain
   = problem may be misidentified = fix/verify first.
3. **Individual verdicts are summary-only** — each reviewer's severity,
   confidence, and satisfied flag (for consensus/diversity auditing), but NOT
   their full reasoning or findings (those are in logs/results/).
4. **No debate rounds** — debate transcripts are internal process artifacts,
   already persisted in ``results/deb-r*.md``.
5. **No final_verdicts dump** — the blind final verdicts are intermediate
   synthesis inputs, not consumer-facing outputs.
6. **Meta-review is summary-only** — calibration result + meta verdict
   severity/confidence, but NOT the meta individual verdicts or reasoning.
"""

import json

from ..debate import DebateResult
from ..router import RouteDecision
from ..types import Finding, Verdict

__all__ = ["render_json"]


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings by confidence ascending — lowest first.

    Low confidence = machine uncertain = problem may be misidentified =
    fix/verify first. Secondary sort by severity descending (critical before
    minor at the same confidence level).
    """
    return sorted(
        findings,
        key=lambda f: (f.confidence, -f.severity.rank),
    )


def _verdict_dict(v: Verdict) -> dict:
    """Full verdict dict — used only for the final (authoritative) verdict.

    Findings are re-sorted by confidence ascending (lowest first) so all
    three artifacts (fix-guide.md, report.md, verdict.json) present findings
    in the same order: low confidence = fix first.
    """
    d = v.model_dump(mode="json")
    # re-sort the serialized findings list to match the ascending-confidence
    # order used by the markdown renderers (model_dump preserves insertion
    # order, which is the engine's synthesis order — not consumer-facing)
    if d.get("findings"):
        sorted_finding_dicts = [
            f.model_dump(mode="json") for f in _sorted_findings(v.findings)
        ]
        d["findings"] = sorted_finding_dicts
    return d


def _verdict_summary(v: Verdict) -> dict:
    """Lean summary for individual/meta verdicts — no reasoning, no findings.

    Consumers need to know *who said what severity with what confidence*,
    not the full reasoning chain (that's in logs).
    """
    return {
        "severity": v.severity.value,
        "confidence": v.confidence,
        "satisfied": v.satisfied,
    }


def render_json(
    result: DebateResult,
    confidence_threshold: float,
    meta_result: DebateResult | None = None,
    route: RouteDecision | None = None,
) -> str:
    """Render the machine-readable JSON verdict (FR-9).

    Contains only **results**: the final synthesized verdict (full, with all
    findings), individual verdict summaries (severity/confidence/satisfied only),
    metrics, route, and meta-review calibration summary. Process data
    (reasoning, debate transcripts, blind finals) is excluded — it lives in logs.
    """
    payload: dict = {
        "verdict": _verdict_dict(result.final_verdict),
        "individual_verdicts": [
            _verdict_summary(v) for v in result.individual_verdicts
        ],
        "consensus_score": result.consensus_score,
        "stability_score": result.stability_score,
        "stability_degraded": result.stability_degraded,
        "conformity_warnings": result.conformity_warnings,
        "threshold": confidence_threshold,
    }
    if route is not None:
        payload["route"] = route.model_dump(mode="json")
    if meta_result is not None:
        mv = meta_result.final_verdict
        payload["meta_review"] = {
            "verdict": _verdict_summary(mv),
            "consensus_score": meta_result.consensus_score,
            "stability_score": meta_result.stability_score,
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)
