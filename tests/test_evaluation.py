"""Evaluation utilities tests: AUROC (fixed tie-aware), infer_confidence
degradation chain, build_pairs pipeline (plan 8-9)."""

from __future__ import annotations

from adversarial_judge.evaluation import (
    accuracy,
    auroc,
    build_pairs,
    infer_confidence,
    mean_confidence,
)


class TestAuroc:
    def test_perfect_ordering_is_one(self):
        pairs = [(1, 0.9), (1, 0.8), (0, 0.3), (0, 0.2)]
        assert abs(auroc(pairs) - 1.0) < 0.001

    def test_reversed_ordering_is_zero(self):
        pairs = [(1, 0.1), (1, 0.2), (0, 0.8), (0, 0.9)]
        assert abs(auroc(pairs) - 0.0) < 0.001

    def test_all_ties_is_half(self):
        pairs = [(1, 0.5), (1, 0.5), (0, 0.5), (0, 0.5)]
        assert abs(auroc(pairs) - 0.5) < 0.001

    def test_balanced_interleave_is_half(self):
        # positives {0.6, 0.3} vs negatives {0.5, 0.4}:
        # 0.6 beats both, 0.3 beats none → 2/4
        pairs = [(1, 0.6), (1, 0.3), (0, 0.5), (0, 0.4)]
        assert abs(auroc(pairs) - 0.5) < 0.001

    def test_partial_ordering(self):
        # positives {0.6, 0.4} vs negatives {0.5, 0.3}: 3/4
        pairs = [(1, 0.6), (0, 0.5), (1, 0.4), (0, 0.3)]
        assert abs(auroc(pairs) - 0.75) < 0.001

    def test_degenerate_all_positive_is_half(self):
        assert auroc([(1, 0.9), (1, 0.8)]) == 0.5

    def test_degenerate_all_negative_is_half(self):
        assert auroc([(0, 0.9), (0, 0.8)]) == 0.5

    def test_partial_ties(self):
        # one tie pair + clean separation:
        # positives {0.9, 0.5} vs negatives {0.5, 0.1}:
        # 0.9 beats both (2) + tie 0.5 vs 0.5 (0.5) + 0.5 beats 0.1 (1) → 3.5/4
        pairs = [(1, 0.9), (1, 0.5), (0, 0.5), (0, 0.1)]
        assert abs(auroc(pairs) - 0.875) < 0.001


class TestInferConfidence:
    def test_explicit_confidence_field(self):
        assert infer_confidence({"confidence": 0.7}) == 0.7

    def test_satisfied_ratio_formula(self):
        # AaaJ formula: max(r, 1-r)
        assert infer_confidence({"satisfied_ratio": 0.7}) == 0.7
        assert infer_confidence({"satisfied_ratio": 0.2}) == 0.8

    def test_judge_stats_confidence(self):
        stats = [{"llm_stats": {"confidence": 0.66}}]
        assert infer_confidence({}, stats, 0) == 0.66

    def test_judge_stats_satisfied_ratio(self):
        stats = [{"llm_stats": {"satisfied_ratio": 0.25}}]
        assert infer_confidence({}, stats, 0) == 0.75

    def test_legacy_fallback_one_vote(self):
        assert infer_confidence({}, None, 0) == 1.0

    def test_stats_index_out_of_range(self):
        stats = [{"llm_stats": {"confidence": 0.5}}]
        assert infer_confidence({}, stats, 5) == 1.0


class TestBuildPairs:
    def test_pairs_zipped_with_labels(self):
        preds = [
            {"satisfied": True, "confidence": 0.9},
            {"satisfied": False, "confidence": 0.6},
        ]
        humans = [{"satisfied": True}, {"satisfied": True}]
        pairs = build_pairs(preds, humans)
        assert pairs == [(1, 0.9), (0, 0.6)]

    def test_missing_labels_skipped(self):
        preds = [{"satisfied": True}, {}]
        humans = [{"satisfied": True}, {"satisfied": False}]
        pairs = build_pairs(preds, humans)
        assert pairs == [(1, 1.0)]  # second skipped (no predicted label)

    def test_accuracy_and_mean_confidence(self):
        pairs = [(1, 0.9), (0, 0.7), (1, 0.8)]
        assert accuracy(pairs) == 2 / 3
        assert abs(mean_confidence(pairs) - 0.8) < 1e-9

    def test_empty(self):
        assert accuracy([]) == 0.0
        assert mean_confidence([]) == 0.0
