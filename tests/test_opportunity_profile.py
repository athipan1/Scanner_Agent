from __future__ import annotations

from app.services import candidate_data_enrichment as enrichment
from app.services.opportunity_profile import build_opportunity_profile


def strong_bundle():
    return {
        "market_snapshot": {
            "currentPrice": 100.0,
            "averageVolume": 1_000_000,
            "alpacaBidPrice": 99.98,
            "alpacaAskPrice": 100.02,
            "alpacaSpreadBps": 4.0,
            "alpacaQuoteTimestamp": "2026-08-20T15:00:00+00:00",
            "alpacaQuoteAgeSeconds": 1.0,
            "quoteQualityStatus": "fresh",
            "usMarketSession": "regular",
            "usMarketOpen": True,
            "quote_quality": {
                "status": "fresh",
                "market_session": "regular",
                "market_open": True,
                "quote_age_seconds": 1.0,
            },
            "fiftyTwoWeekHigh": 102.0,
        },
        "technical": {
            "indicator_values": {
                "rsi": 58.0,
                "atr_pct": 0.025,
                "volume_ratio": 1.7,
            }
        },
        "market_rank": {
            "price": 100.0,
            "return_20d": 0.08,
            "return_60d": 0.18,
            "volume_ratio": 1.7,
            "atr_pct": 0.025,
            "trend_score": 0.9,
        },
        "data_quality": {"coverage_ratio": 0.9},
    }


def test_strong_liquid_trend_candidate_is_qualified_and_non_binding():
    profile = build_opportunity_profile(strong_bundle())

    assert profile["schema_version"] == "scanner-opportunity-profile.v1"
    assert profile["status"] == "qualified"
    assert profile["workflow_status"] == "ready"
    assert profile["opportunity_score"] >= 0.70
    assert profile["is_binding"] is False
    assert profile["manager_decision_required"] is True
    assert profile["fail_closed"] is False
    assert profile["component_scores"]["liquidity"] == 1.0
    assert profile["component_scores"]["spread"] == 1.0
    assert profile["execution_context"]["estimated_dollar_volume"] == 100_000_000.0
    assert profile["execution_context"]["quote_status"] == "fresh"
    assert profile["evidence_quality"]["coverage_ratio"] == 1.0
    assert profile["evidence_quality"]["liquid_spread_sane"] is True
    assert "strong_trend" in profile["reasons"]
    assert "strong_relative_volume" in profile["reasons"]


def test_market_closed_is_review_not_workflow_failure():
    bundle = strong_bundle()
    bundle["market_snapshot"]["quoteQualityStatus"] = "market_closed"
    bundle["market_snapshot"]["usMarketSession"] = "after_hours"
    bundle["market_snapshot"]["usMarketOpen"] = False
    bundle["market_snapshot"]["quote_quality"] = {
        "status": "market_closed",
        "market_session": "after_hours",
        "market_open": False,
        "quote_age_seconds": 3600.0,
    }

    profile = build_opportunity_profile(bundle)

    assert profile["status"] == "review"
    assert profile["workflow_status"] == "market_closed"
    assert profile["fail_closed"] is False
    assert "market_closed" in profile["reasons"]


def test_stale_regular_session_quote_is_review_not_failure():
    bundle = strong_bundle()
    bundle["market_snapshot"]["quoteQualityStatus"] = "stale_quote"
    bundle["market_snapshot"]["alpacaQuoteAgeSeconds"] = 900.0
    bundle["market_snapshot"]["quote_quality"] = {
        "status": "stale_quote",
        "market_session": "regular",
        "market_open": True,
        "quote_age_seconds": 900.0,
    }

    profile = build_opportunity_profile(bundle)

    assert profile["status"] == "review"
    assert profile["workflow_status"] == "stale_quote"
    assert profile["fail_closed"] is False
    assert "stale_quote" in profile["reasons"]


def test_liquid_stock_spread_must_stay_inside_sanity_bound():
    bundle = strong_bundle()
    bundle["market_snapshot"]["alpacaSpreadBps"] = 75.0

    profile = build_opportunity_profile(bundle)

    assert profile["status"] == "review"
    assert profile["evidence_quality"]["liquid_spread_sane"] is False
    assert "liquid_spread_out_of_bounds" in profile["reasons"]


