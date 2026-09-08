"""LLMBroker: multi-model management with instance caching and budget control.

Per-reviewer model injection (M-4): a reviewer may explicitly set ``model`` in
its YAML; when it does not, the broker's ``default_model`` is used.

Credential passthrough: when no explicit ``default_api_key`` /
``default_base_url`` is given, per-model credentials are resolved from the
host session environment (``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` /
``OPENAI_API_KEY`` / ``ANTHROPIC_BASE_URL``) — see ``credentials.py``. This is
how ``aj`` reuses the LLM access of the Claude Code / OpenCode session that
invoked it, without its own API keys.
"""

import logging

from .credentials import env_api_key, env_base_url
from .provider import LLM

logger = logging.getLogger(__name__)

__all__ = ["LLMBroker"]


class LLMBroker:
    """Multi-model manager: per-reviewer models, instance caching, cumulative
    cost/token tracking and budget checks.

    Cost is recorded automatically by ``LLM._post_completion`` into each
    instance's ``Cost``; the broker only aggregates cached instances.
    """

    def __init__(
        self,
        default_model: str,
        default_api_key: str | None = None,
        default_base_url: str | None = None,
        max_budget_usd: float | None = None,
    ):
        self.default_model = default_model
        self.default_api_key = default_api_key
        self.default_base_url = default_base_url
        self.max_budget_usd = max_budget_usd
        self._cache: dict[str, LLM] = {}

    def get_llm(self, model: str | None = None) -> LLM:
        """Return a (cached) LLM instance for ``model``.

        ``model=None`` falls back to ``default_model`` (M-4). Credentials:
        explicit broker args win, then host-session env vars per provider,
        then litellm's internal env fallback (api_key=None).
        """
        resolved = model or self.default_model
        if resolved not in self._cache:
            self._cache[resolved] = LLM(
                model=resolved,
                api_key=self.default_api_key or env_api_key(resolved),
                base_url=self.default_base_url or env_base_url(resolved),
            )
        return self._cache[resolved]

    def get_total_cost(self) -> float:
        """Sum of ``Cost.accumulated_cost`` across cached instances."""
        return sum(llm.cost.accumulated_cost for llm in self._cache.values())

    def get_total_tokens(self) -> int:
        """Sum of input+output tokens across cached instances."""
        return sum(
            llm.total_input_tokens + llm.total_output_tokens
            for llm in self._cache.values()
        )

    def check_budget(self) -> bool:
        """True = budget not exceeded (or no budget set); False = exceeded."""
        if self.max_budget_usd is None:
            return True
        return self.get_total_cost() < self.max_budget_usd
