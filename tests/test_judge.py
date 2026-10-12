"""parse_verdict degradation + run_majority_vote tests (plan 8-3)."""

from __future__ import annotations

import pytest

from agent_judges.judge import parse_verdict, run_majority_vote
from agent_judges.types import Finding, Severity, Verdict

from fixtures.helpers import (
    VERDICT_JSON_SATISFIED,
    VERDICT_JSON_UNSATISFIED,
    make_config,
)
from fixtures.mock_llm import MockLLM


class TestParseVerdict:
    def test_level1_json_code_block(self):
        v = parse_verdict(VERDICT_JSON_UNSATISFIED)
        assert v.severity == Severity.CRITICAL
        assert v.confidence == 0.85
        assert v.satisfied is False
        assert len(v.findings) == 1
        f = v.findings[0]
        assert f.severity == Severity.MAJOR
        assert f.evidence == "no QPS"

    def test_level2_bare_json(self):
        v = parse_verdict(
            '前置说明 {"severity": "minor", "confidence": 0.6, '
            '"reasoning": "r", "findings": [], "satisfied": false} 后置说明'
        )
        assert v.severity == Severity.MINOR
        assert v.satisfied is False

    def test_level3_satisfied_tag(self):
        v = parse_verdict("blah <SATISFIED> 因为都满足了")
        assert v.severity == Severity.PASS
        assert v.confidence == 0.5  # capped: degraded parse escalates to humans
        assert v.satisfied is True

    def test_level3_unsatisfied_tag(self):
        v = parse_verdict("blah <UNSATISFIED> 有重大缺口")
        assert v.severity == Severity.MAJOR
        assert v.confidence == 0.5
        assert v.satisfied is False

    def test_unparsable_raises_value_error(self):
        with pytest.raises(ValueError, match="Could not parse verdict"):
            parse_verdict("no structure here at all")

    def test_pass_level_findings_are_skipped(self):
        # (M-6) findings cannot be pass; a pass finding is dropped, not fatal
        v = parse_verdict(
            '```json\n{"severity": "minor", "confidence": 0.6, "reasoning": "r",'
            ' "findings": [{"description": "d", "severity": "pass",'
            ' "confidence": 0.5, "evidence": "e", "suggestion": "s"}],'
            ' "satisfied": false}\n```'
        )
        assert v.findings == []

    def test_unknown_severity_degrades_to_minor(self):
        v = parse_verdict(
            '```json\n{"severity": "catastrophic", "confidence": 0.6,'
            ' "reasoning": "r", "findings": [], "satisfied": false}\n```'
        )
        assert v.severity == Severity.MINOR

    def test_confidence_clamped_to_unit_interval(self):
        v = parse_verdict(
            '```json\n{"severity": "minor", "confidence": 1.7,'
            ' "reasoning": "r", "findings": [], "satisfied": false}\n```'
        )
        assert v.confidence == 1.0

    def test_confidence_adjustment_extracted(self):
        v = parse_verdict(
            '```json\n{"severity": "minor", "confidence": 0.6,'
            ' "reasoning": "r", "findings": [], "satisfied": false,'
            ' "confidence_adjustment": -0.3}\n```'
        )
        assert v.confidence_adjustment == -0.3

    def test_finding_severity_pass_rejected_by_schema(self):
        with pytest.raises(Exception):
            Finding(
                description="d",
                severity=Severity.PASS,  # type: ignore[arg-type]
                confidence=0.5,
                evidence="e",
                suggestion="s",
            )


class TestSeverityEnum:
    def test_rank_ordering(self):
        # (B-1) explicit ordering — lexicographic max() would be wrong
        assert Severity.CRITICAL.rank > Severity.MAJOR.rank
        assert Severity.MAJOR.rank > Severity.MINOR.rank
        assert Severity.MINOR.rank > Severity.PASS.rank

    def test_lexicographic_max_is_wrong_and_enum_fixes_it(self):
        strings = ["critical", "minor"]
        assert max(strings) == "minor"  # the original bug
        enums = [Severity.CRITICAL, Severity.MINOR]
        assert max(enums, key=lambda s: s.rank) == Severity.CRITICAL


class TestRunMajorityVote:
    def _config(self, votes: int = 3):
        return make_config(name="voter", majority_vote=votes)

    def test_unanimous_satisfied(self):
        llm = MockLLM(responses={"voter": VERDICT_JSON_SATISFIED})
        v = run_majority_vote(llm, self._config(), "prompt", votes=3)
        assert v.satisfied is True
        assert v.confidence == 1.0  # max(1.0, 0.0)
        assert llm.call_count == 3

    def test_majority_by_one_vote(self):
        # sequential responses: 2 satisfied + 1 unsatisfied
        llm = MockLLM(
            responses={
                "voter": [
                    VERDICT_JSON_SATISFIED,
                    VERDICT_JSON_UNSATISFIED,
                    VERDICT_JSON_SATISFIED,
                ]
            }
        )
        v = run_majority_vote(llm, self._config(), "prompt", votes=3)
        assert v.satisfied is True
        assert v.confidence == round(2 / 3, 4)

    def test_minority_unsatisfied(self):
        llm = MockLLM(
            responses={
                "voter": [
                    VERDICT_JSON_UNSATISFIED,
                    VERDICT_JSON_SATISFIED,
                    VERDICT_JSON_SATISFIED,
                ]
            }
        )
        v = run_majority_vote(llm, self._config(), "prompt", votes=3)
        assert v.satisfied is True
        # max severity across votes wins (B-1)
        assert v.severity == Severity.CRITICAL

    def test_all_unsatisfied_confidence_is_one(self):
        llm = MockLLM(responses={"voter": VERDICT_JSON_UNSATISFIED})
        v = run_majority_vote(llm, self._config(), "prompt", votes=3)
        assert v.satisfied is False
        assert v.confidence == 1.0
