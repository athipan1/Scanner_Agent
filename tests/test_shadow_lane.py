from __future__ import annotations

from app.services.shadow_lane import (
    classify_candidate_lane,
    partition_candidates_by_lane,
)


def _candidate(*, status="qualified", score=0.80, spread=4.0, atr=0.02):
    return {
        "symbol": "AAPL",
        "metadata": {
            "details": {
                "data_bundle": {
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": status,
                        "opportunity_score": score,
                        "execution_context": {
                            "current_price": 100.0,
                            "estimated_dollar_volume": 50_000_000.0,
                            "spread_bps": spread,
                            "atr_pct": atr,
                        },
                    }
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
