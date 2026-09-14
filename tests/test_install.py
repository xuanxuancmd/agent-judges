"""``agent-judges install`` tests — golden-file checks against fake hosts."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adversarial_judge.cli import app

from conftest import REVIEWERS_DIR, SKILLS_DIR

runner = CliRunner()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Isolated $HOME so auto-detection and global installs are hermetic."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _install_args(*extra):
    return [
        "install",
        "--reviewers-dir", str(REVIEWERS_DIR),
        "--skills-dir", str(SKILLS_DIR),
        *extra,
    ]


class TestClaudeCode:
    def test_auto_detect_and_global_install(self, fake_home):
        (fake_home / ".claude").mkdir()
        result = runner.invoke(app, _install_args())
        assert result.exit_code == 0, result.output
        # namespaced under judges/ — separate from the user's own agents
        agents_dir = fake_home / ".claude" / "agents" / "judges"
        # judge-manager + 20 reviewers
        installed = sorted(p.stem for p in agents_dir.glob("*.md"))
        assert "judge-manager" in installed
        assert "spec-reviewer" in installed
        assert "meta-reviewer" in installed
        assert len(installed) >= 21

    def test_reviewer_agent_compilation(self, fake_home):
        (fake_home / ".claude").mkdir()
        result = runner.invoke(app, _install_args())
        assert result.exit_code == 0, result.output
        text = (
            fake_home / ".claude" / "agents" / "judges" / "spec-reviewer.md"
        ).read_text(encoding="utf-8")
        # no-direct-invoke guard in the description
        assert text.startswith("---")
        assert "请勿直接触发" in text
        # persona + system-fixed judge frame merged into the body
        assert "规格文档" in text
        assert "审查框架" in text
        assert "证据" in text  # the frame's evidence discipline
        # engine-only keys are stripped from the generated frontmatter
        assert "checklist:" not in text
        assert "majority_vote:" not in text
        assert "weight:" not in text
        # claude-code identity comes from frontmatter — names stay unprefixed
        assert "name: spec-reviewer" in text
        # skill knowledge is injected into the persona at compile time
        scanner = (
            fake_home / ".claude" / "agents" / "judges"
            / "dangerous-operation-scanner.md"
        ).read_text(encoding="utf-8")
        assert "危险操作模式清单" in scanner  # dangerous-operations skill body

    def test_model_passthrough(self, fake_home, tmp_path):
        (fake_home / ".claude").mkdir()
        src = tmp_path / "reviewers"
        src.mkdir()
        (src / "m1.md").write_text(
            "---\nname: m1\ndescription: d\nmodel: opus\n"
            "checklist:\n  - criteria: c\n---\n\npersona\n",
            encoding="utf-8",
        )
        result = runner.invoke(app, ["install", "--reviewers-dir", str(src)])
        assert result.exit_code == 0, result.output
        text = (
            fake_home / ".claude" / "agents" / "judges" / "m1.md"
        ).read_text(encoding="utf-8")
        assert "model: opus" in text  # host-namespace model passed through

    def test_project_scope(self, fake_home, monkeypatch, tmp_path):
        (fake_home / ".claude").mkdir()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, _install_args("--project"))
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".claude" / "agents" / "judges" / "judge-manager.md").is_file()


class TestOpenCode:
    def test_global_install_with_subagent_mode(self, fake_home):
        (fake_home / ".config" / "opencode").mkdir(parents=True)
        result = runner.invoke(app, _install_args("--host", "opencode"))
        assert result.exit_code == 0, result.output
        # docs-canonical agents/ dir + judges/ namespace
        agents_dir = fake_home / ".config" / "opencode" / "agents" / "judges"
        assert (agents_dir / "judge-manager.md").is_file()
        text = (agents_dir / "spec-reviewer.md").read_text(encoding="utf-8")
        assert "mode: subagent" in text  # opencode reviewers are not user-facing
        judge = (agents_dir / "judge-manager.md").read_text(encoding="utf-8")
        assert "mode: all" in judge  # judge-manager is both primary and subagent
        assert "agent-judges review --file" in judge  # driver protocol text
        # opencode names come from the file path → the driver must map the
        # engine's agent field onto the judges/ namespace
        assert '"judges/" + 任务的 agent 字段' in judge


class TestDetectionErrors:
    def test_both_hosts_require_explicit(self, fake_home):
        (fake_home / ".claude").mkdir()
        (fake_home / ".config" / "opencode").mkdir(parents=True)
        result = runner.invoke(app, _install_args())
        assert result.exit_code != 0
        assert "--host" in result.output

    def test_no_host_errors(self, fake_home):
        result = runner.invoke(app, _install_args())
        assert result.exit_code != 0
        assert "--host" in result.output

    def test_unknown_host_errors(self, fake_home):
        result = runner.invoke(app, _install_args("--host", "vscode"))
        assert result.exit_code != 0
