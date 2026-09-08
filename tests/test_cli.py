"""CLI tests via typer's CliRunner with a mocked LLMBroker (plan 8-7).

The broker is monkeypatched at ``adversarial_judge.cli.review.LLMBroker`` so no test
ever hits a real API.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from adversarial_judge.cli import app

from conftest import REVIEWERS_DIR, SKILLS_DIR
from fixtures.helpers import VERDICT_JSON_SATISFIED, VERDICT_JSON_UNSATISFIED
from fixtures.mock_llm import MockLLM, MockLLMBroker

runner = CliRunner()

ROUTE_JSON = (
    '{"content_type": "spec", "complexity": "medium", "profile": "standard",'
    ' "reviewer_names": ["spec-reviewer", "design-reviewer"],'
    ' "reason": "常规规格文档"}'
)


@pytest.fixture
def install_mock_broker(monkeypatch):
    """Patch cli.LLMBroker with a factory returning a MockLLMBroker."""

    def _install(mock_llm: MockLLM):
        def factory(default_model="mock", max_budget_usd=None, **kwargs):
            return MockLLMBroker(mock_llm, max_budget_usd=max_budget_usd)

        monkeypatch.setattr("adversarial_judge.cli.review.LLMBroker", factory)

    return _install


def _base_responses():
    return {
        "审查流程路由器": ROUTE_JSON,  # auto route
        "审查框架": VERDICT_JSON_UNSATISFIED,  # Phase 1
        "辩论阶段": "我坚持存在量化指标缺失问题",  # Phase 2
        "辩论已结束": VERDICT_JSON_UNSATISFIED,  # Phase 3
    }


class TestInputs:
    def test_content_input_json_output(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "需求: 系统支持高并发",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["severity"] == "critical"
        assert payload["consensus_score"] == 1.0  # single reviewer: unanimous with itself
        assert "route" not in payload  # fully manual: no routing

    def test_file_input(self, tmp_path, install_mock_broker):
        doc = tmp_path / "spec.md"
        doc.write_text("# 规格\n系统需支持 10000 QPS。", encoding="utf-8")
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["severity"] == "critical"

    def test_file_json_input_extracts_reasoning(self, tmp_path, install_mock_broker):
        # (L-4) .json verdict file: reasoning is extracted as review content
        verdict_file = tmp_path / "verdict.json"
        verdict_file.write_text(
            json.dumps({"reasoning": "原始审查推理 ABC"}), encoding="utf-8"
        )
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(verdict_file),
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_stdin_input(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
            input="管道传入的需求内容",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["severity"] == "critical"

    def test_no_content_errors(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review",
                "--reviewers-dir", str(REVIEWERS_DIR),
            ],
        )
        assert result.exit_code == 1

    def test_stdin_plus_interactive_rejected(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--interactive",
                "--reviewers-dir", str(REVIEWERS_DIR),
            ],
            input="管道内容",
        )
        assert result.exit_code == 1  # interactive cannot share stdin with content


class TestFlowDecision:
    def test_zero_param_auto_routing(self, tmp_path, install_mock_broker):
        # zero flow params → L1 auto route; route recorded in JSON (FR-2)
        doc = tmp_path / "spec.md"
        doc.write_text("# 规格文档\n较长的规格内容……", encoding="utf-8")
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["route"]["profile"] == "standard"
        assert payload["route"]["reviewer_names"] == ["spec-reviewer", "design-reviewer"]
        assert payload["route"]["reason"] == "常规规格文档"
        # standard: 2 reviewers × 1 debate round → full debate happened
        assert len(payload["debate_rounds"]) == 1
        assert len(payload["individual_verdicts"]) == 2

    def test_profile_fast_skips_routing(self, tmp_path, install_mock_broker):
        doc = tmp_path / "spec.md"
        doc.write_text("# 短内容", encoding="utf-8")
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--profile", "fast",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["route"]["profile"] == "fast"
        assert payload["route"]["reason"] == "explicit profile: fast"
        assert len(payload["route"]["reviewer_names"]) == 1
        assert payload["stability_degraded"] is True  # fast = single-reviewer fast-check

    def test_profile_thorough_includes_meta_review(self, tmp_path, install_mock_broker):
        doc = tmp_path / "spec.md"
        doc.write_text("# 复杂交付物内容", encoding="utf-8")
        responses = _base_responses()
        # thorough profile picks 3 reviewers; meta review adds meta-reviewers
        responses["审查流程路由器"] = (
            '{"content_type": "spec", "complexity": "high", "profile": "thorough",'
            ' "reviewer_names": ["spec-reviewer", "design-reviewer",'
            ' "test-plan-reviewer"], "reason": "关键交付"}'
        )
        install_mock_broker(MockLLM(responses=responses))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--profile", "thorough",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["route"]["profile"] == "thorough"
        assert "meta_review" in payload
        # calibrated = 0.85 × (1 - 0.5) via explicit formula (B-4)
        assert payload["verdict"]["calibrated_confidence"] == 0.425

    def test_unknown_profile_errors(self, tmp_path, install_mock_broker):
        doc = tmp_path / "s.md"
        doc.write_text("x", encoding="utf-8")
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--profile", "ultra",
                "--reviewers-dir", str(REVIEWERS_DIR),
            ],
        )
        assert result.exit_code == 1

    def test_review_depth_above_cap_errors(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "x",
                "-r", "spec-reviewer",
                "--review-depth", "3",
                "--reviewers-dir", str(REVIEWERS_DIR),
            ],
        )
        assert result.exit_code == 1
        assert "上限为 2" in result.output


class TestOutput:
    def test_both_writes_two_files(self, tmp_path, install_mock_broker):
        out_dir = tmp_path / "reports"
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "测试内容",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--output", "both",
                "--output-dir", str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "report.md").exists()
        assert (out_dir / "verdict.json").exists()
        payload = json.loads((out_dir / "verdict.json").read_text(encoding="utf-8"))
        assert payload["verdict"]["severity"] == "critical"
        md = (out_dir / "report.md").read_text(encoding="utf-8")
        assert "对抗审查报告" in md

    def test_markdown_to_stdout(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "测试内容",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "markdown",
            ],
        )
        assert result.exit_code == 0
        assert "对抗审查报告" in result.output

    def test_json_never_goes_to_stderr(self, install_mock_broker):
        # (M-7) stdout carries the JSON; stderr only logs
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "测试",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0
        json.loads(result.stdout)  # stdout is pure JSON

    def test_cost_recorded_in_json(self, install_mock_broker):
        mock = MockLLM(responses=_base_responses(), cost_per_call=0.01)
        install_mock_broker(mock)
        result = runner.invoke(
            app,
            [
                "review", "--content", "测试",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        payload = json.loads(result.stdout)
        assert payload["cost"]["total_cost_usd"] == 0.01
        assert payload["cost"]["total_tokens"] > 0


class TestInteractive:
    def test_interactive_records_human_decision(self, install_mock_broker):
        low_conf = (
            '```json\n{"severity": "major", "confidence": 0.5, "reasoning": "r",'
            ' "findings": [], "satisfied": false}\n```'
        )
        install_mock_broker(MockLLM(responses={"审查框架": low_conf}))
        result = runner.invoke(
            app,
            [
                "review", "--content", "低置信度内容",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--interactive",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
            input="fail: 缺少量化指标\n",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["escalate_to_human"] is True  # 0.5 < 0.8
        assert "[人工裁决]: fail: 缺少量化指标" in payload["verdict"]["reasoning"]

    def test_interactive_not_triggered_when_confident(self, install_mock_broker):
        install_mock_broker(MockLLM(responses={"审查框架": VERDICT_JSON_SATISFIED}))
        result = runner.invoke(
            app,
            [
                "review", "--content", "高置信度内容",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--interactive",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
            input="should never be read\n",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["escalate_to_human"] is False
        assert "人工裁决" not in payload["verdict"]["reasoning"]


class TestListReviewers:
    def test_lists_stock_templates(self):
        result = runner.invoke(
            app,
            [
                "list-reviewers",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
            ],
        )
        assert result.exit_code == 0
        assert "spec-reviewer" in result.output
        assert "meta-reviewer-2" in result.output
        # referenced skills are visible (omission fix: skill display)
        assert "skills: dangerous-operations" in result.output

    def test_missing_dir_errors(self, tmp_path):
        result = runner.invoke(
            app, ["list-reviewers", "--reviewers-dir", str(tmp_path / "nope")]
        )
        assert result.exit_code == 1


class TestSkillsCli:
    def test_list_skills(self):
        result = runner.invoke(
            app, ["list-skills", "--skills-dir", str(SKILLS_DIR)]
        )
        assert result.exit_code == 0
        assert "owasp-top10" in result.output
        assert "api-contract-review" in result.output

    def test_inspect_reviewer_shows_skill_pullup(self):
        # Q1 verification: the skill IS pulled into the anonymous agent
        result = runner.invoke(
            app,
            [
                "inspect-reviewer", "dangerous-operation-scanner",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
            ],
        )
        assert result.exit_code == 0, result.output
        out = result.output
        assert "# skills   : dangerous-operations" in out
        assert "## skill: dangerous-operations" in out  # skill body injected
        assert "危险操作模式清单" in out  # the skill's knowledge content
        assert "[审查框架" in out  # anonymous-slot judge frame appended
        assert "识别" in out  # persona preserved

    def test_inspect_reviewer_skill_prefix(self):
        result = runner.invoke(
            app,
            [
                "inspect-reviewer", "skill:owasp-top10",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "# reviewer : skill-owasp-top10" in result.output
        assert "OWASP Top 10 (2021) 审查指引" in result.output

    def test_inspect_reviewer_unknown_errors(self):
        result = runner.invoke(
            app,
            [
                "inspect-reviewer", "ghost",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
            ],
        )
        assert result.exit_code == 1

    def test_skill_as_adhoc_reviewer_end_to_end(self, install_mock_broker):
        # "通用的匿名 agent 加载用户自定义的 skill" — -r skill:<name>
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "API 契约定义……",
                "-r", "skill:api-contract-review",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["severity"] == "critical"
        assert payload["stability_degraded"] is True  # single-reviewer fast-check

    def test_unknown_skill_prefix_errors_cleanly(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "x",
                "-r", "skill:ghost",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--skills-dir", str(SKILLS_DIR),
            ],
        )
        assert result.exit_code == 1
        assert "ghost" in result.output


class TestBaseUrl:
    def test_base_url_passed_to_broker(self, monkeypatch, install_mock_broker):
        captured: dict = {}

        def factory(default_model="mock", max_budget_usd=None, default_base_url=None, **kwargs):
            captured["default_base_url"] = default_base_url
            return MockLLMBroker(
                MockLLM(responses=_base_responses()), max_budget_usd=max_budget_usd
            )

        monkeypatch.setattr("adversarial_judge.cli.review.LLMBroker", factory)
        result = runner.invoke(
            app,
            [
                "review", "--content", "本地模型测试",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--base-url", "http://localhost:11434",
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["default_base_url"] == "http://localhost:11434"


class TestCredentialHint:
    _CRED_VARS = (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
    )

    def _clear_creds(self, monkeypatch):
        for var in self._CRED_VARS:
            monkeypatch.delenv(var, raising=False)

    def _invoke(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        return runner.invoke(
            app,
            [
                "review", "--content", "凭证提示测试",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )

    def test_warns_without_credentials(self, monkeypatch, install_mock_broker):
        self._clear_creds(monkeypatch)
        result = self._invoke(install_mock_broker)
        assert result.exit_code == 0, result.output
        assert "未检测到" in result.stderr
        assert "凭证" in result.stderr

    def test_no_warning_with_host_credentials(self, monkeypatch, install_mock_broker):
        self._clear_creds(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-session")
        result = self._invoke(install_mock_broker)
        assert result.exit_code == 0, result.output
        assert "未检测到" not in result.stderr

    def test_no_warning_for_local_model(self, monkeypatch, install_mock_broker):
        for var in self._CRED_VARS:
            monkeypatch.delenv(var, raising=False)
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "本地模型",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "0",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "--model", "ollama/llama3",
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "未检测到" not in result.stderr  # local models need no key


class TestReviewDepthTwo:
    def test_depth_two_runs_meta_review_twice(self, install_mock_broker):
        install_mock_broker(MockLLM(responses=_base_responses()))
        result = runner.invoke(
            app,
            [
                "review", "--content", "关键交付物",
                "-r", "spec-reviewer",
                "--debate-rounds", "0",
                "--review-depth", "2",
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["verdict"]["calibrated_confidence"] is not None
        assert "元审查第 2 层完成" in result.output  # two layers ran


class TestEvaluate:
    def test_list_format(self, tmp_path):
        preds = tmp_path / "preds.json"
        preds.write_text(
            json.dumps(
                [
                    {"satisfied": True, "confidence": 0.9},
                    {"satisfied": False, "confidence": 0.3},
                ]
            ),
            encoding="utf-8",
        )
        labels = tmp_path / "labels.json"
        labels.write_text(
            json.dumps([{"satisfied": True}, {"satisfied": True}]), encoding="utf-8"
        )
        result = runner.invoke(
            app, ["evaluate", "--predictions", str(preds), "--labels", str(labels)]
        )
        assert result.exit_code == 0, result.output
        assert "样本数        : 2" in result.output
        assert "Accuracy      : 0.5000" in result.output
        assert "AUROC         : 1.0000" in result.output

    def test_aaaj_dict_format(self, tmp_path):
        preds = tmp_path / "preds.json"
        preds.write_text(
            json.dumps(
                {
                    "requirements": [
                        {"satisfied": True, "satisfied_ratio": 0.67},
                        {"satisfied": False, "satisfied_ratio": 1.0},
                    ],
                    "judge_stats": [],
                }
            ),
            encoding="utf-8",
        )
        labels = tmp_path / "labels.json"
        labels.write_text(
            json.dumps(
                {"requirements": [{"satisfied": True}, {"satisfied": True}]}
            ),
            encoding="utf-8",
        )
        result = runner.invoke(
            app, ["evaluate", "-p", str(preds), "-l", str(labels)]
        )
        assert result.exit_code == 0, result.output
        assert "样本数        : 2" in result.output

    def test_unsupported_shape_errors(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"nope": 1}), encoding="utf-8")
        result = runner.invoke(
            app, ["evaluate", "-p", str(bad), "-l", str(bad)]
        )
        assert result.exit_code == 1

    def test_no_comparable_pairs_errors(self, tmp_path):
        preds = tmp_path / "p.json"
        preds.write_text(json.dumps([{"confidence": 0.9}]), encoding="utf-8")
        labels = tmp_path / "l.json"
        labels.write_text(json.dumps([{"satisfied": True}]), encoding="utf-8")
        result = runner.invoke(
            app, ["evaluate", "-p", str(preds), "-l", str(labels)]
        )
        assert result.exit_code == 1  # missing satisfied on predictions side
