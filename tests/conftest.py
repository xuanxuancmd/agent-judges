"""Shared pytest fixtures for agent_judges tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_judges.reviewer import ReviewerRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEWERS_DIR = REPO_ROOT / "reviewers"
SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture(scope="session")
def stock_registry() -> ReviewerRegistry:
    """Registry over the stock reviewers/ + skills/ directories."""
    return ReviewerRegistry(REVIEWERS_DIR, skills_dir=SKILLS_DIR)


@pytest.fixture(scope="session")
def stock_reviewers_dir() -> Path:
    return REVIEWERS_DIR


@pytest.fixture(scope="session")
def stock_skills_dir() -> Path:
    return SKILLS_DIR


@pytest.fixture(autouse=True)
def _isolate_harness(tmp_path, monkeypatch):
    """Redirect .harness/logs/ and .harness/evidence/ to per-test tmp_path
    so agent-mode runs don't pollute the repo working tree."""
    monkeypatch.setenv(
        "AGENT_JUDGES_LOGS_ROOT", str(tmp_path / "logs" / "judges")
    )
    monkeypatch.setenv(
        "AGENT_JUDGES_EVIDENCE_ROOT", str(tmp_path / "evidence" / "judges")
    )
