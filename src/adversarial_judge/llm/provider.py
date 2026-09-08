"""Unified LLM interface over litellm (multi-provider: Claude / GPT / any).

Rewritten from AaaJ's ``agent_as_a_judge/llm/provider.py``:
- ``model`` is now a required constructor arg (dependency injection, no env read)
- preserves AaaJ's Cost integration, tenacity retry, model_info auto-detection,
  ``is_local`` and ``get_token_count``
- adds ``complete()`` / ``complete_json()`` convenience APIs
- tracks cumulative input/output token usage for budget reporting
"""

import logging
from functools import partial
from typing import Type, TypeVar

from litellm import completion as litellm_completion
from litellm import completion_cost as litellm_completion_cost
from litellm.exceptions import (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
)
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .cost import Cost

logger = logging.getLogger(__name__)

__all__ = ["LLM"]

T = TypeVar("T", bound=BaseModel)


class LLM:
    """Litellm-backed LLM client with cost tracking and retry.

    ``model`` is required — instances are created via :class:`LLMBroker`
    (per-reviewer model injection) rather than read from the environment.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        num_retries: int = 3,
        retry_min_wait: int = 1,
        retry_max_wait: int = 10,
        llm_timeout: int = 30,
        llm_temperature: float = 0.0,  # review scenario: deterministic by default
        llm_top_p: float = 0.9,
        custom_llm_provider: str | None = None,
        max_input_tokens: int = 4096,
        max_output_tokens: int = 4096,
    ):
        self.cost = Cost()
        self.model_name = model
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.llm_timeout = llm_timeout
        self.llm_temperature = llm_temperature
        self.llm_top_p = llm_top_p
        self.num_retries = num_retries
        self.retry_min_wait = retry_min_wait
        self.retry_max_wait = retry_max_wait
        self.custom_llm_provider = custom_llm_provider

        # cumulative token usage (NFR-3: cost/time/token accounting)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

        # AaaJ-preserved: model_info auto-detection (informational)
        self.model_info: dict | None = None
        try:
            import litellm

            info = litellm.get_model_info(self.model_name)
            self.model_info = dict(info) if isinstance(info, dict) else None
        except Exception:
            logger.debug("Could not get model info for %s", self.model_name)

        self._initialize_completion_function()

    def _initialize_completion_function(self) -> None:
        completion_func = partial(
            litellm_completion,
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            custom_llm_provider=self.custom_llm_provider,
            max_tokens=self.max_output_tokens,
            timeout=self.llm_timeout,
            temperature=self.llm_temperature,
            top_p=self.llm_top_p,
        )

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.num_retries),
            wait=wait_random_exponential(
                min=self.retry_min_wait, max=self.retry_max_wait
            ),
            retry=retry_if_exception_type(
                (RateLimitError, APIConnectionError, ServiceUnavailableError)
            ),
        )
        def wrapper(*args, **kwargs):
            return completion_func(*args, **kwargs)

        self._completion = wrapper

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> str:
        """Synchronous text completion with system/user messages."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict = {"messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self._completion(**kwargs)
        self._post_completion(resp)
        return resp["choices"][0]["message"]["content"]

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        temperature: float | None = None,
    ) -> T:
        """Forced structured output (B-5): tool-use first, then a
        multi-level degradation chain. See ``structured_output.py``."""
        from .structured_output import force_structured_output

        return force_structured_output(
            self, system_prompt, user_prompt, schema, temperature=temperature
        )

    def _post_completion(self, response) -> None:
        """Best-effort cost + token accounting (AaaJ-preserved pattern)."""
        try:
            usage = response.get("usage") or {}
            self.total_input_tokens += usage.get("prompt_tokens", 0) or 0
            self.total_output_tokens += usage.get("completion_tokens", 0) or 0
        except Exception:
            logger.debug("Could not read token usage from response", exc_info=True)
        try:
            cost = litellm_completion_cost(completion_response=response)
            if self.cost:
                self.cost.add_cost(cost)
        except Exception:
            logger.debug(
                "Cost calculation not supported for model %s", self.model_name
            )

    def get_token_count(self, messages: list) -> int:
        import litellm

        return litellm.token_counter(model=self.model_name, messages=messages)

    def is_local(self) -> bool:
        if self.base_url:
            return any(
                s in self.base_url for s in ["localhost", "127.0.0.1", "0.0.0.0"]
            )
        if self.model_name and self.model_name.startswith("ollama"):
            return True
        return False

    def __str__(self) -> str:
        return f"LLM(model={self.model_name}, base_url={self.base_url})"

    def __repr__(self) -> str:
        return str(self)
