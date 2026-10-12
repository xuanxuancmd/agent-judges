"""Structured-output degradation chain tests (B-5) + llm_verdict wiring."""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent_judges.judge import llm_verdict
from agent_judges.llm.structured_output import (
    StructuredOutputParseError,
    force_structured_output,
)
from agent_judges.types import Severity, Verdict

from fixtures.helpers import VERDICT_JSON_SATISFIED, make_config
from fixtures.mock_llm import MockLLM


class Sample(BaseModel):
    answer: int


class StubLLM:
    """Scriptable stub for the three force_structured_output levels."""

    def __init__(self, tool_response=None, rf_content=None, text_response=None):
        self.tool_response = tool_response  # Level 1: tool_calls payload
        self.rf_content = rf_content  # Level 2: response_format content
        self.text_response = text_response  # Level 3: free text
        self.completion_calls: list[dict] = []
        self.complete_calls = 0

    def _completion(self, **kwargs):
        self.completion_calls.append(kwargs)
        if "tools" in kwargs:
            if self.tool_response is None:
                raise RuntimeError("no tool path")
            return {
                "choices": [
                    {"message": {"content": None, "tool_calls": self.tool_response}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        if self.rf_content is None:
            raise RuntimeError("no response_format path")
        return {
            "choices": [{"message": {"content": self.rf_content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    def _post_completion(self, resp) -> None:  # cost accounting no-op
        pass

    def complete(self, system_prompt, user_prompt, temperature=None):
        self.complete_calls += 1
        return self.text_response


def _tool_call(arguments: dict):
    return [
        {
            "function": {
                "name": "submit_verdict",
                "arguments": json.dumps(arguments),
            }
        }
    ]


class TestForceStructuredOutput:
    def test_level1_tool_use_success(self):
        stub = StubLLM(tool_response=_tool_call({"answer": 42}))
        result = force_structured_output(stub, "sys", "user", Sample)
        assert result.answer == 42
        assert "tools" in stub.completion_calls[0]  # tool-use was level 1

    def test_level1_falls_through_to_level2(self):
        stub = StubLLM(
            tool_response=None, rf_content='{"answer": 7}'
        )
        result = force_structured_output(stub, "sys", "user", Sample)
        assert result.answer == 7
        assert stub.completion_calls[1].get("response_format") == {
            "type": "json_object"
        }

    def test_level3_prompt_injection_with_json_block(self):
        stub = StubLLM(
            tool_response=None,
            rf_content=None,
            text_response='前置说明\n```json\n{"answer": 3}\n```\n后置',
        )
        result = force_structured_output(stub, "sys", "user", Sample)
        assert result.answer == 3
        assert stub.complete_calls == 1  # level 3 used llm.complete

    def test_all_levels_fail_raises_with_raw_response(self):
        raw = "完全没有结构化内容的回复 <SATISFIED>"
        stub = StubLLM(
            tool_response=None, rf_content=None, text_response=raw
        )
        try:
            force_structured_output(stub, "sys", "user", Sample)
            raise AssertionError("should have raised")
        except StructuredOutputParseError as exc:
            assert exc.response == raw  # raw response carried for fallbacks


class TestLlmVerdictWiring:
    def test_structured_success_returns_verdict_directly(self):
        mock = MockLLM(responses={"审查框架": VERDICT_JSON_SATISFIED})
        v = llm_verdict(mock, "审查框架 persona", "user prompt")
        assert v.severity == Severity.PASS
        assert v.satisfied is True

    def test_tag_fallback_on_same_response_no_extra_call(self):
        tag_response = "分析……<SATISFIED> 满足"
        mock = MockLLM(responses={"审查框架": tag_response})
        v = llm_verdict(mock, "审查框架 persona", "user prompt")
        assert v.satisfied is True
        assert v.confidence == 0.5  # degraded parse: capped
        assert mock.call_count == 1  # exactly one LLM call, no retry

    def test_unparsable_everywhere_raises(self):
        mock = MockLLM(responses={"审查框架": "纯文本,无标签无 JSON"})
        try:
            llm_verdict(mock, "审查框架 persona", "user prompt")
            raise AssertionError("should have raised")
        except ValueError as exc:
            assert "Could not parse verdict" in str(exc)
        assert mock.call_count == 1

    def test_majority_vote_path_uses_structured_chain(self):
        # run_majority_vote → llm_verdict → complete_json: strict parse of
        # canned ```json responses succeeds without tag fallback
        from agent_judges.judge import run_majority_vote

        mock = MockLLM(responses={"voter": VERDICT_JSON_SATISFIED})
        reviewer = make_config(name="voter", majority_vote=3)
        v = run_majority_vote(mock, reviewer, "prompt", votes=3)
        assert v.satisfied is True
        assert mock.call_count == 3
