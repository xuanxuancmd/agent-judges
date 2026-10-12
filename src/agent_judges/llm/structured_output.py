"""Forced structured output: litellm tool-use first + multi-level degradation.

Degradation chain (B-5):
1. litellm tool-use (Anthropic natively supports tool_use; manually-built
   tool definition — no reliance on unstable litellm internal APIs)
2. ``response_format={"type": "json_object"}`` (OpenAI-compatible models)
3. JSON schema injected into the prompt + regex parsing
   (```json fenced block → bare ``{...}`` object)

The final ``<SATISFIED>/<UNSATISFIED>`` label fallback lives in
``agent_judges.judge.parse_verdict`` (AaaJ-preserved) and is used by the
debate pipeline instead of this module.
"""

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

__all__ = ["StructuredOutputParseError", "force_structured_output"]


class StructuredOutputParseError(ValueError):
    """Every structured-output level failed (typed error).

    ``response`` carries the raw Level-3 response so callers can apply a
    domain-specific fallback (e.g. AaaJ ``<SATISFIED>`` tag parsing in
    ``judge.llm_verdict``) **without a second LLM call**.
    """

    def __init__(self, message: str, response: str = ""):
        super().__init__(message)
        self.response = response


def force_structured_output(
    llm,
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    temperature: float | None = None,
) -> T:
    """Obtain a schema-conformant object from the LLM, degrading gracefully.

    Raises :class:`StructuredOutputParseError` only when every level of the
    chain fails; the exception carries the raw Level-3 response.
    """
    # Level 1: tool-use (works on Anthropic and most modern providers)
    try:
        return _try_tool_use(llm, system_prompt, user_prompt, schema)
    except Exception as exc:
        logger.debug("tool-use structured output failed: %s", exc)

    # Level 2: response_format (OpenAI-compatible)
    try:
        return _try_response_format(llm, system_prompt, user_prompt, schema)
    except Exception as exc:
        logger.debug("response_format structured output failed: %s", exc)

    # Level 3: prompt-injected schema + regex parsing
    response = _prompt_based_json(llm, system_prompt, user_prompt, schema, temperature)
    return _parse_json_response(response, schema)


def _try_tool_use(llm, system_prompt: str, user_prompt: str, schema: Type[T]) -> T:
    """litellm tool-use: convert the Pydantic schema to a tool definition.

    The tool definition is built manually for compatibility across litellm
    versions (no internal helper APIs).
    """
    tool_schema = schema.model_json_schema()
    tool = {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": "Submit the review verdict as structured data",
            "parameters": tool_schema,
        },
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm._completion(
        messages=messages,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "submit_verdict"}},
        temperature=0.0,
    )
    llm._post_completion(resp)
    tool_calls = resp["choices"][0]["message"].get("tool_calls") or []
    if not tool_calls:
        raise ValueError("No tool call in response")
    args = json.loads(tool_calls[0]["function"]["arguments"])
    return schema(**args)


def _try_response_format(llm, system_prompt: str, user_prompt: str, schema: Type[T]) -> T:
    """OpenAI ``response_format={"type": "json_object"}`` (OpenAI-only)."""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    enhanced_system = (
        system_prompt
        + f"\n\n你必须返回符合以下 JSON schema 的 JSON 对象:\n{schema_json}\n"
        f"只返回 JSON,不要其他内容。"
    )
    messages = [
        {"role": "system", "content": enhanced_system},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm._completion(
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = resp["choices"][0]["message"]["content"]
    llm._post_completion(resp)
    data = json.loads(content)
    return schema(**data)


def _prompt_based_json(
    llm,
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    temperature: float | None = None,
) -> str:
    """Inject the JSON schema into the prompt and get a free-text response."""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    enhanced_system = (
        system_prompt
        + f"\n\n你必须返回符合以下 JSON schema 的 JSON 对象(用 ```json 代码块包裹):\n{schema_json}\n"
    )
    return llm.complete(enhanced_system, user_prompt, temperature=temperature)


def _parse_json_response(response: str, schema: Type[T]) -> T:
    """Multi-level JSON parsing degradation:
    1. ```json ... ``` fenced block
    2. bare JSON object (first ``{...}``)
    """
    # Level 1: JSON code block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return schema(**data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    # Level 2: bare JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return schema(**data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    raise StructuredOutputParseError(
        f"Could not parse structured output from response: {response[:200]}...",
        response=response,
    )
