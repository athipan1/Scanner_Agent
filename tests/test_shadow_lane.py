from __future__ import annotations

from app.services.shadow_lane import (
    RESEARCH_MAX_CANDIDATES,
    classify_candidate_lane,
    partition_candidates_by_lane,
)


def _candidate(
    *,
    symbol="AAPL",
    status="qualified",
    score=0.80,
    spread=4.0,
    atr=0.02,
    fail_closed=False,
    components=None,
):
    profile = {
        "schema_version": "scanner-opportunity-profile.v1",
        "status": status,
        "opportunity_score": score,
        "fail_closed": fail_closed,
        "execution_context": {
            "current_price": 100.0,
            "estimated_dollar_volume": 50_000_000.0,
            "spread_bps": spread,
            "atr_pct": atr,
        },
    }
    if components is not None:
        profile["component_scores"] = components
    return {
        "symbol": symbol,
        "metadata": {
            "details": {
                "data_bundle": {
                    "opportunity_profile": profile,
                }
            }
        },
    }


def test_qualified_complete_candidate_is_production_eligible():
    decision = classify_candidate_lane(_candidate())

    assert decision["lane"] == "production"
    assert decision["production_eligible"] is True
    assert decision["research_eligible"] is False
    assert decision["broker_order_authorized"] is False


def test_review_candidate_goes_to_research_only():
    decision = classify_candidate_lane(_candidate(status="review", score=0.62))

    assert decision["lane"] == "research"
    assert decision["production_eligible"] is False
    assert decision["research_eligible"] is True
    assert decision["broker_order_authorized"] is False


def test_missing_live_spread_demotes_candidate_to_research():
    decision = classify_candidate_lane(_candidate(score=0.78, spread=None))

    assert decision["lane"] == "research"
    assert "production_missing_spread_bps" in decision["reason_codes"]


def test_off_session_historical_evidence_can_enter_shadow_without_live_spread_or_atr():
    decision = classify_candidate_lane(
        _candidate(
            status="avoid",
            score=0.42,
            spread=None,
            atr=None,
            components={
                "trend": 0.95,
                "liquidity": 1.0,
                "spread": 0.0,
                "relative_volume": 0.0,
                "volatility": 0.0,
                "data_quality": 0.90,
            },
        )
    )

    assert decision["lane"] == "research"
    assert decision["production_eligible"] is False
    assert decision["research_eligible"] is True
    assert decision["research_opportunity_score"] >= 0.50
    assert decision["research_score_source"] == "historical_components"
    assert "research_historical_evidence_override" in decision["reason_codes"]
    assert "production_missing_spread_bps" in decision["reason_codes"]
    assert "production_missing_atr_pct" in decision["reason_codes"]


def test_fail_closed_candidate_never_enters_shadow_even_with_strong_components():
    decision = classify_candidate_lane(
        _candidate(
            status="avoid",
            score=0.20,
            fail_closed=True,
            components={
                "trend": 1.0,
                "liquidity": 1.0,
                "relative_volume": 1.0,
                "volatility": 1.0,
                "data_quality": 1.0,
            },
        )
    )

    assert decision["lane"] == "blocked"
    assert decision["research_eligible"] is False
    assert "opportunity_profile_fail_closed" in decision["reason_codes"]


def test_low_score_or_missing_profile_is_blocked():
    low = classify_candidate_lane(_candidate(status="avoid", score=0.30))
    missing = classify_candidate_lane({"symbol": "MSFT", "metadata": {}})

    assert low["lane"] == "blocked"
    assert missing["lane"] == "blocked"
    assert missing["reason_codes"] == ["missing_opportunity_profile"]


def test_partition_keeps_production_and_research_separate():
    candidates = [
        _candidate(),
        _candidate(status="review", score=0.61),
        _candidate(status="avoid", score=0.20),
    ]

    production, research, summary = partition_candidates_by_lane(candidates)

    assert len(production) == 1
    assert len(research) == 1
    assert summary["blocked_count"] == 1
    assert summary["research_execution_mode"] == "shadow"
    assert summary["research_broker_order_authorized"] is False


def test_partition_caps_shadow_lane_to_top_twenty_by_research_score():
    candidates = []
    for index in range(RESEARCH_MAX_CANDIDATES + 5):
        score = 0.50 + (index * 0.01)
        candidates.append(
            _candidate(
                symbol=f"T{index:02d}",
                status="review",
                score=score,
                spread=None,
                components={
                    "trend": min(1.0, score + 0.20),
                    "liquidity": 1.0,
                    "relative_volume": score,
                    "volatility": score,
                    "data_quality": 0.90,
                },
            )
        )

    production, research, summary = partition_candidates_by_lane(candidates)

    assert production == []
    assert len(research) == RESEARCH_MAX_CANDIDATES
    assert research[0]["symbol"] == "T24"
    assert summary["research_eligible_count_before_cap"] == 25
    assert summary["research_overflow_count"] == 5
    assert summary["reason_counts"]["research_top_k_overflow"] == 5
