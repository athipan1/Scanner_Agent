import math

import pytest

from app.scoring import fundamental_score


def test_valuation_score_accepts_numeric_strings():
    score = fundamental_score.calculate_valuation_score(
        {
            "pe_ratio": "18.5",
            "peg_ratio": "1.25",
            "pb_ratio": "4.0",
        }
    )

    assert score == pytest.approx(80.0)


def test_invalid_provider_values_are_skipped_without_free_points():
    score = fundamental_score.calculate_valuation_score(
        {
            "pe_ratio": "not-a-number",
            "peg_ratio": None,
            "pb_ratio": "2.5",
        }
    )

    assert score == pytest.approx(100.0)
    assert fundamental_score.calculate_valuation_score(
        {
            "pe_ratio": "not-a-number",
            "peg_ratio": float("nan"),
            "pb_ratio": float("inf"),
        }
    ) is None


def test_component_score_strings_are_normalized_before_weighting(monkeypatch):
    monkeypatch.setattr(fundamental_score.settings, "QUALITY_SCORE_WEIGHT", 0.4)
    monkeypatch.setattr(fundamental_score.settings, "GROWTH_SCORE_WEIGHT", 0.3)
    monkeypatch.setattr(fundamental_score.settings, "VALUATION_SCORE_WEIGHT", 0.3)

    score = fundamental_score.calculate_fundamental_score(
        {
            "quality_score": "80",
            "growth_score": "60",
            "valuation_score": "40",
        }
    )

    assert score == pytest.approx(62.0)


def test_grade_rejects_non_finite_scores():
    with pytest.raises(ValueError):
        fundamental_score.get_grade(math.nan)
