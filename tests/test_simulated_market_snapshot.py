from __future__ import annotations

import pytest

from app.data_sources import market_data


def _enable_simulated_market(monkeypatch):
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_ENABLED", "true")
    monkeypatch.setattr(market_data.settings, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(market_data.settings, "SCANNER_DEV_MODE", True)


def test_simulated_snapshot_short_circuits_all_market_providers(monkeypatch):
    _enable_simulated_market(monkeypatch)

    def provider_call_forbidden(*args, **kwargs):
        raise AssertionError("provider call must be bypassed in simulated market mode")

    monkeypatch.setattr(market_data, "_alpaca_configured", provider_call_forbidden)
    monkeypatch.setattr(market_data.yf, "Ticker", provider_call_forbidden)
    monkeypatch.setattr(market_data, "_yfinance_execution_history", provider_call_forbidden)

    snapshot = market_data.get_market_snapshot(
        "AAPL",
        exchange="NASDAQ",
        yfinance_info={
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "trailingPE": 30.0,
            "pegRatio": 2.0,
            "priceToBook": 45.0,
        },
        include_execution_history=True,
    )

    assert snapshot["symbol"] == "AAPL"
    assert snapshot["quoteQualityStatus"] == "fresh"
    assert snapshot["usMarketSession"] == "regular"
    assert snapshot["usMarketOpen"] is True
    assert snapshot["alpacaQuoteAgeSeconds"] == 0.0
    assert snapshot["alpacaSpreadBps"] == 8.0
    assert snapshot["historicalAtrPct"] == 0.02
    assert snapshot["historicalAtr14"] == pytest.approx(2.0)
    assert snapshot["averageVolume"] == 2_500_000.0
    assert snapshot["regularMarketVolume"] == 3_000_000.0
    assert snapshot["provider_status"]["alpaca"] == "bypassed"
    assert snapshot["provider_status"]["yfinance"] == "reused"
    assert snapshot["provider_status"]["yfinance_history"] == "bypassed"
    assert snapshot["provider_errors"] == []
    assert snapshot["simulatedMarket"] == {
        "enabled": True,
        "fixture": "open_us_regular_session",
        "broker_orders_allowed": False,
        "provider_calls_bypassed": True,
    }
    assert snapshot["valuation_metric_count"] == 3
    assert snapshot["data_quality"]["critical_data_available"] is True


def test_simulated_snapshot_uses_deterministic_overrides(monkeypatch):
    _enable_simulated_market(monkeypatch)
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_PRICE", "250")
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_SPREAD_BPS", "10")
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_AVERAGE_VOLUME", "4000000")
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_REGULAR_VOLUME", "6000000")
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_ATR_PCT", "0.03")

    snapshot = market_data.get_market_snapshot(
        "NVDA",
        exchange="NASDAQ",
        include_execution_history=True,
    )

    assert snapshot["currentPrice"] == 250.0
    assert snapshot["alpacaSpreadBps"] == 10.0
    assert snapshot["averageVolume"] == 4_000_000.0
    assert snapshot["regularMarketVolume"] == 6_000_000.0
    assert snapshot["historicalAtrPct"] == 0.03
    assert snapshot["historicalAtr14"] == pytest.approx(7.5)
    assert snapshot["historyBarCount"] == 45


def test_simulated_snapshot_rejected_outside_paper_mode(monkeypatch):
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_ENABLED", "true")
    monkeypatch.setattr(market_data.settings, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(market_data.settings, "SCANNER_DEV_MODE", True)

    with pytest.raises(RuntimeError, match="TRADING_MODE=PAPER"):
        market_data.get_market_snapshot("AAPL", exchange="NASDAQ")


def test_simulated_snapshot_rejected_without_dev_mode(monkeypatch):
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_ENABLED", "true")
    monkeypatch.setattr(market_data.settings, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(market_data.settings, "SCANNER_DEV_MODE", False)

    with pytest.raises(RuntimeError, match="SCANNER_DEV_MODE=true"):
        market_data.get_market_snapshot("AAPL", exchange="NASDAQ")


def test_simulated_snapshot_rejected_for_non_us_exchange(monkeypatch):
    _enable_simulated_market(monkeypatch)

    with pytest.raises(RuntimeError, match="US equity exchanges only"):
        market_data.get_market_snapshot("PTT", exchange="SET")


def test_simulated_snapshot_rejects_unsafe_spread_override(monkeypatch):
    _enable_simulated_market(monkeypatch)
    monkeypatch.setenv("SCANNER_SIMULATED_MARKET_SPREAD_BPS", "500")

    with pytest.raises(RuntimeError, match="SCANNER_SIMULATED_MARKET_SPREAD_BPS"):
        market_data.get_market_snapshot("AAPL", exchange="NASDAQ")
