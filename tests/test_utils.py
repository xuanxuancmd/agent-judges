"""truncate_string unit tests + debate token-fit guard (omission B-4)."""

from __future__ import annotations

import pytest

from adversarial_judge.debate import DebateOrchestrator, fit_for_model
from adversarial_judge.types import Severity
from adversarial_judge.utils.truncate import truncate_string

from fixtures.helpers import VERDICT_JSON_UNSATISFIED, make_config, make_registry
from fixtures.mock_llm import MockLLM, MockLLMBroker


class TestTruncateString:
    def test_none_returns_empty(self):
        assert truncate_string(None) == ""

    def test_short_string_unchanged(self):
        assert truncate_string("hello world") == "hello world"

    def test_long_string_truncated_with_ellipsis(self):
        text = "token " * 5000  # ~5000 tokens
        result = truncate_string(text, max_tokens=100)
        assert "..." in result
        assert len(result) < len(text)

    def test_drop_modes(self):
        text = " ".join(str(i) for i in range(500))
        for mode in ("head", "middle", "tail"):
            result = truncate_string(text, max_tokens=50, drop_mode=mode)
            assert "..." in result
            assert len(result) < len(text)

    def test_invalid_drop_mode_raises(self):
        with pytest.raises(ValueError, match="drop_mode"):
            truncate_string("x" * 100, max_tokens=5, drop_mode="sideways")

    def test_unknown_model_falls_back_to_cl100k(self):
        result = truncate_string("hello", model="totally-unknown-model")
        assert result == "hello"


class TestDebateTokenFit:
    def _orchestrator(self, mock: MockLLM) -> DebateOrchestrator:
        broker = MockLLMBroker(mock)
        registry = make_registry(make_config("r1"))
        return DebateOrchestrator(registry=registry, broker=broker, debate_rounds=0)

    def test_fit_reduces_oversized_content(self):
        huge = "内容" * 20000  # far beyond the mock's 4096-token budget
        fitted = fit_for_model(MockLLM(), huge)
        assert len(fitted) < len(huge)
        assert "..." in fitted

    def test_fit_keeps_small_content(self):
        assert fit_for_model(MockLLM(), "短内容") == "短内容"

    def test_fit_share_divides_budget(self):
        text = "字" * 5000
        full = fit_for_model(MockLLM(), text)
        half = fit_for_model(MockLLM(), text, share=2)
        assert len(half) <= len(full)

    def test_oversized_content_still_completes_review(self):
        # end-to-end guard: a huge input no longer blows the pipeline
        mock = MockLLM(responses={"审查框架": VERDICT_JSON_UNSATISFIED})
        orch = self._orchestrator(mock)
        result = orch.run("需求" * 20000, ["r1"])
        assert result.final_verdict.severity == Severity.CRITICAL
        assert result.final_verdict.satisfied is False
        assert mock.call_count == 1
