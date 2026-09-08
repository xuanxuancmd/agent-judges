"""Machine-readable JSON verdict rendering (FR-9)."""

import json

from ..debate import DebateResult
from ..llm.broker import LLMBroker
from ..router import RouteDecision
from ..types import Verdict

__all__ = ["render_json"]


def _verdict_dict(v: Verdict) -> dict:
    return v.model_dump(mode="json")


def render_json(
    result: DebateResult,
    confidence_threshold: float,
    meta_result: DebateResult | None = None,
    broker: LLMBroker | None = None,
    route: RouteDecision | None = None,
) -> str:
    """Render the machine-readable JSON verdict (FR-9, M-7: stdout/file, never stderr)."""
    payload: dict = {
        "verdict": _verdict_dict(result.final_verdict),
        "individual_verdicts": [_verdict_dict(v) for v in result.individual_verdicts],
        "final_verdicts": [_verdict_dict(v) for v in result.final_verdicts],
        "debate_rounds": result.debate_rounds,
        "consensus_score": result.consensus_score,
        "stability_score": result.stability_score,
        "stability_degraded": result.stability_degraded,
        "threshold": confidence_threshold,
    }
    if route is not None:
        payload["route"] = route.model_dump(mode="json")
    if meta_result is not None:
        payload["meta_review"] = {
            "verdict": _verdict_dict(meta_result.final_verdict),
            "consensus_score": meta_result.consensus_score,
            "stability_score": meta_result.stability_score,
            "individual_verdicts": [
                _verdict_dict(v) for v in meta_result.individual_verdicts
            ],
        }
    if broker is not None:
        payload["cost"] = {
            "total_tokens": broker.get_total_tokens(),
            "total_cost_usd": round(broker.get_total_cost(), 6),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)
