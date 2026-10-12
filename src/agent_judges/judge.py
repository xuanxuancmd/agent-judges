"""Verdict parsing (multi-level degradation).

``parse_verdict`` degrades gracefully (B-5):
1. ```json ... ``` fenced code block
2. bare JSON object (first ``{...}``)
3. ``<SATISFIED>``/``<UNSATISFIED>`` tag parsing (AaaJ's original scheme,
   confidence capped at 0.5 so degraded parses escalate to humans)

The agent-driven path passes raw reviewer-agent output through ``parse_verdict``
— no LLM calls, no structured-output chain. The former ``llm_verdict`` and
``run_majority_vote`` (in-process litellm direct mode) have been removed.
"""

import json
import logging
import re

from pydantic import ValidationError

from .types import Finding, Severity, Verdict

logger = logging.getLogger(__name__)

__all__ = ["parse_verdict"]


def parse_verdict(response: str) -> Verdict:
    """Parse a Verdict from an LLM response with 3-level degradation."""
    # Level 1: JSON code block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    # Level 2: bare JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    # Level 3: tag degradation (AaaJ's original scheme)
    if "<SATISFIED>" in response:
        return Verdict(
            severity=Severity.PASS,
            confidence=0.5,  # degraded parse: capped so it escalates to humans
            reasoning=response,
            findings=[],
            satisfied=True,
        )
    elif "<UNSATISFIED>" in response:
        return Verdict(
            severity=Severity.MAJOR,  # default to major
            confidence=0.5,
            reasoning=response,
            findings=[],
            satisfied=False,
        )

    raise ValueError(
        f"Could not parse verdict from response: {response[:200]}..."
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _parse_severity(value, default: Severity = Severity.MINOR) -> Severity:
    """Case-insensitive severity parsing; unknown values degrade to MINOR."""
    try:
        return Severity(str(value).lower())
    except ValueError:
        return default


def _build_verdict(data: dict) -> Verdict:
    """Build a Verdict from a parsed dict, adapting LLM field variations."""
    findings_data = data.get("findings", [])
    findings = []
    for f in findings_data:
        sev = _parse_severity(f.get("severity", "minor"))
        # (M-6) skip pass-level findings; a finding is an issue by definition
        if sev == Severity.PASS:
            continue
        findings.append(
            Finding(
                description=f.get("description", ""),
                severity=sev,
                confidence=_clamp01(float(f.get("confidence", 0.5))),
                evidence=f.get("evidence", ""),
                suggestion=f.get("suggestion", ""),
            )
        )

    sev = _parse_severity(data.get("severity", "minor"))

    # extract confidence_adjustment (meta-reviewer's calibration suggestion)
    confidence_adjustment = data.get("confidence_adjustment")
    if confidence_adjustment is not None:
        try:
            confidence_adjustment = float(confidence_adjustment)
        except (TypeError, ValueError):
            confidence_adjustment = None

    return Verdict(
        severity=sev,
        confidence=_clamp01(float(data.get("confidence", 0.5))),
        reasoning=data.get("reasoning", ""),
        findings=findings,
        satisfied=bool(data.get("satisfied", sev == Severity.PASS)),
        confidence_adjustment=confidence_adjustment,
    )