def test_crossed_quote_fails_closed():
    bundle = strong_bundle()
    bundle["market_snapshot"]["alpacaBidPrice"] = 100.10
    bundle["market_snapshot"]["alpacaAskPrice"] = 100.00

    profile = build_opportunity_profile(bundle)

    assert profile["status"] == "avoid"
    assert profile["workflow_status"] == "fail_closed"
    assert profile["fail_closed"] is True
    assert "crossed_quote_invalid" in profile["reasons"]


def test_wide_spread_and_high_volatility_are_exposed_as_execution_risk():
    bundle = strong_bundle()
    bundle["market_snapshot"]["alpacaSpreadBps"] = 90.0
    bundle["technical"]["indicator_values"]["atr_pct"] = 0.13
    bundle["market_rank"]["atr_pct"] = 0.13
    bundle["market_rank"]["trend_score"] = 0.2
    bundle["market_rank"]["volume_ratio"] = 0.5

    profile = build_opportunity_profile(bundle)

    assert profile["status"] in {"review", "avoid"}
    assert profile["component_scores"]["spread"] == 0.05
    assert profile["component_scores"]["volatility"] == 0.05
    assert "wide_spread" in profile["reasons"]
    assert "high_volatility" in profile["reasons"]


def test_missing_execution_evidence_fails_closed_without_hiding_candidate():
    profile = build_opportunity_profile(
        {
            "market_snapshot": {},
            "technical": {"indicator_values": {}},
            "market_rank": {},
            "data_quality": {"coverage_ratio": 0.2},
        }
    )

    assert profile["status"] == "avoid"
    assert profile["workflow_status"] == "fail_closed"
    assert profile["opportunity_score"] < 0.50
    assert profile["preferred_strategy_hint"] is None
    assert "missing_dollar_volume" in profile["reasons"]
    assert "missing_live_spread" in profile["reasons"]
    assert "missing_atr" in profile["reasons"]
    assert "missing_relative_volume" in profile["reasons"]
    assert "low_data_coverage" in profile["reasons"]


def test_real_market_fixture_evidence_coverage_is_at_least_95_percent():
    fixtures = []
    for index in range(20):
        bundle = strong_bundle()
        bundle["market_snapshot"]["currentPrice"] = 50.0 + index
        bundle["market_rank"]["price"] = 50.0 + index
        fixtures.append(bundle)

    fixtures[-1]["technical"]["indicator_values"].pop("atr_pct")
    fixtures[-1]["market_rank"].pop("atr_pct")
    fixtures[-1]["technical"]["indicator_values"].pop("volume_ratio")
    fixtures[-1]["market_rank"].pop("volume_ratio")

    profiles = [build_opportunity_profile(bundle) for bundle in fixtures]
    atr_coverage = sum(
        profile["evidence_quality"]["atr_available"] for profile in profiles
    ) / len(profiles)
    relative_volume_coverage = sum(
        profile["evidence_quality"]["relative_volume_available"] for profile in profiles
    ) / len(profiles)

    assert atr_coverage >= 0.95
    assert relative_volume_coverage >= 0.95


def test_existing_data_bundle_gets_profile_without_provider_round_trip(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("existing bundle must not trigger a provider request")

    monkeypatch.setattr(enrichment, "get_market_snapshot", unexpected)
    metadata = {"details": {"data_bundle": strong_bundle()}}

    result = enrichment.enrich_candidate_metadata("AAPL", metadata)

    assert result is not metadata
    assert "opportunity_profile" not in metadata["details"]["data_bundle"]
    profile = result["details"]["data_bundle"]["opportunity_profile"]
    assert profile["status"] == "qualified"


def test_existing_profile_is_idempotent():
    bundle = strong_bundle()
    bundle["opportunity_profile"] = build_opportunity_profile(bundle)
    metadata = {"details": {"data_bundle": bundle}}

    assert enrichment.enrich_candidate_metadata("AAPL", metadata) is metadata
