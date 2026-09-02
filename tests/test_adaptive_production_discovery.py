from __future__ import annotations

from types import SimpleNamespace

from app.services import adaptive_production_discovery as adaptive


def _profile(*, fail_closed: bool = False) -> dict:
    return {
        "status": "review",
        "workflow_status": "evidence_review",
        "opportunity_score": 0.60,
        "fail_closed": fail_closed,
        "strategy_affinity": {
            "trend_following": 0.40,
            "breakout": 0.50,
            "mean_reversion": 0.82,
        },
        "execution_context": {
            "quote_status": "fresh",
            "market_session": "regular",
        },
        "evidence_quality": {
            "spread_structurally_valid": True,
            "liquid_spread_sane": True,
            "coverage_ratio": 1.0,
        },
    }


def test_strategy_aware_value_rebound_can_qualify_without_relaxing_hard_safety(monkeypatch):
    monkeypatch.setattr(adaptive, "_base_build_opportunity_profile", lambda bundle: _profile())

    result = adaptive.adaptive_build_opportunity_profile(
        {"strategy_context": {"primary_strategy_bucket_hint": "value_rebound"}}
    )

    assert result["status"] == "qualified"
    assert result["workflow_status"] == "strategy_ready"
    assert result["qualification_policy"]["mode"] == "strategy_aware"
    assert result["qualification_policy"]["strategy_name"] == "mean_reversion"
    assert result["qualification_policy"]["hard_execution_safe"] is True
    assert result["qualification_policy"]["hard_execution_thresholds_relaxed"] is False


def test_strategy_aware_path_never_overrides_fail_closed(monkeypatch):
    monkeypatch.setattr(
        adaptive,
        "_base_build_opportunity_profile",
        lambda bundle: _profile(fail_closed=True),
    )

    result = adaptive.adaptive_build_opportunity_profile(
        {"strategy_context": {"primary_strategy_bucket_hint": "value_rebound"}}
    )

    assert result["status"] == "review"
    assert result["qualification_policy"]["mode"] == "none"
    assert result["qualification_policy"]["hard_execution_safe"] is False


def test_stale_regular_session_quote_retries_once_and_recovers(monkeypatch):
    snapshots = iter(
        [
            {
                "quoteQualityStatus": "stale_quote",
                "usMarketSession": "regular",
                "alpacaQuoteAgeSeconds": 90,
            },
            {
                "quoteQualityStatus": "fresh",
                "usMarketSession": "regular",
                "alpacaQuoteAgeSeconds": 1,
            },
        ]
    )
    monkeypatch.setenv("SCANNER_PRODUCTION_STALE_QUOTE_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("SCANNER_PRODUCTION_STALE_QUOTE_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr(adaptive, "_BASE_MARKET_SNAPSHOT", lambda *a, **k: next(snapshots))

    result = adaptive.adaptive_get_market_snapshot("ABC")

    assert result["quoteQualityStatus"] == "fresh"
    assert result["adaptive_quote_refresh"]["attempts"] == 1
    assert result["adaptive_quote_refresh"]["recovered"] is True
    assert result["adaptive_quote_refresh"]["hard_execution_thresholds_relaxed"] is False


def test_market_closed_quote_is_not_retried(monkeypatch):
    calls = {"count": 0}

    def snapshot(*args, **kwargs):
        calls["count"] += 1
        return {
            "quoteQualityStatus": "market_closed",
            "usMarketSession": "closed",
        }

    monkeypatch.setattr(adaptive, "_BASE_MARKET_SNAPSHOT", snapshot)
    result = adaptive.adaptive_get_market_snapshot("ABC")

    assert calls["count"] == 1
    assert result["adaptive_quote_refresh"]["attempts"] == 0


def test_discovery_backfills_lower_ranked_production_safe_candidates(monkeypatch):
    candidates = [
        SimpleNamespace(
            symbol=f"S{rank}",
            discovery_rank=rank,
            metadata={"data_bundle": {}},
        )
        for rank in range(1, 21)
    ]
    production_rows = [candidates[11], candidates[14]]

    monkeypatch.setattr(
        adaptive,
        "_base_discover_best_fundamentals",
        lambda **kwargs: (candidates, [], {"top_n": kwargs["top_n"]}),
    )
    monkeypatch.setattr(
        adaptive,
        "_BASE_ENRICH",
        lambda rows, default_exchange="NASDAQ": (
            list(rows),
            {"production_qualified_count": 2},
        ),
    )
    monkeypatch.setattr(
        adaptive,
        "partition_candidates_by_lane",
        lambda rows: (
            production_rows,
            [candidate for candidate in rows if candidate not in production_rows],
            {"production_count": 2},
        ),
    )

    selected, errors, metadata = adaptive.discover_best_fundamentals(top_n=3)

    assert errors == []
    assert [candidate.symbol for candidate in selected] == ["S12", "S15", "S1"]
    summary = metadata["adaptive_production_backfill"]
    assert summary["requested_top_n"] == 3
    assert summary["backfilled_production_count"] == 2
    assert summary["backfilled_symbols"] == ["S12", "S15"]
    assert summary["trading_thresholds_relaxed"] is False
    assert summary["broker_order_authorized"] is False


def test_same_cycle_pre_enrichment_is_reused_but_not_cross_cycle_execution_evidence():
    candidate = SimpleNamespace(
        symbol="ABC",
        discovery_rank=1,
        metadata={
            "adaptive_production_pre_enriched": True,
            "production_enrichment": {
                "status": "complete",
                "opportunity_status": "qualified",
            },
            "data_bundle": {
                "market_snapshot": {
                    "adaptive_quote_refresh": {"attempts": 1, "recovered": True}
                }
            },
        },
    )

    rows, summary = adaptive.reuse_pre_enriched_candidates([candidate])

    assert rows == [candidate]
    assert summary["production_qualified_count"] == 1
    assert summary["stale_quote_retry_attempts"] == 1
    assert summary["stale_quote_retry_recovered_count"] == 1
    assert summary["reused_same_cycle_pre_enrichment"] is True
    assert summary["production_execution_evidence_reused_across_cycles"] is False
