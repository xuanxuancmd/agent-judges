"""Shared pytest fixtures for adversarial_judge tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from adversarial_judge.reviewer import ReviewerRegistry

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
