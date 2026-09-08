"""DebateOrchestrator: the 4-phase adversarial debate pipeline.

# allow: SIZE_OK — one cohesive orchestrator state machine: all four phases
# share registry/broker/rounds state; splitting the class would scatter that
# state and hurt cohesion. (Measured 253 non-blank lines, ~50 of them
# docstrings.)

Phases (borrowed from agent-review-panel's debate + blind-final model):
1. Independent review — N reviewers, **parallel** (ThreadPoolExecutor, M-8)
2. Adversarial debate — 1-3 rounds, only when >= 2 reviewers (B-3)
3. Blind final — each reviewer's final verdict, **parallel**;
   skipped entirely in the single-reviewer fast-check mode (the re-judger
   equals the original judge, so self-review adds no value — L0 rule)
4. Verdict synthesis — weighted aggregation with ``Severity.rank``
   max-severity (B-1), real consensus/stability computation (M-5)

Budget checks (``broker.check_budget``) run between phases and before each
debate round; per-reviewer failures degrade to a low-confidence Verdict
instead of crashing the batch.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .consensus import (
    compute_consensus,
    compute_stability,
    failed_verdict,
    synthesize_verdict,
)
from .judge import llm_verdict, run_majority_vote
from .llm.broker import LLMBroker
from .prompts.debate import (
    build_blind_final_system_prompt,
    build_blind_final_user_prompt,
    build_debate_system_prompt,
    build_debate_user_prompt,
)
from .prompts.judge_system import build_system_prompt
from .prompts.judge_user import build_judge_prompt
from .reviewer import ReviewerConfig, ReviewerRegistry
from .types import Verdict
from .utils.truncate import truncate_string

logger = logging.getLogger(__name__)

__all__ = ["DebateResult", "DebateOrchestrator"]

# tokens reserved for persona + checklist + output requirements (+ injected
# skill bodies) when fitting user-supplied content into a model's input budget
_PROMPT_RESERVE_TOKENS = 1536


def fit_for_model(llm, text: str, share: int = 1) -> str:
    """Token-fit guard: truncate unbounded text to the reviewer model's input
    budget (middle-drop). ``share`` divides the budget (context and debate
    positions get a half-share)."""
    budget = max(512, (llm.max_input_tokens - _PROMPT_RESERVE_TOKENS) // share)
    return truncate_string(text, model=llm.model_name, max_tokens=budget)


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


class DebateOrchestrator:
    """Orchestrates independent review → debate → blind final → synthesis."""

    def __init__(
        self,
        registry: ReviewerRegistry,
        broker: LLMBroker,
        debate_rounds: int = 2,
        max_workers: int | None = None,
    ):
        self.registry = registry
        self.broker = broker
        self.debate_rounds = debate_rounds
        self.max_workers = max_workers or 4

    def run(
        self,
        content: str,
        reviewer_names: list[str],
        context: str | None = None,
    ) -> DebateResult:
        reviewers = [self.registry.get(name) for name in reviewer_names]
        if len(reviewers) < 1:
            raise ValueError("At least 1 reviewer required")

        # Phase 1: independent review (parallel, M-8)
        individual_verdicts = self._parallel_independent_review(
            reviewers, content, context
        )

        # Budget check after Phase 1: over budget → skip debate, synthesize now
        if not self.broker.check_budget():
            logger.warning(
                "预算超限 ($%.4f),跳过辩论阶段", self.broker.get_total_cost()
            )
            final_verdict = synthesize_verdict(individual_verdicts, reviewers, content)
            return DebateResult(
                individual_verdicts=individual_verdicts,
                debate_rounds=[],
                final_verdicts=individual_verdicts,
                final_verdict=final_verdict,
                consensus_score=compute_consensus(individual_verdicts),
                stability_score=1.0,
            )

        # Phase 2: adversarial debate — only when >= 2 reviewers (B-3)
        debate_log: list[list[str]] = []
        if len(reviewers) >= 2 and self.debate_rounds > 0:
            current_positions = [v.reasoning for v in individual_verdicts]
            for _round_idx in range(self.debate_rounds):
                if not self.broker.check_budget():
                    logger.warning(
                        "预算超限 ($%.4f),终止辩论", self.broker.get_total_cost()
                    )
                    break
                round_args = self._debate_round(
                    reviewers, content, current_positions, context
                )
                debate_log.append(round_args)
                current_positions = round_args
        else:
            current_positions = [v.reasoning for v in individual_verdicts]

        # Phase 3: blind final (parallel) — skipped in single-reviewer
        # fast-check mode (L0 rule: re-judger == original judge)
        if len(reviewers) >= 2:
            final_verdicts = self._parallel_blind_final(
                reviewers, content, current_positions, context
            )
            stability = compute_stability(individual_verdicts, final_verdicts)
            stability_degraded = False
        else:
            logger.info(
                "单 reviewer 快检形态: 跳过盲评终判,stability 标记 degraded"
            )
            final_verdicts = individual_verdicts
            stability = 1.0
            stability_degraded = True

        # Phase 4: verdict synthesis
        final_verdict = synthesize_verdict(final_verdicts, reviewers, content)
        consensus = compute_consensus(final_verdicts)

        return DebateResult(
            individual_verdicts=individual_verdicts,
            debate_rounds=debate_log,
            final_verdicts=final_verdicts,
            final_verdict=final_verdict,
            consensus_score=consensus,
            stability_score=stability,
            stability_degraded=stability_degraded,
        )

    # ------------------------------------------------------------------
    # Phase 1: independent review
    # ------------------------------------------------------------------

    def _parallel_independent_review(
        self, reviewers: list[ReviewerConfig], content: str, context: str | None
    ) -> list[Verdict]:
        """Phase 1: parallel independent review; per-reviewer failures
        degrade to a low-confidence Verdict."""

        def work(reviewer: ReviewerConfig) -> Verdict:
            try:
                return self._independent_review(reviewer, content, context)
            except Exception as e:
                logger.warning(
                    "Reviewer '%s' failed in independent review: %s",
                    reviewer.name,
                    e,
                )
                return failed_verdict(reviewer.name, "independent review", e)

        results: list[Verdict | None] = [None] * len(reviewers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(work, r): i for i, r in enumerate(reviewers)}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                results[idx] = fut.result()
        return [r for r in results if r is not None]

    def _independent_review(
        self, reviewer: ReviewerConfig, content: str, context: str | None
    ) -> Verdict:
        """Independent review; supports majority_vote (G-5) internally."""
        llm = self.broker.get_llm(reviewer.model)
        safe_content = fit_for_model(llm, content)
        safe_context = fit_for_model(llm, context, share=2) if context else None
        user_prompt = build_judge_prompt(
            safe_content, reviewer.checklist, safe_context
        )
        system_prompt = build_system_prompt(reviewer.system_prompt)

        if reviewer.majority_vote > 1:
            return run_majority_vote(llm, reviewer, user_prompt, reviewer.majority_vote)
        return llm_verdict(llm, system_prompt, user_prompt, reviewer.temperature)

    # ------------------------------------------------------------------
    # Phase 2: adversarial debate
    # ------------------------------------------------------------------

    def _debate_round(
        self,
        reviewers: list[ReviewerConfig],
        content: str,
        current_positions: list[str],
        context: str | None,
    ) -> list[str]:
        """One debate round: each reviewer sees the others' positions and
        rebuts. A failed reviewer keeps its original position."""
        round_arguments: list[str | None] = [None] * len(reviewers)

        def work(i: int) -> str:
            reviewer = reviewers[i]
            others = "\n".join(
                f"[{reviewers[j].name}]: {current_positions[j]}"
                for j in range(len(reviewers))
                if j != i
            )
            try:
                return self._debate_single(reviewer, content, others, context)
            except Exception as e:
                logger.warning(
                    "Reviewer '%s' failed in debate round: %s", reviewer.name, e
                )
                return current_positions[i]  # keep original position

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(work, i): i for i in range(len(reviewers))}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                round_arguments[idx] = fut.result()
        return [a for a in round_arguments if a is not None]

    def _debate_single(
        self,
        reviewer: ReviewerConfig,
        content: str,
        others_args: str,
        context: str | None,
    ) -> str:
        llm = self.broker.get_llm(reviewer.model)
        system = build_debate_system_prompt(reviewer.system_prompt)
        user = build_debate_user_prompt(
            fit_for_model(llm, content), fit_for_model(llm, others_args, share=2)
        )
        return llm.complete(system, user, temperature=reviewer.temperature)

    # ------------------------------------------------------------------
    # Phase 3: blind final
    # ------------------------------------------------------------------

    def _parallel_blind_final(
        self,
        reviewers: list[ReviewerConfig],
        content: str,
        current_positions: list[str],
        context: str | None,
    ) -> list[Verdict]:
        """Phase 3: parallel blind final; per-reviewer failures degrade."""

        def work(idx: int) -> Verdict:
            try:
                return self._blind_final(
                    reviewers[idx], content, current_positions[idx], context
                )
            except Exception as e:
                logger.warning(
                    "Reviewer '%s' failed in blind final: %s",
                    reviewers[idx].name,
                    e,
                )
                return failed_verdict(reviewers[idx].name, "blind final", e)

        results: list[Verdict | None] = [None] * len(reviewers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(work, i): i for i in range(len(reviewers))}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                results[idx] = fut.result()
        return [r for r in results if r is not None]

    def _blind_final(
        self,
        reviewer: ReviewerConfig,
        content: str,
        debated_position: str,
        context: str | None,
    ) -> Verdict:
        llm = self.broker.get_llm(reviewer.model)
        system = build_blind_final_system_prompt(reviewer.system_prompt)
        user = build_blind_final_user_prompt(
            fit_for_model(llm, content), fit_for_model(llm, debated_position, share=2)
        )
        return llm_verdict(llm, system, user, reviewer.temperature)

    # ------------------------------------------------------------------
    # Phase 4 (synthesis) lives in consensus.synthesize_verdict
    # ------------------------------------------------------------------
