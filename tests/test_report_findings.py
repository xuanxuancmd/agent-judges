"""Report.md findings rendering tests — empty suggestion handling + ordering.

Covers:
- suggestion 为空 → "需人工排查"
- suggestion 有值 → "建议"
- findings 按 confidence 升序排列
- 低置信度标注
- verdict.json findings 同样按 confidence 升序
- CLI 总结输出产物路径
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from adversarial_judge.cli import app
from adversarial_judge.debate import DebateResult
from adversarial_judge.output import render_json, render_markdown
from adversarial_judge.types import Finding, Severity, Verdict

from fixtures.helpers import make_finding, make_verdict

REVIEWERS_DIR = Path(__file__).resolve().parent.parent / "reviewers"

VERDICT_JSON_SATISFIED = """```json
{"severity": "pass", "confidence": 0.92, "reasoning": "all good",
 "findings": [], "satisfied": true}
```"""

VERDICT_JSON_UNSATISFIED = """```json
{"severity": "critical", "confidence": 0.85, "reasoning": "bad",
 "findings": [{"description": "missing metric", "severity": "critical",
   "confidence": 0.7, "evidence": "no QPS", "suggestion": "add QPS"},
   {"description": "complex issue", "severity": "major",
   "confidence": 0.5, "evidence": "unclear arch", "suggestion": ""}],
 "satisfied": false}
```"""


def _make_result(verdict: Verdict) -> DebateResult:
    return DebateResult(
        individual_verdicts=[verdict],
        debate_rounds=[],
        final_verdicts=[verdict],
        final_verdict=verdict,
        consensus_score=1.0,
        stability_score=1.0,
        stability_degraded=True,
    )


class TestReportSuggestionHandling:
    def test_empty_suggestion_shows_investigation_needed(self):
        v = make_verdict(
            Severity.CRITICAL,
            confidence=0.5,
            satisfied=False,
            findings=[
                Finding(
                    description="complex arch issue",
                    severity=Severity.CRITICAL,
                    confidence=0.5,
                    evidence="no clear separation",
                    suggestion="",
                ),
            ],
        )
        md = render_markdown(_make_result(v), 0.8)
        assert "需人工排查" in md
        assert "reviewer 未给出修复建议" in md
        # "建议:" should not appear for this finding
        assert "建议: complex arch issue" not in md

    def test_non_empty_suggestion_shows_advice(self):
        v = make_verdict(
            Severity.MAJOR,
            confidence=0.7,
            satisfied=False,
            findings=[
                Finding(
                    description="simple typo",
                    severity=Severity.MINOR,
                    confidence=0.9,
                    evidence="page 3",
                    suggestion="fix typo",
                ),
            ],
        )
        md = render_markdown(_make_result(v), 0.8)
        assert "建议:" in md or "建议:" in md
        assert "fix typo" in md
        assert "需人工排查" not in md

    def test_mixed_findings_empty_and_nonempty_suggestion(self):
        v = make_verdict(
            Severity.CRITICAL,
            confidence=0.5,
            satisfied=False,
            findings=[
                Finding(
                    description="simple typo",
                    severity=Severity.MINOR,
                    confidence=0.9,
                    evidence="page 3",
                    suggestion="fix typo",
                ),
                Finding(
                    description="complex arch issue",
                    severity=Severity.CRITICAL,
                    confidence=0.3,
                    evidence="no clear separation",
                    suggestion="",
                ),
            ],
        )
        md = render_markdown(_make_result(v), 0.8)
        # both findings present
        assert "simple typo" in md
        assert "complex arch issue" in md
        # the empty-suggestion finding shows "需人工排查"
        assert "需人工排查" in md
        # the non-empty finding shows "建议"
        assert "fix typo" in md

    def test_findings_sorted_by_confidence_ascending(self):
        v = make_verdict(
            Severity.CRITICAL,
            confidence=0.5,
            satisfied=False,
            findings=[
                make_finding(Severity.CRITICAL, confidence=0.9),
                make_finding(Severity.MINOR, confidence=0.3),
                make_finding(Severity.MAJOR, confidence=0.6),
            ],
        )
        md = render_markdown(_make_result(v), 0.8)
        # lowest confidence (0.3) should appear first
        low_pos = md.index("0.30")
        mid_pos = md.index("0.60")
        high_pos = md.index("0.90")
        assert low_pos < mid_pos < high_pos


class TestJSONVerdictFindingsOrder:
    def test_findings_sorted_by_confidence_ascending_in_json(self):
        v = make_verdict(
            Severity.CRITICAL,
            confidence=0.5,
            satisfied=False,
            findings=[
                make_finding(Severity.CRITICAL, confidence=0.9),
                make_finding(Severity.MINOR, confidence=0.3),
                make_finding(Severity.MAJOR, confidence=0.6),
            ],
        )
        result = _make_result(v)
        json_str = render_json(result, 0.8)
        payload = json.loads(json_str)
        findings = payload["verdict"]["findings"]
        # lowest confidence first
        assert findings[0]["confidence"] == 0.3
        assert findings[1]["confidence"] == 0.6
        assert findings[2]["confidence"] == 0.9


class TestCLISummary:
    """CLI _emit_final summary on stderr points to the right artifacts."""

    def test_done_manifest_no_fix_guide_file(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("# spec", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-r", "spec-reviewer", "--debate-rounds", "0",
                "-o", "json",
            ],
        )
        assert result.exit_code == 0, result.output
        manifest = json.loads(result.stdout)
        logs_dir = Path(manifest["logs_dir"])
        (logs_dir / "results").mkdir(exist_ok=True)
        (logs_dir / "results" / "p1-spec-reviewer-v1.md").write_text(
            VERDICT_JSON_SATISFIED, encoding="utf-8"
        )
        result = runner.invoke(
            app, ["review", "--resume", "--reviewers-dir", str(REVIEWERS_DIR)]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["done"] is True
        # no fix_guide_file in manifest
        assert "fix_guide_file" not in payload
        assert payload["verdict_file"] == "verdict.json"
        assert payload["report_file"] == "report.md"
        # no fix-guide.md on disk
        evidence_dir = Path(payload["evidence_dir"])
        assert not (evidence_dir / "fix-guide.md").is_file()
        assert (evidence_dir / "verdict.json").is_file()
        assert (evidence_dir / "report.md").is_file()

    def test_summary_points_to_artifacts(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("# spec", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-r", "spec-reviewer", "--debate-rounds", "0",
                "-o", "json",
            ],
        )
        manifest = json.loads(result.stdout)
        logs_dir = Path(manifest["logs_dir"])
        (logs_dir / "results").mkdir(exist_ok=True)
        (logs_dir / "results" / "p1-spec-reviewer-v1.md").write_text(
            VERDICT_JSON_UNSATISFIED, encoding="utf-8"
        )
        result = runner.invoke(
            app, ["review", "--resume", "--reviewers-dir", str(REVIEWERS_DIR)]
        )
        combined = result.output or ""
        assert "总结" in combined
        assert "report.md" in combined
        assert "verdict.json" in combined
        assert "推导过程" in combined or "logs" in combined

    def test_report_has_empty_suggestion_handling(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("# spec", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "review", "--file", str(doc),
                "--reviewers-dir", str(REVIEWERS_DIR),
                "-r", "spec-reviewer", "--debate-rounds", "0",
                "-o", "json",
            ],
        )
        manifest = json.loads(result.stdout)
        logs_dir = Path(manifest["logs_dir"])
        (logs_dir / "results").mkdir(exist_ok=True)
        (logs_dir / "results" / "p1-spec-reviewer-v1.md").write_text(
            VERDICT_JSON_UNSATISFIED, encoding="utf-8"
        )
        result = runner.invoke(
            app, ["review", "--resume", "--reviewers-dir", str(REVIEWERS_DIR)]
        )
        payload = json.loads(result.stdout)
        report = (Path(payload["evidence_dir"]) / "report.md").read_text(
            encoding="utf-8"
        )
        # VERDICT_JSON_UNSATISFIED has two findings:
        # 1. "missing metric" with suggestion "add QPS"
        # 2. "complex issue" with empty suggestion ""
        assert "add QPS" in report
        assert "需人工排查" in report
        assert "complex issue" in report
