from app.models import ScannerCandidateContract
from app.services.bucket_hints import (
    BUCKET_HINT_POLICY_VERSION,
    CONTROLLED_BUCKETS,
    build_strategy_bucket_hints,
)


def test_bucket_hints_prefers_core_for_quality_income_candidate():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 90,
            "valuation_score": 50,
            "growth_score": 40,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.5,
            "dividend_yield": 0.03,
            "pe_ratio": 24,
            "pb_ratio": 4,
        },
        {"sector": "Consumer Defensive"},
    )

    assert result["bucket_hint_version"] == "scanner-bucket-hints-v2"
    assert result["bucket_hint_policy_version"] == BUCKET_HINT_POLICY_VERSION
    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "core_dividend"
    assert result["primary_strategy_bucket_confidence"] >= 0.65
    assert result["bucket_hint_scores"]["core_dividend"] >= result[
        "bucket_hint_scores"
    ]["value_rebound"]
    assert "positive_free_cash_flow" in result[
        "bucket_hint_supporting_evidence"
    ]["core_dividend"]
    assert any(
        reason.startswith("dividend_yield:")
        for reason in result["bucket_hint_defining_evidence"][
            "core_dividend"
        ]
    )
    assert result["bucket_hint_dominance_rule"] == (
        "quality_income_dominance"
    )
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
    assert any(
        reason.startswith("pe_ratio:")
        for reason in result["bucket_hint_defining_evidence"][
            "value_rebound"
        ]
    )
    assert result["bucket_hint_dominance_rule"] == (
        "deep_value_without_income_dominance"
    )
    assert result["strategy_bucket_hints"] == ["value_rebound"]


def test_financial_services_is_not_core_identity_by_sector_alone():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 90,
            "fundamental_score": 90,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.2,
        },
        {"sector": "Financial Services"},
    )

    assert result["bucket_hint_scores"]["core_dividend"] <= 0.59
    assert result["bucket_hint_defining_evidence"]["core_dividend"] == []
    assert result["primary_strategy_bucket_hint"] is None


def test_bucket_hints_prefers_news_momentum_for_growth_candidate():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 50,
            "valuation_score": 20,
            "growth_score": 90,
            "momentum_score": 80,
            "relative_strength_score": 75,
            "fcf_growth": 0.8,
            "revenue_3y_cagr": 0.7,
            "breakout_ratio": 0.99,
            "pe_ratio": 60,
            "pb_ratio": 10,
        },
        {"sector": "Technology"},
    )

    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "news_momentum"
    assert result["primary_strategy_bucket_confidence"] >= 0.65
    assert result["bucket_hint_dominance_rule"] == (
        "growth_momentum_dominance"
    )


def test_growth_percentage_points_are_not_mistaken_for_100x_growth():
    result = build_strategy_bucket_hints(
        {
            "growth_score": 20,
            "eps_growth": 1.1711,
            "fcf_growth": 1.9221,
        },
        {},
    )

    evidence = result["bucket_hint_supporting_evidence"]["news_momentum"]
    assert "growth_metric_support:0.0192" in evidence
    assert not any("1.9221" in reason for reason in evidence)
    assert result["bucket_hint_scores"]["news_momentum"] < 0.50


def test_bucket_hints_abstains_when_evidence_is_missing():
    result = build_strategy_bucket_hints(
        {},
        {"source": "watchlist_no_buy_signal"},
    )

    assert result["bucket_hint_status"] == "insufficient_evidence"
    assert result["primary_strategy_bucket_hint"] is None
    assert result["primary_strategy_bucket_confidence"] is None
    assert result["strategy_bucket_hints"] == []
    assert result["bucket_hint_scores"] == {
        "core_dividend": 0.0,
        "value_rebound": 0.0,
        "news_momentum": 0.0,
    }
    assert "insufficient_bucket_evidence" in result[
        "bucket_hint_reasons"
    ]


def test_deep_value_dominance_resolves_quality_overlap():
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

    assert result["bucket_hint_status"] == "suggested"
    assert result["primary_strategy_bucket_hint"] == "value_rebound"
    assert result["bucket_hint_dominance_rule"] == (
        "deep_value_without_income_dominance"
    )
    assert result["strategy_bucket_hints"] == ["value_rebound"]


def test_close_advisory_identities_use_review_not_conflict():
    result = build_strategy_bucket_hints(
        {
            "quality_score": 85,
            "valuation_score": 60,
            "growth_score": 95,
            "momentum_score": 60,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.4,
            "pe_ratio": 22,
            "revenue_3y_cagr": 0.25,
        },
        {"sector": "Healthcare"},
    )

    assert result["bucket_hint_status"] in {"review", "suggested"}
    assert result["bucket_hint_status"] != "conflict"


def test_bucket_hint_output_never_emits_unknown_bucket_names():
    result = build_strategy_bucket_hints(
        {"quality_score": 75, "valuation_score": 65, "growth_score": 70},
        {},
    )

    assert set(result["bucket_hint_scores"]) == set(CONTROLLED_BUCKETS)
    assert set(result["strategy_bucket_hints"]).issubset(
        set(CONTROLLED_BUCKETS)
    )
    assert result["primary_strategy_bucket_hint"] in {
        *CONTROLLED_BUCKETS,
        None,
    }


