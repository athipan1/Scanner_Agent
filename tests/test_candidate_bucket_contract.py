from app.models import CandidateResult, ScannerCandidateContract


def test_technical_candidate_gets_news_momentum_hint_from_technical_evidence():
    candidate = CandidateResult(
        symbol="MOMO",
        confidence_score=0.91,
        recommendation="STRONG_BUY",
        metadata={
            "details": {
                "growth_score": 0.82,
                "momentum_score": 0.91,
                "relative_strength_score": 0.84,
                "indicator_score": 0.88,
                "technical_vote_score": 0.86,
                "sector_rotation_score": 0.70,
                "scanner_v50": {
                    "indicator_values": {
                        "volume_ratio": 1.8,
                        "breakout_ratio": 0.99,
                    }
                },
            }
        },
    )

    assert candidate.bucket_hint is not None
    assert candidate.bucket_hint.bucket_hint_status == "suggested"
    assert candidate.bucket_hint.primary_strategy_bucket_hint == (
        "news_momentum"
    )
    assert candidate.metadata["primary_strategy_bucket_hint"] == (
        "news_momentum"
    )
    assert candidate.metadata["primary_strategy_bucket_confidence"] >= 0.65
    assert candidate.metadata["bucket_hint_is_binding"] is False
    assert candidate.bucket_hint.bucket_hint_policy_version == (
        "scanner-bucket-hint-policy-v3"
    )


def test_fundamental_candidate_gets_value_hint_from_nested_metrics():
    candidate = CandidateResult(
        symbol="VALUE",
        confidence_score=0.82,
        recommendation="A",
        metadata={
            "quality": {
                "score": 60,
                "free_cash_flow": 500000,
                "debt_to_equity": 1.4,
            },
            "growth": {
                "score": 30,
                "revenue_cagr": 0.08,
                "eps_growth": 0.05,
            },
            "valuation": {
                "score": 92,
                "pe_ratio": 11,
                "pb_ratio": 1.1,
            },
            "grade": "A",
        },
    )

    assert candidate.bucket_hint.primary_strategy_bucket_hint == (
        "value_rebound"
    )
    assert candidate.metadata["bucket_hint_status"] == "suggested"
    assert any(
        reason.startswith("pe_ratio:")
        for reason in candidate.metadata[
            "bucket_hint_defining_evidence"
        ]["value_rebound"]
    )


def test_watchlist_candidate_abstains_instead_of_manufacturing_bucket():
    candidate = CandidateResult(
        symbol="WATCH",
        confidence_score=0.55,
        recommendation="WATCHLIST",
        metadata={
            "source": "yfinance_market_data",
            "selection_mode": "watchlist_no_buy_signal",
            "market_cap": 10_000_000_000,
            "sector": "Technology",
        },
    )

    assert candidate.bucket_hint.bucket_hint_status == (
        "insufficient_evidence"
    )
    assert candidate.bucket_hint.primary_strategy_bucket_hint is None
    assert candidate.metadata["strategy_bucket_hints"] == []


def test_scanner_contract_mirrors_typed_hint_without_polluting_tags():
    candidate = ScannerCandidateContract(
        symbol="CORE",
        candidate_score=0.80,
        recommendation_hint="FUNDAMENTAL_TOP_10",
        tags=["fundamental", "quality"],
        raw_scores={
            "quality_score": 92,
            "valuation_score": 45,
            "growth_score": 35,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.4,
            "dividend_yield": 0.035,
        },
        metadata={"sector": "Consumer Defensive"},
    )

    assert candidate.bucket_hint.primary_strategy_bucket_hint == (
        "core_dividend"
    )
    assert candidate.metadata["primary_strategy_bucket_hint"] == (
        "core_dividend"
    )
    assert candidate.metadata["bucket_hint_version"] == (
        "scanner-bucket-hints-v2"
    )
    assert candidate.metadata["bucket_hint_policy_version"] == (
        "scanner-bucket-hint-policy-v3"
    )
    assert candidate.tags == ["fundamental", "quality"]
    assert "bucket-hint:core_dividend" in candidate.metadata[
        "bucket_hint_tags"
    ]
    assert candidate.bucket_hint.manager_decision_required is True
