"""truncate_string unit tests (pure function, no litellm).

The debate token-fit guard (fit_for_model) was part of the in-process
litellm direct mode and has been removed. The agent-driven path handles
token limits in the engine's task emission.
"""

from __future__ import annotations

import pytest

from agent_judges.utils.truncate import truncate_string


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
