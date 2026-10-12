"""Integration tests — REAL LLM calls (plan 8-10).

Credentials are inherited from the environment (typically the Claude Code /
OpenCode session that runs the test command); any one of the supported
host-session vars is sufficient:

    pytest tests/test_integration.py -m integration -v

Deselect with:
    pytest tests/ -m "not integration"
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from agent_judges.cli import app
from conftest import REVIEWERS_DIR

_HOST_LLM_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",  # claude setup-token sessions (sk-ant-oat*)
    "OPENAI_API_KEY",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not any(os.getenv(var) for var in _HOST_LLM_ENV),
        reason="requires host LLM credentials (ANTHROPIC_API_KEY / "
        "ANTHROPIC_AUTH_TOKEN / OPENAI_API_KEY), e.g. inherited from a "
        "Claude Code / OpenCode session",
    ),
]

runner = CliRunner()

CONTENT_REQUIREMENT = (
    "# 需求\n1. 系统支持高并发\n2. 用户可以导出数据\n3. 系统提供管理后台\n"
)


def test_integration_requirement_debate():
    """场景 1: 需求分析审查(两 reviewer 辩论)。"""
    result = runner.invoke(
        app,
        [
            "review", "--content", CONTENT_REQUIREMENT,
            "--scene", "document",
            "--debate-rounds", "1",
            "--review-depth", "0",
            "--llm", "litellm",  # in-process direct mode: one-shot JSON verdict
            "--reviewers-dir", str(REVIEWERS_DIR),
            "-o", "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"]["severity"] in ("critical", "major", "minor", "pass")
    assert 0.0 <= payload["verdict"]["confidence"] <= 1.0
    assert len(payload["individual_verdicts"]) == 2


def test_integration_implementation_review():
    """场景 2: 实现对照审查。"""
    result = runner.invoke(
        app,
        [
            "review", "--content",
            "# 需求: 支持导出 CSV\n# 实现: 提供了 export_json() 函数",
            "-r", "implementation-vs-requirement-reviewer",
            "--debate-rounds", "0",
            "--review-depth", "0",
            "--llm", "litellm",
            "--reviewers-dir", str(REVIEWERS_DIR),
            "-o", "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"]["severity"] in ("critical", "major", "minor", "pass")


def test_integration_meta_review_calibration():
    """场景 3: 元审查校准 confidence。"""
    result = runner.invoke(
        app,
        [
            "review", "--content", CONTENT_REQUIREMENT,
            "-r", "spec-reviewer",
            "--debate-rounds", "0",
            "--meta-review",
            "--llm", "litellm",
            "--reviewers-dir", str(REVIEWERS_DIR),
            "-o", "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "meta_review" in payload
    v = payload["verdict"]
    assert v["calibrated_confidence"] is not None
    # explicit formula, never a blind overwrite
    assert 0.0 <= v["calibrated_confidence"] <= 1.0


def test_integration_zero_param_progressive():
    """场景 4: 零参数渐进式审查(哨兵先行 + 结果驱动门控)。"""
    result = runner.invoke(
        app,
        [
            "review", "--content", CONTENT_REQUIREMENT,
            "--llm", "litellm",
            "--reviewers-dir", str(REVIEWERS_DIR),
            "-o", "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["route"]["profile"] in ("fast", "standard", "thorough")
    assert payload["route"]["reviewer_names"]
    assert payload["route"]["reason"]
