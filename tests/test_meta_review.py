"""Calibration formula tests (B-3/B-4).

The MetaReviewer class (in-process litellm direct mode) has been removed.
The agent-driven path handles meta-review in engine.py. These tests cover
the pure ``calibrate_confidence`` and ``serialize_verdict`` functions that
the engine calls.
"""

from __future__ import annotations

from agent_judges.meta_review import calibrate_confidence, serialize_verdict
from agent_judges.types import Severity

from fixtures.helpers import make_verdict


class TestCalibrationFormula:
    """B-4: explicit formula, never a blind confidence overwrite."""

    def test_critical_penalty_halves(self):
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.CRITICAL, confidence=0.4, satisfied=False)
        assert calibrate_confidence(original, meta) == 0.45  # 0.9 * (1-0.5)

    def test_major_penalty(self):
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.MAJOR, confidence=0.4, satisfied=False)
        assert calibrate_confidence(original, meta) == 0.63  # 0.9 * (1-0.3)

    def test_minor_penalty(self):
        original = make_verdict(Severity.MAJOR, confidence=0.9, satisfied=False)
        meta = make_verdict(Severity.MINOR, confidence=0.4, satisfied=False)
        assert calibrate_confidence(original, meta) == 0.81  # 0.9 * (1-0.1)

    def test_pass_penalty_keeps_original(self):
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.2, satisfied=True)
        assert calibrate_confidence(original, meta) == 0.9  # no penalty

    def test_confidence_adjustment_blended(self):
        original = make_verdict(Severity.PASS, confidence=0.6, satisfied=True)
        # pass penalty (0.0) -> calibrated = 0.6; adjustment +0.25 -> adjusted = 0.85
        # blend: (0.6 + 0.85) / 2 = 0.725
        meta = make_verdict(Severity.PASS, confidence=0.5, satisfied=True)
        meta.confidence_adjustment = 0.25
        assert calibrate_confidence(original, meta) == 0.725

    def test_adjustment_clamped(self):
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.5, satisfied=True)
        meta.confidence_adjustment = 0.9  # clamp(0.9+0.9) = 1.0
        # blend: (0.9 + 1.0) / 2 = 0.95
        assert calibrate_confidence(original, meta) == 0.95

    def test_meta_confidence_never_blindly_overrides(self):
        # B-4 regression: meta's own confidence (0.2) must NOT become calibrated
        original = make_verdict(Severity.PASS, confidence=0.9, satisfied=True)
        meta = make_verdict(Severity.PASS, confidence=0.2, satisfied=True)
        assert calibrate_confidence(original, meta) == 0.9


class TestSerializeVerdict:
    def test_serialize_verdict_includes_original_content(self):
        v = make_verdict(Severity.MAJOR, confidence=0.8, satisfied=False)
        text = serialize_verdict(v, "原始内容 XYZ")
        assert "原始内容 XYZ" in text
        assert "major" in text
        assert "0.8" in text
        assert "confidence_adjustment" in text
