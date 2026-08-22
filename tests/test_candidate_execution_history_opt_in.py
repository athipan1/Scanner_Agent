from __future__ import annotations

from app.services import candidate_data_enrichment


def test_ranked_candidate_requests_execution_history(monkeypatch):
    calls = []

    def fake_snapshot(symbol, exchange="SET", yfinance_info=None, *, include_execution_history=False):
        calls.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "include_execution_history": include_execution_history,
            }
        )
        return {
            "currentPrice": 100.0,
            "averageVolume": 1_000_000,
            "historicalAtrPct": 0.02,
            "regularMarketVolume": 1_100_000,
            "alpacaBidPrice": 99.99,
            "alpacaAskPrice": 100.01,
            "alpacaSpreadBps": 2.0,
            "alpacaQuoteTimestamp": "2026-08-21T15:00:00+00:00",
            "alpacaQuoteAgeSeconds": 10.0,
            "quoteQualityStatus": "fresh",
            "usMarketSession": "regular",
            "usMarketOpen": True,
            "quote_quality": {
                "status": "fresh",
                "market_session": "regular",
                "market_open": True,
                "quote_age_seconds": 10.0,
            },
            "market_data_sources": ["alpaca_latest_quote", "yfinance_execution_history"],
            "provider_status": {"alpaca": "success", "yfinance_history": "success"},
            "provider_errors": [],
            "data_quality": {"status": "partial", "coverage_ratio": 0.7, "missing_fields": []},
        }

    monkeypatch.setattr(candidate_data_enrichment, "get_market_snapshot", fake_snapshot)

    details = {
        "resolved_exchange": "NASDAQ",
        "scanner_v50": {
            "indicator_values": {"close": 100.0, "atr": None},
            "market_rank": {
                "price": 100.0,
                "return_20d": 0.05,
                "return_60d": 0.10,
                "volume_ratio": 1.1,
                "trend_score": 0.8,
            },
            "fundamental": {"exchange": "NASDAQ", "market_cap": 3_000_000_000_000},
            "sector_rotation": {},
            "backtest": {},
        },
    }

    bundle = candidate_data_enrichment.build_candidate_data_bundle("AAPL", details)

    assert calls == [
        {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "include_execution_history": True,
        }
    ]
    profile = bundle["opportunity_profile"]
    assert profile["evidence_quality"]["atr_available"] is True
    assert profile["execution_context"]["atr_pct"] == 0.02
