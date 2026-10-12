"""MetaReviewer tests: calibration formula + multi-reviewer adversarial
setup (plan 8-6, B-3/B-4)."""

from __future__ import annotations

from agent_judges.debate import DebateOrchestrator
from agent_judges.meta_review import MetaReviewer
from agent_judges.types import Severity

from fixtures.helpers import (
    VERDICT_JSON_UNSATISFIED,
    make_config,
    make_registry,
    make_verdict,
)
from fixtures.mock_llm import MockLLM, MockLLMBroker


def _meta_setup(mock: MockLLM):
    registry = make_registry(
        make_config("meta-reviewer"),
        make_config("meta-reviewer-2"),
    )
    broker = MockLLMBroker(mock)
    orchestrator = DebateOrchestrator(
        registry=registry, broker=broker, debate_rounds=1
    )
    return MetaReviewer(orchestrator)


class TestCalibrationFormula:
    """B-4: explicit formula, never a blind confidence overwrite."""

    def _meta_reviewer(self):
        return _meta_setup(MockLLM())

    def test_critical_penalty_halves(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.CRITICAL, confidence=0.4, satisfied=False)
        assert m._calibrate_confidence(original, meta) == 0.45  # 0.9 × (1-0.5)

    def test_major_penalty(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.MAJOR, confidence=0.4, satisfied=False)
        assert m._calibrate_confidence(original, meta) == 0.63  # 0.9 × (1-0.3)

    def test_minor_penalty(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.MINOR, confidence=0.4, satisfied=False)
        assert m._calibrate_confidence(original, meta) == 0.81  # 0.9 × (1-0.1)

    def test_pass_penalty_keeps_original(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.2, satisfied=True)
        assert m._calibrate_confidence(original, meta) == 0.9  # no penalty

    def test_confidence_adjustment_blended(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.PASS, confidence=0.6, satisfied=True)
        # pass penalty (0.0) → calibrated = 0.6; adjustment +0.25 → adjusted = 0.85
        # blend: (0.6 + 0.85) / 2 = 0.725
        meta = make_verdict(Severity.PASS, confidence=0.5, satisfied=True)
        meta.confidence_adjustment = 0.25
        assert m._calibrate_confidence(original, meta) == 0.725

    def test_adjustment_clamped(self):
        m = self._meta_reviewer()
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.5, satisfied=True)
        meta.confidence_adjustment = 0.9  # clamp(0.9+0.9) = 1.0
        # blend: (0.9 + 1.0) / 2 = 0.95
        assert m._calibrate_confidence(original, meta) == 0.95

    def test_meta_confidence_never_blindly_overrides(self):
        # B-4 regression: meta's own confidence (0.2) must NOT become calibrated
        m = self._meta_reviewer()
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.2, satisfied=True)
        assert m._calibrate_confidence(original, meta) == 0.9


class TestMetaReviewFlow:
    def test_review_uses_two_meta_reviewers(self):
        # B-3: at least 2 meta-reviewers form a real adversarial debate
        mock = MockLLM(
            responses={
                "审查框架": VERDICT_JSON_UNSATISFIED,  # P1 (both)
                "辩论阶段": "元审查观点...",  # P2 (both)
                "辩论已结束": VERDICT_JSON_UNSATISFIED,  # P3 (both)
            }
        )
        meta = _meta_setup(mock)
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)

        calibrated, meta_result = meta.review("原始内容", original)

        assert len(meta_result.individual_verdicts) == 2
        assert len(meta_result.debate_rounds) == 1
        # critical meta-verdict → 0.9 × 0.5 = 0.45
        assert calibrated.calibrated_confidence == 0.45
        assert calibrated is original  # original verdict gets annotated in place

    def test_default_meta_reviewers_are_two(self):
        assert MetaReviewer.DEFAULT_META_REVIEWERS == [
            "meta-reviewer",
            "meta-reviewer-2",
        ]

    def test_serialize_verdict_includes_original_content(self):
        meta = _meta_setup(MockLLM())
        v = make_verdict(Severity.MAJOR, confidence=0.8, satisfied=False)
        text = meta._serialize_verdict(v, "原始内容 XYZ")
        assert "原始内容 XYZ" in text
        assert "major" in text
        assert "0.8" in text
        assert "confidence_adjustment" in text

    def test_calibration_uses_meta_confidence_adjustment(self):
        mock = MockLLM(
            responses={
                "审查框架": (
                    '```json\n{"severity": "pass", "confidence": 0.5,'
                    ' "reasoning": "ok", "findings": [], "satisfied": true,'
                    ' "confidence_adjustment": -0.4}\n```'
                ),
                "辩论阶段": "agree",
                "辩论已结束": (
                    '```json\n{"severity": "pass", "confidence": 0.5,'
                    ' "reasoning": "ok", "findings": [], "satisfied": true,'
                    ' "confidence_adjustment": -0.4}\n```'
                ),
            }
        )
        meta = _meta_setup(mock)
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        calibrated, _ = meta.review("content", original)
        # pass penalty → 0.9; adjustment −0.4 → adjusted 0.5; blend (0.9+0.5)/2 = 0.7
        assert calibrated.calibrated_confidence == 0.7
