import pytest
from app.scoring.fundamental_score import calculate_quality_score, calculate_growth_score, calculate_valuation_score

def test_calculate_quality_score_granular():
    # Test high ROE
    metrics = {"roe": 20, "roa": 12, "debt_to_equity": 0.3, "free_cash_flow": 100, "profit_margins": 15}
    # All should be 1.0 -> 100%
    assert calculate_quality_score(metrics) == 100.0

    # Test medium ROE
    metrics = {"roe": 12, "roa": 8, "debt_to_equity": 0.8, "free_cash_flow": 100, "profit_margins": 8}
    # 0.7 + 0.7 + 0.7 + 1.0 + 0.7 = 3.8 / 5 = 0.76 -> 76%
    assert calculate_quality_score(metrics) == pytest.approx(76.0)

    # Test low ROE
    metrics = {"roe": 6, "roa": 5, "debt_to_equity": 1.2, "free_cash_flow": -10, "profit_margins": 5}
    # 0.3 + 0.3 + 0.3 + 0.0 + 0.3 = 1.2 / 5 = 0.24 -> 24%
    assert calculate_quality_score(metrics) == pytest.approx(24.0)

def test_calculate_growth_score_granular():
    # Test high growth
    metrics = {"revenue_cagr": 15, "eps_growth": 20}
    assert calculate_growth_score(metrics) == 100.0

    # Test medium growth
    metrics = {"revenue_cagr": 8, "eps_growth": 9}
    # 0.7 + 0.7 = 1.4 / 2 = 0.7 -> 70%
    assert calculate_growth_score(metrics) == pytest.approx(70.0)

def test_calculate_valuation_score_granular():
    # Test good valuation
    metrics = {"pe_ratio": 15, "peg_ratio": 0.5, "pb_ratio": 2.0}
    assert calculate_valuation_score(metrics) == 100.0

    # Test fair valuation
    metrics = {"pe_ratio": 25, "peg_ratio": 1.2, "pb_ratio": 3.5}
    # 0.7 + 0.7 + 0.7 = 2.1 / 3 = 0.7 -> 70%
    assert calculate_valuation_score(metrics) == pytest.approx(70.0)

    # Test expensive valuation
    metrics = {"pe_ratio": 35, "peg_ratio": 1.7, "pb_ratio": 5.0}
    # 0.3 + 0.3 + 0.3 = 0.9 / 3 = 0.3 -> 30%
    assert calculate_valuation_score(metrics) == pytest.approx(30.0)
