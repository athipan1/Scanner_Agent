from __future__ import annotations

from app.models import ScannerCandidateContract, ScannerContractResult


def _fundamental_candidate(symbol: str = "BSX") -> ScannerCandidateContract:
    return ScannerCandidateContract(
        symbol=symbol,
        candidate_score=0.82,
        recommendation_hint="FUNDAMENTAL_TOP_10",
        exchange="NASDAQ",
        screener="america",
        raw_scores={
            "fundamental_score": 82.0,
            "quality_score": 85.0,
            "growth_score": 80.0,
            "valuation_score": 75.0,
        },
        metadata={
            "source": "real_market_fundamental_discovery",
            "data_bundle": {
                "schema_version": "scanner-data-bundle.v1",
                "symbol": symbol,
                "sources": ["yfinance_financial_statements", "alpaca_latest_quote"],
                "market_snapshot": {
                    "symbol": symbol,
                    "regularMarketPrice": 100.0,
                    "averageVolume": 3_000_000,
                    "marketCap": 50_000_000_000,
                },
                "financial_statements": {
                    "provider_status": "success",
                    "available_statements": ["annual_income_statement"],
                    "missing_statements": [],
                },
                "data_quality": {
                    "status": "complete",
                    "market": {"status": "complete"},
                    "financial_statements": {"status": "complete"},
                },
            },
        },
    )


def test_best_fundamentals_are_hydrated_before_lane_partition(monkeypatch):
    from app.services import production_enrichment

    monkeypatch.setattr(
        production_enrichment,
        "rank_market_symbols",
        lambda symbols: (
            list(symbols),
            {
                "BSX": {
                    "market_rank_score": 0.92,
                    "return_20d": 0.12,
                    "return_60d": 0.24,
                    "volume_ratio": 1.5,
                    "trend_score": 0.92,
                    "benchmark_symbol": "SPY",
                    "benchmark_return_20d": 0.04,
                    "benchmark_return_60d": 0.08,
                    "relative_return_20d": 0.08,
                    "relative_return_60d": 0.16,
                    "outperforming_benchmark": True,
                }
            },
        ),
    )
    monkeypatch.setattr(
        production_enrichment,
        "fetch_analysis",
        lambda symbol, screener, exchange: {
            "symbol": symbol,
            "exchange": "NYSE",
            "analysis": {"RECOMMENDATION": "BUY"},
            "indicators": {
                "close": 100.0,
                "RSI": 58.0,
                "MACD.macd": 2.0,
                "MACD.signal": 1.0,
                "SMA50": 94.0,
                "SMA200": 82.0,
                "volume": 4_500_000,
                "Volume MA": 3_000_000,
                "ATR": 2.0,
                "High.52W": 103.0,
            },
        },
    )
    monkeypatch.setattr(
        production_enrichment,
        "get_market_snapshot",
        lambda symbol, exchange, yfinance_info, include_execution_history: {
            "symbol": symbol,
            "currentPrice": 100.0,
            "regularMarketPrice": 100.0,
            "averageVolume": 3_000_000,
            "regularMarketVolume": 4_500_000,
            "marketCap": 50_000_000_000,
            "alpacaBidPrice": 99.99,
            "alpacaAskPrice": 100.0,
            "alpacaSpreadBps": 1.0001,
            "alpacaQuoteTimestamp": "2026-08-25T14:00:00+00:00",
            "alpacaQuoteAgeSeconds": 1.0,
            "quoteQualityStatus": "fresh_regular_session",
            "usMarketSession": "regular",
            "usMarketOpen": True,
            "historicalAtrPct": 0.02,
            "provider_status": {
                "alpaca": "success",
                "yfinance": "reused",
                "yfinance_history": "success",
            },
            "provider_errors": [],
        },
    )

    result = ScannerContractResult(
        scan_type="best_fundamentals",
        count=1,
        candidates=[_fundamental_candidate()],
    )

    assert len(result.production_candidates) == 1
    assert result.production_candidates[0].symbol == "BSX"
    assert result.lane_summary["production_count"] == 1
    assert result.lane_summary["production_enrichment"]["enriched_count"] == 1
    assert (
        result.lane_summary["production_enrichment"]["production_qualified_count"]
        == 1
    )

    bundle = result.candidates[0].metadata["data_bundle"]
    assert bundle["data_quality"]["analysis"]["coverage_ratio"] == 1.0
    assert bundle["opportunity_profile"]["status"] == "qualified"
    assert bundle["opportunity_profile"]["fail_closed"] is False
    assert bundle["opportunity_profile"]["opportunity_score"] >= 0.70
    assert bundle["candidate_score_inputs"]["technical"]["sma200"] == 82.0
    assert (
        bundle["candidate_score_inputs"]["market_strength"][
            "stronger_than_universe_proxy"
        ]
        is True
    )
    assert (
        result.candidates[0].metadata["production_enrichment"][
            "broker_order_authorized"
        ]
        is False
    )


def test_non_fundamental_contract_does_not_trigger_provider_enrichment(monkeypatch):
    from app.services import production_enrichment

    def unexpected_call(*args, **kwargs):
        raise AssertionError("provider enrichment must not run")

    monkeypatch.setattr(production_enrichment, "rank_market_symbols", unexpected_call)
    monkeypatch.setattr(production_enrichment, "fetch_analysis", unexpected_call)
    monkeypatch.setattr(production_enrichment, "get_market_snapshot", unexpected_call)

    candidate = ScannerCandidateContract(
        symbol="AAPL",
        candidate_score=0.80,
        recommendation_hint="WATCHLIST",
        metadata={"source": "technical_scan"},
    )
    result = ScannerContractResult(
        scan_type="candidate_discovery",
        count=1,
        candidates=[candidate],
    )

    assert result.lane_summary["production_count"] == 0
    assert result.lane_summary["blocked_count"] == 1
