from app.services import candidate_data_enrichment as enrichment


def scanner_details():
    return {
        "resolved_exchange": "NASDAQ",
        "raw_recommendation": "BUY",
        "scanner_v50": {
            "indicator_values": {
                "close": 100.0,
                "rsi": 58.0,
                "macd": 2.0,
                "sma50": 95.0,
                "sma200": 80.0,
                "atr": 2.5,
            },
            "relative_strength_values": {"perf_1m": 8.0},
            "growth_values": {"earnings_growth": 15.0},
            "market_rank": {
                "price": 100.0,
                "return_20d": 0.08,
                "return_60d": 0.18,
                "volume_ratio": 1.4,
                "trend_score": 0.9,
            },
            "fundamental": {
                "market_cap": 3_000_000_000_000,
                "average_volume": 50_000_000,
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "revenue_growth": 0.08,
                "earnings_growth": 0.11,
                "pe_ratio": 31.0,
                "forward_pe": 27.0,
                "peg_ratio": 2.1,
                "price_to_book": 45.0,
                "roe": 1.45,
                "roa": 0.24,
                "debt_to_equity": 135.0,
                "profit_margin": 0.27,
                "free_cashflow": 100_000_000_000,
                "exchange": "NMS",
            },
            "sector_rotation": {"sector": "Technology", "score": 0.75},
            "backtest": {"score": 0.72},
        },
    }


def complete_snapshot():
    return {
        "currentPrice": 101.25,
        "market_data_sources": ["alpaca_latest_quote", "reused_yfinance_info"],
        "provider_status": {"alpaca": "success", "yfinance": "reused"},
        "provider_errors": [],
        "data_quality": {"status": "complete", "missing_fields": []},
    }


def test_builds_complete_bundle_and_reuses_existing_fundamental_values(monkeypatch):
    captured = {}

    def fake_snapshot(symbol, exchange, yfinance_info):
        captured.update(
            symbol=symbol,
            exchange=exchange,
            yfinance_info=yfinance_info,
        )
        return complete_snapshot()

    monkeypatch.setattr(enrichment, "get_market_snapshot", fake_snapshot)
    bundle = enrichment.build_candidate_data_bundle("AAPL", scanner_details())

    assert bundle["schema_version"] == "scanner-data-bundle.v1"
    assert bundle["data_quality"]["status"] == "complete"
    assert bundle["data_quality"]["coverage_ratio"] == 1.0
    assert bundle["data_quality"]["missing_components"] == []
    assert "tradingview" in bundle["sources"]
    assert "alpaca_latest_quote" in bundle["sources"]
    assert "yfinance_fundamentals" in bundle["sources"]
    assert captured["symbol"] == "AAPL"
    assert captured["exchange"] == "NASDAQ"
    assert captured["yfinance_info"]["marketCap"] == 3_000_000_000_000
    assert captured["yfinance_info"]["returnOnAssets"] == 0.24
    assert captured["yfinance_info"]["currentPrice"] == 100.0


def test_enriches_scanner_v5_metadata_without_mutating_source(monkeypatch):
    monkeypatch.setattr(
        enrichment,
        "get_market_snapshot",
        lambda symbol, exchange, yfinance_info: complete_snapshot(),
    )
    original = {"details": scanner_details()}

    result = enrichment.enrich_candidate_metadata("AAPL", original)

    assert "data_bundle" not in original["details"]
    assert result is not original
    assert result["details"]["data_bundle"]["symbol"] == "AAPL"


def test_skips_generic_candidate_details_to_avoid_provider_side_effects(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("provider must not be called for non-scanner-v5 details")

    monkeypatch.setattr(enrichment, "get_market_snapshot", unexpected)
    metadata = {"details": {"source": "fallback"}}

    assert enrichment.enrich_candidate_metadata("AAPL", metadata) is metadata


def test_provider_failure_is_reported_without_dropping_candidate(monkeypatch):
    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(enrichment, "get_market_snapshot", fail_snapshot)
    result = enrichment.enrich_candidate_metadata(
        "AAPL",
        {"details": scanner_details()},
    )

    bundle = result["details"]["data_bundle"]
    assert bundle["data_quality"]["status"] == "partial"
    assert bundle["data_quality"]["missing_components"] == ["market"]
    assert bundle["data_quality"]["market_provider_errors"][0]["provider"] == "enrichment"
