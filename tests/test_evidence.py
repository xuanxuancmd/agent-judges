"""Tests for graphify evidence collection (active verification).

These tests mock subprocess and shutil.which to verify:
1. graphify absent → silent skip (returns None)
2. content not code-like → skip (returns None)
3. graph file missing → skip (returns None)
4. graphify available + code content + graph exists → evidence injected
5. enrich_context appends evidence to existing context
6. enrich_context with no existing context returns evidence as context
7. engine prepare_progressive/prepare_fixed inject evidence into state.context
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adversarial_judge.evidence import (
    collect_graphify_evidence,
    enrich_context,
    _is_code_like,
)
from adversarial_judge.engine import prepare_progressive, prepare_fixed
from adversarial_judge.run_state import Stage
from adversarial_judge.reviewer import ReviewerConfig, ChecklistItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CODE_CONTENT = """\
import os
from pathlib import Path

class Engine:
    def __init__(self, config):
        self.config = config

    def run(self, content):
        return self._process(content)

    def _process(self, content):
        if not content:
            return None
        return content.strip()
"""

PROSE_CONTENT = """\
这是一份需求文档。系统需要支持高并发，用户量预计在10万级别。
性能要求：QPS不低于5000，响应时间不超过200ms。
可用性要求：99.9%。
"""

GRAPHIFY_OUTPUT = "## Engine\n- 类型: class\n- 文件: engine.py\n- 调用者: cli/review.py\n- 依赖: types.py, config.py"


def _make_config(name="test-reviewer"):
    return ReviewerConfig(
        name=name,
        description="test",
        system_prompt="test persona",
        checklist=[ChecklistItem(criteria="test criteria")],
    )


# ---------------------------------------------------------------------------
# _is_code_like
# ---------------------------------------------------------------------------


class TestIsCodeLike:
    def test_code_filename(self):
        assert _is_code_like("anything", "engine.py") is True

    def test_ts_filename(self):
        assert _is_code_like("anything", "app.tsx") is True

    def test_prose_filename(self):
        assert _is_code_like("anything", "spec.md") is False

    def test_code_keywords_in_content(self):
        assert _is_code_like(CODE_CONTENT, None) is True

    def test_prose_content(self):
        assert _is_code_like(PROSE_CONTENT, None) is False

    def test_empty_content(self):
        assert _is_code_like("", None) is False


# ---------------------------------------------------------------------------
# collect_graphify_evidence — skip conditions
# ---------------------------------------------------------------------------


class TestCollectGraphifyEvidenceSkip:
    def test_graphify_not_on_path(self):
        with patch("adversarial_judge.evidence.shutil.which", return_value=None):
            result = collect_graphify_evidence(CODE_CONTENT, "engine.py")
        assert result is None

    def test_content_not_code_like(self):
        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"):
            result = collect_graphify_evidence(PROSE_CONTENT, "spec.md")
        assert result is None

    def test_graph_file_missing(self, tmp_path):
        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"):
            result = collect_graphify_evidence(
                CODE_CONTENT, "engine.py", graph_path=tmp_path / "graph.json"
            )
        assert result is None


# ---------------------------------------------------------------------------
# collect_graphify_evidence — successful collection
# ---------------------------------------------------------------------------


class TestCollectGraphifyEvidenceSuccess:
    def test_returns_evidence_text(self, tmp_path):
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": GRAPHIFY_OUTPUT,
            "stderr": "",
        })()

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
            result = collect_graphify_evidence(CODE_CONTENT, "engine.py", graph_path=graph_file)

        assert result is not None
        assert "代码结构证据" in result
        assert GRAPHIFY_OUTPUT in result

    def test_graphify_failure_returns_none(self, tmp_path):
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 1,
            "stdout": "",
            "stderr": "error: something",
        })()

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
            result = collect_graphify_evidence(CODE_CONTENT, "engine.py", graph_path=graph_file)

        assert result is None

    def test_timeout_returns_none(self, tmp_path):
        import subprocess
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", side_effect=subprocess.TimeoutExpired("graphify", 15)):
            result = collect_graphify_evidence(CODE_CONTENT, "engine.py", graph_path=graph_file)

        assert result is None

    def test_empty_output_returns_none(self, tmp_path):
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        })()

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
            result = collect_graphify_evidence(CODE_CONTENT, "engine.py", graph_path=graph_file)

        assert result is None

    def test_stdout_error_pattern_returns_none(self, tmp_path):
        """graphify may print human-facing errors to stdout with rc=0."""
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        for error_pattern in ["未找到图谱文件", "error: something went wrong", "ERROR: failed"]:
            mock_result = type("R", (), {
                "returncode": 0,
                "stdout": error_pattern,
                "stderr": "",
            })()
            with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
                result = collect_graphify_evidence(CODE_CONTENT, "engine.py", graph_path=graph_file)
            assert result is None, f"Should return None for stdout containing '{error_pattern}'"


# ---------------------------------------------------------------------------
# enrich_context
# ---------------------------------------------------------------------------


class TestEnrichContext:
    def test_no_evidence_returns_original_context(self):
        with patch("adversarial_judge.evidence.shutil.which", return_value=None):
            result = enrich_context(CODE_CONTENT, "existing context", "engine.py")
        assert result == "existing context"

    def test_no_evidence_no_context_returns_none(self):
        with patch("adversarial_judge.evidence.shutil.which", return_value=None):
            result = enrich_context(CODE_CONTENT, None, "engine.py")
        assert result is None

    def test_evidence_appended_to_existing_context(self, tmp_path):
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": GRAPHIFY_OUTPUT,
            "stderr": "",
        })()

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
            result = enrich_context(CODE_CONTENT, "base context", "engine.py", graph_path=graph_file)

        assert result is not None
        assert "base context" in result
        assert "代码结构证据" in result
        assert GRAPHIFY_OUTPUT in result

    def test_evidence_becomes_context_when_none(self, tmp_path):
        graph_file = tmp_path / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": GRAPHIFY_OUTPUT,
            "stderr": "",
        })()

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result):
            result = enrich_context(CODE_CONTENT, None, "engine.py", graph_path=graph_file)

        assert result is not None
        assert "代码结构证据" in result


# ---------------------------------------------------------------------------
# Engine integration — evidence flows into state.context
# ---------------------------------------------------------------------------


class TestEngineEvidenceInjection:
    def test_prepare_progressive_injects_evidence(self, tmp_path):
        """prepare_progressive should enrich context with graphify evidence."""
        graph_dir = tmp_path / ".graph"
        graph_dir.mkdir()
        graph_file = graph_dir / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": GRAPHIFY_OUTPUT,
            "stderr": "",
        })()

        configs = {"test-reviewer": _make_config()}

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result), \
             patch("adversarial_judge.evidence.Path.cwd", return_value=tmp_path):
            state, tasks = prepare_progressive(
                content=CODE_CONTENT,
                context=None,
                filename="engine.py",
                configs=configs,
                available=["test-reviewer"],
            )

        assert state.context is not None
        assert "代码结构证据" in state.context
        assert GRAPHIFY_OUTPUT in state.context

    def test_prepare_progressive_skips_when_graphify_absent(self):
        """prepare_progressive should work normally when graphify is absent."""
        configs = {"test-reviewer": _make_config()}

        with patch("adversarial_judge.evidence.shutil.which", return_value=None):
            state, tasks = prepare_progressive(
                content=CODE_CONTENT,
                context="original context",
                filename="engine.py",
                configs=configs,
                available=["test-reviewer"],
            )

        # context unchanged — no evidence appended
        assert state.context == "original context"

    def test_prepare_fixed_injects_evidence(self, tmp_path):
        """prepare_fixed should enrich context with graphify evidence."""
        graph_dir = tmp_path / ".graph"
        graph_dir.mkdir()
        graph_file = graph_dir / "graph.json"
        graph_file.write_text("{}")

        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": GRAPHIFY_OUTPUT,
            "stderr": "",
        })()

        configs = {"test-reviewer": _make_config()}

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"), \
             patch("adversarial_judge.evidence.subprocess.run", return_value=mock_result), \
             patch("adversarial_judge.evidence.Path.cwd", return_value=tmp_path):
            state, tasks = prepare_fixed(
                content=CODE_CONTENT,
                context=None,
                filename="engine.py",
                configs=configs,
                panel=["test-reviewer"],
                debate_rounds=1,
                review_depth=0,
            )

        assert state.context is not None
        assert "代码结构证据" in state.context

    def test_prepare_fixed_skips_prose_content(self):
        """prepare_fixed should not inject evidence for prose documents."""
        configs = {"test-reviewer": _make_config()}

        with patch("adversarial_judge.evidence.shutil.which", return_value="/usr/bin/graphify"):
            state, tasks = prepare_fixed(
                content=PROSE_CONTENT,
                context="original context",
                filename="spec.md",
                configs=configs,
                panel=["test-reviewer"],
                debate_rounds=1,
                review_depth=0,
            )

        # prose content: no evidence, context unchanged
        assert state.context == "original context"
