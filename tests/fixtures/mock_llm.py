"""Mock LLM fixtures — unit tests never hit real APIs (G-6).

``MockLLM`` routes canned responses by substring matching against the
system/user prompt (e.g. a reviewer persona keyword, or a phase marker like
"审查框架" / "辩论阶段" / "辩论已结束" / "审查流程路由器"). Response values
may be a ``str`` (constant) or a ``list[str]`` (sequential, cycling).

Extra knobs:
- ``raise_on``: substring → exception to raise (tests per-reviewer failure
  degradation)
- ``delay``: seconds to sleep per call (tests parallel timing)
- ``cost_per_call``: synthetic cost added per call (tests budget control)
"""

from __future__ import annotations

import time

from pydantic import ValidationError

from agent_judges.llm.broker import LLMBroker
from agent_judges.llm.cost import Cost
from agent_judges.llm.provider import LLM
from agent_judges.llm.structured_output import (
    StructuredOutputParseError,
    _parse_json_response,
)

__all__ = ["MockLLM", "MockLLMBroker"]

_CALL_TOKENS = 10  # synthetic tokens accounted per emulated call


class MockLLM(LLM):
    """Returns canned responses; no litellm calls, no network.

    ``complete_json`` emulates the strict structured chain: the matched
    canned response is strict-parsed into ``schema``; on failure a
    ``StructuredOutputParseError`` carrying the response is raised so the
    pipeline's AaaJ tag fallback runs on the same text (no extra call).
    """

    def __init__(
        self,
        responses: dict[str, str | list[str]] | None = None,
        delay: float = 0.0,
        cost_per_call: float = 0.0,
        raise_on: dict[str, Exception] | None = None,
    ):
        # deliberately bypass LLM.__init__ (no litellm initialization);
        # set the attributes the pipeline actually touches
        self.model_name = "mock"
        self.max_input_tokens = 4096
        self.cost = Cost()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self._responses: list[tuple[str, list[str]]] = [
            (key, [v] if isinstance(v, str) else list(v))
            for key, v in (responses or {}).items()
        ]
        self._delay = delay
        self._cost_per_call = cost_per_call
        self._raise_on = raise_on or {}
        self._seq_index = 0

    def _account_call(self) -> None:
        self.call_count += 1
        self.total_input_tokens += _CALL_TOKENS
        self.total_output_tokens += _CALL_TOKENS
        if self._cost_per_call:
            self.cost.add_cost(self._cost_per_call)

    def _guard(self, system_prompt: str, user_prompt: str) -> None:
        if self._delay:
            time.sleep(self._delay)
        for key, exc in self._raise_on.items():
            if key in system_prompt or key in user_prompt:
                raise exc

    def complete(self, system_prompt: str, user_prompt: str, temperature=None) -> str:
        self._guard(system_prompt, user_prompt)
        self._account_call()
        return self._match(system_prompt, user_prompt)

    def complete_json(self, system_prompt, user_prompt, schema, temperature=None):
        self._guard(system_prompt, user_prompt)
        self._account_call()
        response = self._match(system_prompt, user_prompt)
        try:
            return _parse_json_response(response, schema)
        except (ValueError, ValidationError) as exc:
            raise StructuredOutputParseError(
                f"mock: structured parse failed: {exc}", response=response
            ) from exc

    def _match(self, system_prompt: str, user_prompt: str) -> str:
        for key, responses in self._responses:
            if key in system_prompt or key in user_prompt:
                if len(responses) == 1:
                    return responses[0]
                resp = responses[self._seq_index % len(responses)]
                self._seq_index += 1
                return resp
        if self._responses:
            first = self._responses[0][1]
            if len(first) == 1:
                return first[0]
            resp = first[self._seq_index % len(first)]
            self._seq_index += 1
            return resp
        return ""


class MockLLMBroker(LLMBroker):
    """Broker injecting a single shared MockLLM (per-reviewer routing is
    handled inside MockLLM's response matching)."""

    def __init__(self, mock_llm: MockLLM, max_budget_usd: float | None = None):
        super().__init__(default_model="mock", max_budget_usd=max_budget_usd)
        self._mock_llm = mock_llm

    def get_llm(self, model: str | None = None) -> LLM:
        return self._mock_llm

    def get_total_cost(self) -> float:
        return self._mock_llm.cost.accumulated_cost

    def get_total_tokens(self) -> int:
        return self._mock_llm.total_input_tokens + self._mock_llm.total_output_tokens
