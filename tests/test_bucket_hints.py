from app.services.bucket_hints import build_strategy_bucket_hints


def test_bucket_hints_prefers_core_for_quality_cashflow_defensive_candidate():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 90,
            "valuation_score": 50,
            "growth_score": 40,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.5,
            "pe_ratio": 24,
            "pb_ratio": 4,
        },
        {"sector": "Consumer Defensive"},
    )

    assert result["primary_strategy_bucket_hint"] == "core_dividend"
    assert result["bucket_hint_scores"]["core_dividend"] >= result["bucket_hint_scores"]["value_rebound"]
    assert "bucket-hint:core_dividend" in result["bucket_hint_tags"]


def test_bucket_hints_prefers_value_for_cheap_candidate():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 55,
            "valuation_score": 90,
            "growth_score": 25,
            "free_cash_flow": 100_000,
            "debt_to_equity": 2,
            "pe_ratio": 10,
            "pb_ratio": 1.2,
        },
        {"sector": "Financial Services"},
    )

    assert result["primary_strategy_bucket_hint"] == "value_rebound"
    assert "bucket-hint:value_rebound" in result["bucket_hint_tags"]


def test_bucket_hints_prefers_news_momentum_for_growth_candidate():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 50,
            "valuation_score": 20,
            "growth_score": 90,
            "fcf_growth": 0.8,
            "revenue_3y_cagr": 0.7,
            "pe_ratio": 60,
            "pb_ratio": 10,
        },
        {"sector": "Technology"},
    )

    assert result["primary_strategy_bucket_hint"] == "news_momentum"
    assert "bucket-hint:news_momentum" in result["bucket_hint_tags"]
