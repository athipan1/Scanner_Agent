from __future__ import annotations

from app.data_sources import market_data
from app.services.opportunity_profile import build_opportunity_profile


class _FakeHistory:
    empty = False

    def iterrows(self):
        rows = []
        close = 100.0
        for index in range(20):
            row = {
                "High": close + 1.5,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1_000_000 + index * 10_000,
            }
            rows.append((index, row))
            close += 0.25
        return iter(rows)


class _FakeTicker:
    def history(self, **kwargs):
        assert kwargs["period"] == "45d"
        assert kwargs["interval"] == "1d"
        return _FakeHistory()


def test_execution_history_computes_atr_and_average_volume(monkeypatch):
    market_data._yfinance_execution_history.cache_clear()
    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: _FakeTicker())

    result = market_data._yfinance_execution_history("AAPL")

    assert result["historyBarCount"] == 20
    assert result["historicalAtr14"] > 0
    assert result["historicalAtrPct"] > 0
    assert result["historicalAverageVolume20d"] > 1_000_000


def test_opportunity_profile_uses_historical_atr_fallback():
    bundle = {
        "market_snapshot": {
            "currentPrice": 100.0,
            "averageVolume": 1_000_000,
            "regularMarketVolume": 1_200_000,
            "alpacaBidPrice": 99.99,
            "alpacaAskPrice": 100.01,
            "alpacaSpreadBps": 2.0,
            "alpacaQuoteTimestamp": "2026-08-21T14:00:00+00:00",
            "alpacaQuoteAgeSeconds": 10.0,
            "historicalAtrPct": 0.02,
            "quoteQualityStatus": "fresh",
            "usMarketSession": "regular",
            "usMarketOpen": True,
            "quote_quality": {
                "status": "fresh",
                "market_session": "regular",
                "market_open": True,
                "quote_age_seconds": 10.0,
            },
        },
        "technical": {"indicator_values": {}},
        "market_rank": {"trend_score": 0.80},
        "data_quality": {"coverage_ratio": 1.0},
    }

    profile = build_opportunity_profile(bundle)

    assert profile["execution_context"]["atr_pct"] == 0.02
    assert profile["execution_context"]["relative_volume"] == 1.2
    assert profile["evidence_quality"]["atr_available"] is True
    assert profile["evidence_quality"]["relative_volume_available"] is True
    assert profile["evidence_quality"]["spread_available"] is True
    assert profile["evidence_quality"]["quote_timestamp_available"] is True
    assert profile["evidence_quality"]["coverage_ratio"] == 1.0
    assert profile["workflow_status"] == "ready"
    assert profile["status"] == "qualified"
