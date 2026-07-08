from app.services.bucket_hints import CONTROLLED_BUCKETS, build_strategy_bucket_hints


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

    assert result["bucket_hint_version"] == "scanner-bucket-hints-v2"
    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "core_dividend"
    assert result["primary_strategy_bucket_confidence"] >= 0.65
    assert result["bucket_hint_scores"]["core_dividend"] >= result["bucket_hint_scores"]["value_rebound"]
    assert "positive_free_cash_flow" in result["bucket_hint_evidence"]["core_dividend"]
    assert "bucket-hint:core_dividend" in result["bucket_hint_tags"]
    assert result["bucket_hint_is_binding"] is False
    assert result["manager_decision_required"] is True


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

    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "value_rebound"
    assert any(reason.startswith("pe_ratio:") for reason in result["bucket_hint_evidence"]["value_rebound"])
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

    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "news_momentum"
    assert result["primary_strategy_bucket_confidence"] >= 0.65
    assert "bucket-hint:news_momentum" in result["bucket_hint_tags"]


def test_bucket_hints_abstains_when_evidence_is_missing():
    result = build_strategy_bucket_hints({}, {"source": "watchlist_no_buy_signal"})

    assert result["bucket_hint_status"] == "insufficient_evidence"
    assert result["primary_strategy_bucket_hint"] is None
    assert result["primary_strategy_bucket_confidence"] is None
    assert result["strategy_bucket_hints"] == []
    assert result["bucket_hint_scores"] == {
        "core_dividend": 0.0,
        "value_rebound": 0.0,
        "news_momentum": 0.0,
    }
    assert "insufficient_bucket_evidence" in result["bucket_hint_reasons"]


def test_bucket_hints_abstains_on_close_high_confidence_scores():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 90,
            "valuation_score": 80,
            "fundamental_score": 80,
            "growth_score": 10,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.5,
            "pe_ratio": 12,
            "pb_ratio": 2.0,
        },
        {"sector": "Utilities"},
    )

    assert result["bucket_hint_status"] == "conflict"
    assert result["primary_strategy_bucket_hint"] is None
    assert result["primary_strategy_bucket_confidence"] is None
    assert result["bucket_hint_margin"] < 0.10
    assert set(result["strategy_bucket_hints"]) >= {"core_dividend", "value_rebound"}
    assert "top_bucket_scores_are_too_close" in result["bucket_hint_reasons"]


def test_bucket_hint_output_never_emits_unknown_bucket_names():
    result = build_strategy_bucket_hints(
        {"quality_score": 75, "valuation_score": 65, "growth_score": 70},
        {},
    )

    assert set(result["bucket_hint_scores"]) == set(CONTROLLED_BUCKETS)
    assert set(result["strategy_bucket_hints"]).issubset(set(CONTROLLED_BUCKETS))
    assert result["primary_strategy_bucket_hint"] in {*CONTROLLED_BUCKETS, None}
