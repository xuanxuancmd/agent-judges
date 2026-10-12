"""Host-agent credential resolution tests (Claude Code / OpenCode passthrough)."""

from __future__ import annotations

from agent_judges.llm.broker import LLMBroker
from agent_judges.llm.credentials import (
    env_api_key,
    env_base_url,
    is_host_provider,
)

_ANTHROPIC_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
_OPENAI_VARS = ("OPENAI_API_KEY",)
_ALL_VARS = _ANTHROPIC_VARS + _OPENAI_VARS + ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL")


def _clear_env(monkeypatch):
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)


class TestEnvApiKey:
    def test_anthropic_api_key(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
        assert env_api_key("anthropic/claude-sonnet-4-20250514") == "sk-ant-1"

    def test_anthropic_auth_token_fallback(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
        assert env_api_key("anthropic/claude-sonnet-4-20250514") == "gateway-token"

    def test_claude_code_oauth_token_fallback(self, monkeypatch):
        # `claude setup-token` + export CLAUDE_CODE_OAUTH_TOKEN (sk-ant-oat*)
        _clear_env(monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-xyz")
        assert env_api_key("anthropic/claude-sonnet-4-20250514") == "sk-ant-oat01-xyz"

    def test_api_key_wins_over_auth_token_and_oauth(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "primary")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secondary")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-tertiary")
        assert env_api_key("anthropic/claude-opus-4-20250514") == "primary"

    def test_openai_key(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
        assert env_api_key("openai/gpt-4o") == "sk-oai"

    def test_anthropic_vars_do_not_leak_to_openai(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-xyz")
        assert env_api_key("openai/gpt-4o") is None

    def test_unknown_provider_returns_none(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
        assert env_api_key("ollama/llama3") is None

    def test_no_env_returns_none(self, monkeypatch):
        _clear_env(monkeypatch)
        assert env_api_key("anthropic/claude-sonnet-4-20250514") is None


class TestEnvBaseUrl:
    def test_anthropic_base_url(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.internal/v1")
        assert env_base_url("anthropic/claude-sonnet-4-20250514") == "https://gw.internal/v1"

    def test_openai_base_url(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:4010/v1")
        assert env_base_url("openai/gpt-4o") == "http://127.0.0.1:4010/v1"

    def test_base_url_not_cross_provider(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.internal/v1")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:4010/v1")
        assert env_base_url("openai/gpt-4o") == "http://127.0.0.1:4010/v1"
        assert env_base_url("anthropic/claude-sonnet-4-20250514") == "https://gw.internal/v1"
        assert env_base_url("ollama/llama3") is None

    def test_unset_returns_none(self, monkeypatch):
        _clear_env(monkeypatch)
        assert env_base_url("anthropic/claude-sonnet-4-20250514") is None


class TestIsHostProvider:
    def test_host_providers(self):
        assert is_host_provider("anthropic/claude-sonnet-4-20250514") is True
        assert is_host_provider("openai/gpt-4o") is True

    def test_local_providers(self):
        assert is_host_provider("ollama/llama3") is False
        assert is_host_provider("some-custom/model") is False


class TestBrokerWiring:
    def test_broker_resolves_env_key(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "from-host-session")
        broker = LLMBroker(default_model="anthropic/claude-sonnet-4-20250514")
        assert broker.get_llm().api_key == "from-host-session"

    def test_explicit_key_wins_over_env(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        broker = LLMBroker(
            default_model="anthropic/claude-sonnet-4-20250514",
            default_api_key="explicit",
        )
        assert broker.get_llm().api_key == "explicit"

    def test_broker_resolves_env_base_url(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.internal/v1")
        broker = LLMBroker(default_model="anthropic/claude-sonnet-4-20250514")
        assert broker.get_llm().base_url == "https://gw.internal/v1"

    def test_broker_resolves_claude_code_oauth_token(self, monkeypatch):
        # claude setup-token session: only CLAUDE_CODE_OAUTH_TOKEN present
        _clear_env(monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-xyz")
        broker = LLMBroker(default_model="anthropic/claude-sonnet-4-20250514")
        assert broker.get_llm().api_key == "sk-ant-oat01-xyz"

    def test_explicit_base_url_wins_over_env(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env-gw/v1")
        broker = LLMBroker(
            default_model="anthropic/claude-sonnet-4-20250514",
            default_base_url="https://explicit-gw/v1",
        )
        assert broker.get_llm().base_url == "https://explicit-gw/v1"

    def test_per_model_provider_resolution(self, monkeypatch):
        # heterogeneous reviewers: anthropic key from env, openai key from env
        _clear_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
        broker = LLMBroker(default_model="anthropic/claude-sonnet-4-20250514")
        assert broker.get_llm().api_key == "sk-ant-1"
        assert broker.get_llm("openai/gpt-4o").api_key == "sk-oai"
