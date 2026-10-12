"""Verdict parsing (multi-level degradation) and the AaaJ majority-vote algorithm.

``parse_verdict`` degrades gracefully (B-5):
1. ```json ... ``` fenced code block
2. bare JSON object (first ``{...}``)
3. ``<SATISFIED>``/``<UNSATISFIED>`` tag parsing (AaaJ's original scheme,
   confidence capped at 0.5 so degraded parses escalate to humans)

``run_majority_vote`` preserves AaaJ ``DevAsk.check()``'s full voting chain
(G-5): N same-model calls → satisfied_ratio → majority judge →
``confidence = max(satisfied_ratio, 1 - satisfied_ratio)``.
"""

import json
import logging
import re

from pydantic import ValidationError

from .llm.structured_output import StructuredOutputParseError
from .reviewer import ReviewerConfig
from .types import Finding, Severity, Verdict

logger = logging.getLogger(__name__)

__all__ = ["parse_verdict", "run_majority_vote", "llm_verdict"]


def llm_verdict(
    llm,
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
) -> Verdict:
    """One LLM call → Verdict via the full degradation chain (B-5).

    1. ``complete_json``: tool-use → response_format → prompt-injected
       schema + JSON regex (strict schema validation)
    2. When the structured chain cannot parse, the AaaJ ``<SATISFIED>`` tag
       fallback runs on the **same raw response** (carried by
       ``StructuredOutputParseError.response`` — no second LLM call).
    """
    try:
        return llm.complete_json(system_prompt, user_prompt, Verdict, temperature)
    except StructuredOutputParseError as exc:
        return parse_verdict(exc.response)


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


def run_majority_vote(
    llm, reviewer: ReviewerConfig, user_prompt: str, votes: int
) -> Verdict:
    """Same-model N-call voting aggregation (G-5, AaaJ ``DevAsk.check()``).

    AaaJ-preserved formula: ``confidence = max(satisfied_ratio, 1 - satisfied_ratio)``
    with majority satisfied at ``satisfied_ratio >= 0.5``.
    """
    verdicts = [
        llm_verdict(
            llm, reviewer.system_prompt, user_prompt, reviewer.temperature
        )
        for _ in range(votes)
    ]

    satisfied_count = sum(1 for v in verdicts if v.satisfied)
    total = len(verdicts)
    satisfied_ratio = (satisfied_count / total) if total else 0.0
    majority_satisfied = satisfied_ratio >= 0.5

    # (AaaJ original formula)
    confidence = max(satisfied_ratio, 1.0 - satisfied_ratio)

    all_findings = [f for v in verdicts for f in v.findings]
    max_severity = max(verdicts, key=lambda v: v.severity.rank).severity

    return Verdict(
        severity=max_severity,
        confidence=round(confidence, 4),
        reasoning="\n---\n".join(v.reasoning for v in verdicts),
        findings=all_findings,
        satisfied=majority_satisfied,
    )
