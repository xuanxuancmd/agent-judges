"""Host-agent LLM credential resolution (Claude Code / OpenCode passthrough).

``aj`` is designed to be invoked from coding-agent sessions (design.md 1.5).
It does not require its own API keys: LLM credentials are inherited from the
calling session's environment, resolved per provider:

- ``anthropic/*``: ``ANTHROPIC_API_KEY`` → ``ANTHROPIC_AUTH_TOKEN`` (gateway
  bearer) → ``CLAUDE_CODE_OAUTH_TOKEN`` (from ``claude setup-token``; litellm
  detects the ``sk-ant-oat*`` prefix and routes to Bearer + OAuth beta
  headers). Note: Pro/Max subscription ``/login`` credentials live in
  ``~/.claude/.credentials.json`` and are NOT exported to subprocesses.
- ``openai/*``: ``OPENAI_API_KEY``
- gateway/base URL: ``ANTHROPIC_BASE_URL`` (anthropic) / ``OPENAI_BASE_URL``
  (openai) — e.g. pointing at an ``opencode-llm-proxy`` instance, since
  OpenCode does not export its ``auth.json`` credentials to subprocesses.

Resolution order in :class:`~adversarial_judge.llm.broker.LLMBroker`:
explicit constructor args > these env vars > litellm's internal fallback.
"""

from __future__ import annotations

import os

__all__ = ["env_api_key", "env_base_url"]

_HOST_PROVIDERS = ("anthropic", "openai")


def _provider_of(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else ""


def env_api_key(model: str) -> str | None:
    """First matching provider credential from the host session, if any."""
    names: tuple[str, ...]
    match _provider_of(model):
        case "anthropic":
            names = (
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "CLAUDE_CODE_OAUTH_TOKEN",
            )
        case "openai":
            names = ("OPENAI_API_KEY",)
        case _:
            return None
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def env_base_url(model: str) -> str | None:
    """Gateway base URL passthrough per provider (e.g. ``opencode-llm-proxy``)."""
    match _provider_of(model):
        case "anthropic":
            return os.getenv("ANTHROPIC_BASE_URL") or None
        case "openai":
            return os.getenv("OPENAI_BASE_URL") or None
        case _:
            return None


def is_host_provider(model: str) -> bool:
    """True when ``model`` is a hosted provider that expects credentials
    (used for the missing-credential hint; local models need none)."""
    return _provider_of(model) in _HOST_PROVIDERS
