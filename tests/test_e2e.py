"""E2E tests — real requirement documents × the full review system.

Review targets are the two requirement doc sets under ``tests/project/``
(each: ``spec.md`` + ``plan.md``):

- ``todo-app``            — simple requirement (a TODO list app)
- ``graphify-gitnexus``   — complex requirement (GitNexus-parity capabilities
                            on top of the graphify knowledge graph)

Automated, zero token (default suite): ``MockScenarioAnswerer`` drives the
judge-manager protocol (prepare → tasks → results → resume → verdict) over
the real documents — CLI + run-dir protocol + progressive gates + 4-phase
debate + synthesis + escalation, end to end.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_judges.cli import app
from agent_judges.run_state import run_dir_layout
from conftest import REVIEWERS_DIR, SKILLS_DIR
from fixtures.e2e_driver import (
    PROJECTS_DIR,
    MockScenarioAnswerer,
    drive_review,
)

TODO_DIR = PROJECTS_DIR / "todo-app"
GRAPHIFY_DIR = PROJECTS_DIR / "graphify-gitnexus"
TODO_SPEC = TODO_DIR / "spec.md"
GRAPHIFY_SPEC = GRAPHIFY_DIR / "spec.md"

_SEVERITIES = ("critical", "major", "minor", "pass")

# --- shared assertions ------------------------------------------------------


def assert_protocol_complete(outcome, *, context: bool) -> None:
    """The run must contain the full protocol artifact set across logs + evidence."""
    layout = run_dir_layout(outcome.run_id)
    assert layout["verdict"].is_file()
    assert layout["report"].is_file()
    assert layout["state"].is_file()
    for tid in set(outcome.task_ids):
        assert (layout["tasks"] / f"{tid}.md").is_file(), f"prompt missing: {tid}"
    for tid in outcome.answered:
        assert (layout["results"] / f"{tid}.md").is_file(), f"result missing: {tid}"
    report = layout["report"].read_text(encoding="utf-8")
    assert "对抗审查报告" in report
    assert "最终裁决" in report
    # the report reflects the machine verdict
    assert outcome.verdict["verdict"]["severity"] in report


def assert_reviewed_real_document(outcome, doc: Path) -> None:
    """The engine actually embedded the real document into the task prompts."""
    layout = run_dir_layout(outcome.run_id)
    first_line = next(
        line for line in doc.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    first_prompt = (
        layout["tasks"] / f"{outcome.answered[0]}.md"
    ).read_text(encoding="utf-8")
    assert first_line in first_prompt


def assert_thorough_chain(outcome) -> None:
    """Structural asserts for the problem scenario (Gate 2 → thorough)."""
    payload = outcome.verdict
    route = payload["route"]
    assert route["profile"] == "thorough"
    assert route["early_stopped"] is False
    v = payload["verdict"]
    assert v["severity"] == "critical"
    assert v["satisfied"] is False
    assert v["findings"], "critical verdict must carry findings"
    # thorough runs the meta layer → calibrated confidence → escalation
    assert v["calibrated_confidence"] is not None
    assert v["calibrated_confidence"] < payload["threshold"]
    assert v["escalate_to_human"] is True
    assert "meta_review" in payload
    assert payload["meta_review"]["verdict"]["severity"] in _SEVERITIES
    # individual verdicts are summary-only (no reasoning/findings in JSON)
    assert len(payload["individual_verdicts"]) >= 2
    assert "severity" in payload["individual_verdicts"][0]
    assert "confidence" in payload["individual_verdicts"][0]
    assert "reasoning" not in payload["individual_verdicts"][0]


def assert_verdict_shape(payload: dict) -> None:
    """Loose structural asserts for real-LLM runs (judgment varies)."""
    v = payload["verdict"]
    assert v["severity"] in _SEVERITIES
    assert 0.0 <= v["confidence"] <= 1.0
    assert isinstance(v["findings"], list)
    assert all("description" in f and "severity" in f for f in v["findings"])
    effective = v["calibrated_confidence"]
    if effective is None:
        effective = v["confidence"]
    assert v["escalate_to_human"] == (effective < payload["threshold"])
    route = payload["route"]
    assert route["profile"] in ("fast", "standard", "thorough")
    assert route["reviewer_names"]
    assert route["reason"]


# --- automated e2e: mock scenarios, zero token ------------------------------


class TestMockE2E:
    def test_todo_spec_clean_early_stop(self, tmp_path):
        """简单需求 spec × 干净通过 → Gate 1 早停(fast 档,只跑哨兵)。"""
        outcome = drive_review(
            TODO_SPEC, MockScenarioAnswerer("clean")
        )
        assert_protocol_complete(outcome, context=False)
        assert_reviewed_real_document(outcome, TODO_SPEC)
        route = outcome.verdict["route"]
        assert route["early_stopped"] is True
        assert route["profile"] == "fast"
        # (B-4) early stop reports exactly the reviewers that ran
        assert route["reviewer_names"] == ["design-reviewer"]  # first in document pool
        assert route["token_count"] < 8000
        v = outcome.verdict["verdict"]
        assert v["severity"] == "pass"
        assert v["escalate_to_human"] is False
        assert len(outcome.answered) == 1  # only the sentinel ran

    def test_todo_spec_problem_full_thorough_chain(self, tmp_path):
        """简单需求 spec × critical 发现 → Gate 2 thorough:2 轮辩论 + 元审查 + 人工升级。"""
        outcome = drive_review(
            TODO_SPEC, MockScenarioAnswerer("problem")
        )
        assert_protocol_complete(outcome, context=False)
        assert_thorough_chain(outcome)

    def test_todo_plan_clean_with_spec_context(self, tmp_path):
        """plan.md 审查以 spec.md 为背景上下文 → 上下文嵌入 prompt + 早停。"""
        outcome = drive_review(
            TODO_DIR / "plan.md",
            MockScenarioAnswerer("clean"),
            context_file=TODO_SPEC,
        )
        assert_protocol_complete(outcome, context=True)
        # context is embedded verbatim in task prompts (not snapshotted to disk)
        layout = run_dir_layout(outcome.run_id)
        first_prompt = (
            layout["tasks"] / f"{outcome.answered[0]}.md"
        ).read_text(encoding="utf-8")
        assert TODO_SPEC.read_text(encoding="utf-8") in first_prompt
        route = outcome.verdict["route"]
        assert route["early_stopped"] is True  # short plan → sentinel path
        assert outcome.verdict["verdict"]["severity"] == "pass"

    def test_graphify_spec_clean_profile_follows_content_length(self, tmp_path):
        """复杂需求 spec × 干净通过 → 档位由内容长度决定(短→早停 fast,长→standard)。"""
        outcome = drive_review(
            GRAPHIFY_SPEC, MockScenarioAnswerer("clean")
        )
        assert_protocol_complete(outcome, context=False)
        assert_reviewed_real_document(outcome, GRAPHIFY_SPEC)
        route = outcome.verdict["route"]
        if route["token_count"] < 8000:
            assert route["early_stopped"] is True
            assert route["profile"] == "fast"
        else:
            # long content starts the full panel; clean panel → standard
            assert route["early_stopped"] is False
            assert route["profile"] == "standard"
        v = outcome.verdict["verdict"]
        assert v["severity"] == "pass"
        assert v["escalate_to_human"] is False

    def test_graphify_spec_problem_full_thorough_chain(self, tmp_path):
        """复杂需求 spec × critical 发现 → thorough 全链路(长内容路径)。"""
        outcome = drive_review(
            GRAPHIFY_SPEC, MockScenarioAnswerer("problem")
        )
        assert_protocol_complete(outcome, context=False)
        assert_reviewed_real_document(outcome, GRAPHIFY_SPEC)
        assert_thorough_chain(outcome)

    def test_graphify_plan_problem_with_spec_context(self, tmp_path):
        """复杂需求 plan(以 spec 为上下文)× critical 发现 → thorough 全链路。"""
        outcome = drive_review(
            GRAPHIFY_DIR / "plan.md",
            MockScenarioAnswerer("problem"),
            context_file=GRAPHIFY_SPEC,
        )
        assert_protocol_complete(outcome, context=True)
        assert_thorough_chain(outcome)
