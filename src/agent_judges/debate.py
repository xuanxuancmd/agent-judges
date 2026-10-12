"""DebateResult: the complete outcome of one debate run.

The in-process DebateOrchestrator (litellm direct mode) has been removed —
the agent-driven path uses :mod:`agent_judges.engine`'s prepare/resume state
machine instead. This module retains only the ``DebateResult`` dataclass,
which ``engine.build_result`` and the output renderers depend on.
"""

from dataclasses import dataclass, field

from .types import Verdict

__all__ = ["DebateResult"]


@dataclass
class DebateResult:
    """Complete outcome of one debate run."""

    individual_verdicts: list[Verdict]  # each reviewer's Phase-1 verdict
    debate_rounds: list[list[str]]  # arguments per round
    final_verdicts: list[Verdict]  # each reviewer's Phase-3 blind final
    final_verdict: Verdict  # synthesized verdict (weighted aggregation)
    consensus_score: float  # reviewer agreement on satisfied (M-5)
    stability_score: float  # position-flip resistance across the debate
    stability_degraded: bool = field(
        default=False
    )  # True = fast-check mode (Phase 3 skipped), stability not measurable
    conformity_warnings: list[str] = field(
        default_factory=list
    )  # reviewers who flipped without new findings (MachineSoM, ACL 2024)