def test_typed_bucket_hints_are_not_copied_into_generic_tags():
    candidate = ScannerCandidateContract(
        symbol="GENERIC",
        candidate_score=0.90,
        tags=["fundamental", "profitable"],
        raw_scores={
            "quality_score": 80,
            "valuation_score": 90,
            "pe_ratio": 10,
            "pb_ratio": 1.2,
            "free_cash_flow": 100_000,
        },
        metadata={"sector": "Financial Services"},
    )

    assert candidate.bucket_hint is not None
    assert candidate.tags == ["fundamental", "profitable"]
    assert not any("bucket-hint" in tag for tag in candidate.tags)
    assert not any("bucket-candidate" in tag for tag in candidate.tags)
    assert candidate.metadata["bucket_hint_tags"]


REAL_HOURLY_FIXTURES = {
    "ACGL": {
        "fundamental_score": 91.9,
        "quality_score": 86.0,
        "growth_score": 100.0,
        "valuation_score": 90.0,
        "debt_to_equity": 0.1127406428,
        "free_cash_flow": 6_128_000_000.0,
        "revenue_3y_cagr": 0.2614046974,
        "eps_growth": 2.0333333333,
        "fcf_growth": 0.6271906532,
        "pe_ratio": 7.9138865,
        "pb_ratio": 1.5350468,
    },
    "BKNG": {
        "fundamental_score": 89.5,
        "quality_score": 80.0,
        "growth_score": 100.0,
        "valuation_score": 90.0,
        "debt_to_equity": -3.458766583,
        "free_cash_flow": 9_087_000_000.0,
        "revenue_3y_cagr": 0.1634869878,
        "eps_growth": 1.1710560626,
        "fcf_growth": 0.4689621726,
        "pe_ratio": 23.973864,
        "pb_ratio": -15.582476,
    },
    "ADBE": {
        "fundamental_score": 89.2667,
        "quality_score": 94.0,
        "growth_score": 100.0,
        "valuation_score": 66.6667,
        "debt_to_equity": 0.5719693711,
        "free_cash_flow": 9_852_000_000.0,
        "revenue_3y_cagr": 0.1052233993,
        "eps_growth": 0.6515301086,
        "fcf_growth": 0.3320713899,
        "pe_ratio": 12.675846,
        "pb_ratio": 7.6537223,
    },
    "CINF": {
        "fundamental_score": 86.0667,
        "quality_score": 86.0,
        "growth_score": 100.0,
        "valuation_score": 66.6667,
        "debt_to_equity": 0.0556847464,
        "free_cash_flow": 3_092_000_000.0,
        "revenue_3y_cagr": 0.2438798816,
        "eps_growth": 6.0065359477,
        "fcf_growth": 0.5179185076,
        "pe_ratio": 10.813877,
        "pb_ratio": 1.7863011,
    },
    "ACIC": {
        "fundamental_score": 89.2667,
        "quality_score": 94.0,
        "growth_score": 100.0,
        "valuation_score": 66.6667,
        "debt_to_equity": 0.480178861,
        "free_cash_flow": 70_870_000.0,
        "revenue_3y_cagr": 0.1491027034,
        "eps_growth": 1.2016498625,
        "fcf_growth": 1.402304723,
        "pe_ratio": 5.381395,
        "pb_ratio": 1.6652274,
    },
    "CGEN": {
        "fundamental_score": 97.5,
        "quality_score": 100.0,
        "growth_score": 100.0,
        "valuation_score": 90.0,
        "debt_to_equity": 0.0288131139,
        "free_cash_flow": 31_328_000.0,
        "revenue_3y_cagr": 1.1328080304,
        "eps_growth": 1.9743589744,
        "fcf_growth": 1.905433526,
        "pe_ratio": 6.3421054,
        "pb_ratio": 2.390873,
    },
    "BFC": {
        "fundamental_score": 87.1,
        "quality_score": 74.0,
        "growth_score": 100.0,
        "valuation_score": 90.0,
        "debt_to_equity": 0.1894364403,
        "free_cash_flow": 51_038_000.0,
        "revenue_3y_cagr": 0.1286743698,
        "eps_growth": 0.2956989247,
        "fcf_growth": 0.5402583293,
        "pe_ratio": 20.797995,
        "pb_ratio": 1.9871329,
    },
    "ACAD": {
        "fundamental_score": 89.1667,
        "quality_score": 100.0,
        "growth_score": 100.0,
        "valuation_score": 56.6667,
        "debt_to_equity": 0.0425186778,
        "free_cash_flow": 105_146_000.0,
        "revenue_3y_cagr": 0.2747805611,
        "eps_growth": 2.7313432836,
        "fcf_growth": 1.9220502477,
        "pe_ratio": 11.872146,
        "pb_ratio": 3.564085,
    },
}


def test_hourly_run_fixtures_no_longer_emit_scanner_conflict():
    sectors = {
        "ACGL": "Financial Services",
        "BKNG": "Consumer Cyclical",
        "ADBE": "Technology",
        "CINF": "Financial Services",
        "ACIC": "Financial Services",
        "CGEN": "Healthcare",
        "BFC": "Financial Services",
        "ACAD": "Healthcare",
    }

    results = {
        symbol: build_strategy_bucket_hints(
            raw_scores,
            {"sector": sectors[symbol]},
        )
        for symbol, raw_scores in REAL_HOURLY_FIXTURES.items()
    }

    assert all(
        result["bucket_hint_status"] != "conflict"
        for result in results.values()
    )
    for symbol in ("ACGL", "ADBE", "CINF", "ACIC", "CGEN"):
        assert results[symbol]["primary_strategy_bucket_hint"] == (
            "value_rebound"
        )
        assert results[symbol]["bucket_hint_status"] == "suggested"
    assert results["BKNG"]["bucket_hint_status"] == "review"
    assert results["BFC"]["primary_strategy_bucket_hint"] == (
        "value_rebound"
    )
    assert results["ACAD"]["bucket_hint_status"] in {
        "review",
        "suggested",
    }
