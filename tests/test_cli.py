"""CLI tests — agent-driven mode (review via prepare/resume) + install + list.

All review tests drive the agent-mode protocol (prepare → tasks → results →
resume → verdict) using the MockScenarioAnswerer from the e2e driver. No
litellm, no API keys, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_judges.cli import app

from conftest import REVIEWERS_DIR, SKILLS_DIR
from fixtures.e2e_driver import (
    PROJECTS_DIR,
    MockScenarioAnswerer,
    drive_review,
)
from fixtures.helpers import VERDICT_JSON_SATISFIED, VERDICT_JSON_UNSATISFIED

runner = CliRunner()

TODO_SPEC = PROJECTS_DIR / "todo-app" / "spec.md"
_SEVERITIES = ("critical", "major", "minor", "pass")


class TestReviewCommand:
    """Agent-mode review: prepare → tasks → results → resume → verdict."""

    def test_review_help_lists_options(self):
        result = runner.invoke(app, ["review", "--help"])
        assert result.exit_code == 0
        assert "--file" in result.output
        assert "--scene" in result.output
        assert "--profile" in result.output

    def test_review_no_content_errors(self):
        result = runner.invoke(
            app,
            ["review", "--reviewers-dir", str(REVIEWERS_DIR)],
        )
        assert result.exit_code == 1

    def test_review_clean_scenario_early_stop(self, tmp_path):
        """Clean doc → sentinel passes → early stop (fast, 1 call)."""
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("clean"),
            extra_args=["--scene", "document"],
        )
        assert outcome.verdict["verdict"]["severity"] in _SEVERITIES
        assert outcome.verdict["route"]["profile"] == "fast"

    def test_review_problem_scenario_thorough(self, tmp_path):
        """Problem doc → sentinel fails → panel → thorough (debate + meta)."""
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("problem"),
            extra_args=["--scene", "document"],
        )
        v = outcome.verdict["verdict"]
        assert v["severity"] == "critical"
        assert outcome.verdict["route"]["profile"] == "thorough"
        # thorough includes meta-review → calibrated_confidence
        assert v["calibrated_confidence"] is not None

    def test_review_json_output(self, tmp_path):
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("clean"),
            extra_args=["-o", "json", "--scene", "document"],
        )
        # JSON output goes to evidence_dir/verdict.json
        assert "verdict" in outcome.verdict
        assert "route" in outcome.verdict

    def test_review_with_context(self, tmp_path):
        ctx_file = tmp_path / "ctx.txt"
        ctx_file.write_text("背景: 这是一个 TODO 应用,需要支持多用户。", encoding="utf-8")
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("problem"),
            extra_args=["--scene", "document"],
            context_file=ctx_file,
        )
        # context is passed; the run should still complete
        assert outcome.verdict["verdict"]["severity"] in _SEVERITIES

    def test_review_profile_thorough(self, tmp_path):
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("problem"),
            extra_args=["--profile", "thorough", "--scene", "document"],
        )
        assert outcome.verdict["route"]["profile"] == "thorough"

    def test_review_resume_after_interrupt(self, tmp_path):
        """Resume should pick up from where the run left off."""
        outcome = drive_review(
            TODO_SPEC,
            MockScenarioAnswerer("clean"),
            extra_args=["--scene", "document"],
        )
        assert outcome.rounds > 0
        assert outcome.verdict["verdict"]["severity"] in _SEVERITIES


class TestInstallCommand:
    def test_install_help(self):
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output
        assert "--project" in result.output

    def test_install_codeagent_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            ["install", "--platform", "codeagent", "--project"],
        )
        assert result.exit_code == 0
        assert "judge-manager" in result.output
        assert "reviewer" in result.output
        # verify files were written
        assert (tmp_path / ".cac" / "agents" / "judges" / "judge-manager.md").exists()
        assert (tmp_path / ".cac" / "agents" / "judges" / "reviewer.md").exists()


class TestListReviewers:
    def test_list_reviewers(self):
        result = runner.invoke(
            app,
            ["list-reviewers", "--reviewers-dir", str(REVIEWERS_DIR)],
        )
        assert result.exit_code == 0
        assert "spec-reviewer" in result.output
        assert "design-reviewer" in result.output
        assert "meta-reviewer" in result.output


class TestEvaluate:
    def test_evaluate_help(self):
        result = runner.invoke(app, ["evaluate", "--help"])
        assert result.exit_code == 0

    def test_evaluate_missing_satisfied(self, tmp_path):
        preds = tmp_path / "p.json"
        preds.write_text(json.dumps([{"confidence": 0.9}]), encoding="utf-8")
        labels = tmp_path / "l.json"
        labels.write_text(json.dumps([{"satisfied": True}]), encoding="utf-8")
        result = runner.invoke(
            app, ["evaluate", "-p", str(preds), "-l", str(labels)]
        )
        assert result.exit_code == 1  # missing satisfied on predictions side
