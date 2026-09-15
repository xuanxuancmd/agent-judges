"""``agent-judges install`` tests — template-copy checks per platform."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adversarial_judge.cli import app

runner = CliRunner()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Isolated $HOME so auto-detection and global installs are hermetic."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _install_args(*extra):
    return ["install", *extra]


class TestCodeagent:
    """Default platform — claude-compatible mechanism, .cac directory."""

    def test_default_platform_global_install(self, fake_home):
        """No --platform flag → codeagent (default), installs to ~/.cac."""
        (fake_home / ".cac").mkdir()
        result = runner.invoke(app, _install_args())
        assert result.exit_code == 0, result.output
        agents_dir = fake_home / ".cac" / "agents" / "judges"
        # only judge-manager + anonymous reviewer
        installed = sorted(p.stem for p in agents_dir.glob("*.md"))
        assert installed == ["judge-manager", "reviewer"]

    def test_reviewer_is_anonymous(self, fake_home):
        """reviewer.md has no persona — just a generic slot."""
        (fake_home / ".cac").mkdir()
        result = runner.invoke(app, _install_args())
        assert result.exit_code == 0, result.output
        text = (
            fake_home / ".cac" / "agents" / "judges" / "reviewer.md"
        ).read_text(encoding="utf-8")
        assert "匿名审查槽位" in text
        # no reviewer persona content (spec-reviewer persona, etc.)
        assert "规格文档" not in text
        assert "需求收集" not in text

    def test_judge_manager_template(self, fake_home):
        """judge-manager.md spawns the anonymous 'reviewer' subagent."""
        (fake_home / ".cac").mkdir()
        result = runner.invoke(app, _install_args())
        assert result.exit_code == 0, result.output
        text = (
            fake_home / ".cac" / "agents" / "judges" / "judge-manager.md"
        ).read_text(encoding="utf-8")
        assert "subagent_type" in text
        assert "reviewer" in text
        assert "agent-judges review --file" in text

    def test_project_scope(self, fake_home, monkeypatch, tmp_path):
        (fake_home / ".cac").mkdir()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, _install_args("--project"))
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".cac" / "agents" / "judges" / "judge-manager.md").is_file()
        assert (tmp_path / ".cac" / "agents" / "judges" / "reviewer.md").is_file()

    def test_explicit_platform_codeagent(self, fake_home):
        """--platform codeagent works even without .cac directory."""
        result = runner.invoke(app, _install_args("--platform", "codeagent"))
        assert result.exit_code == 0, result.output
        agents_dir = fake_home / ".cac" / "agents" / "judges"
        assert (agents_dir / "judge-manager.md").is_file()
        assert (agents_dir / "reviewer.md").is_file()


class TestClaudeCode:
    """Backward-compat: --platform claude-code → .claude directory."""

    def test_claude_code_global_install(self, fake_home):
        result = runner.invoke(app, _install_args("--platform", "claude-code"))
        assert result.exit_code == 0, result.output
        agents_dir = fake_home / ".claude" / "agents" / "judges"
        installed = sorted(p.stem for p in agents_dir.glob("*.md"))
        assert installed == ["judge-manager", "reviewer"]

    def test_host_alias_backward_compat(self, fake_home):
        """--host is a deprecated alias for --platform."""
        result = runner.invoke(app, _install_args("--host", "claude-code"))
        assert result.exit_code == 0, result.output
        agents_dir = fake_home / ".claude" / "agents" / "judges"
        assert (agents_dir / "judge-manager.md").is_file()


class TestOpenCode:
    def test_opencode_global_install(self, fake_home):
        result = runner.invoke(app, _install_args("--platform", "opencode"))
        assert result.exit_code == 0, result.output
        agents_dir = fake_home / ".config" / "opencode" / "agents" / "judges"
        assert (agents_dir / "judge-manager.md").is_file()
        # reviewer has mode: subagent
        text = (agents_dir / "reviewer.md").read_text(encoding="utf-8")
        assert "mode: subagent" in text
        judge = (agents_dir / "judge-manager.md").read_text(encoding="utf-8")
        assert "mode: all" in judge
        assert "judges/reviewer" in judge  # opencode path-based identity
        assert "agent-judges review --file" in judge


class TestAutoDetect:
    def test_auto_detect_codeagent(self, fake_home):
        (fake_home / ".cac").mkdir()
        result = runner.invoke(app, _install_args("--platform", "auto"))
        assert result.exit_code == 0, result.output
        assert (fake_home / ".cac" / "agents" / "judges" / "judge-manager.md").is_file()

    def test_auto_detect_opencode(self, fake_home):
        (fake_home / ".config" / "opencode").mkdir(parents=True)
        result = runner.invoke(app, _install_args("--platform", "auto"))
        assert result.exit_code == 0, result.output
        assert (
            fake_home / ".config" / "opencode" / "agents" / "judges" / "judge-manager.md"
        ).is_file()

    def test_multiple_platforms_require_explicit(self, fake_home):
        (fake_home / ".cac").mkdir()
        (fake_home / ".config" / "opencode").mkdir(parents=True)
        result = runner.invoke(app, _install_args("--platform", "auto"))
        assert result.exit_code != 0
        assert "--platform" in result.output

    def test_no_platform_errors(self, fake_home):
        result = runner.invoke(app, _install_args("--platform", "auto"))
        assert result.exit_code != 0
        assert "--platform" in result.output

    def test_unknown_platform_errors(self, fake_home):
        result = runner.invoke(app, _install_args("--platform", "vscode"))
        assert result.exit_code != 0
