from app.data_sources import market_data


class Quote:
    ask_price = 101.25
    bid_price = 101.0
    ask_size = 15
    bid_size = 12
    timestamp = "2026-08-15T08:00:00Z"


class Client:
    def get_stock_latest_quote(self, request):
        return {"AAPL": Quote()}


def enable_alpaca(monkeypatch):
    monkeypatch.setattr(market_data, "_alpaca_configured", lambda: True)
    monkeypatch.setattr(market_data, "_alpaca_client", lambda: Client())


def test_reuses_existing_yfinance_info_and_accepts_partial_valuation(monkeypatch):
    enable_alpaca(monkeypatch)

    def unexpected_ticker(symbol):
        raise AssertionError("yfinance Ticker must not be called when info is reused")

    monkeypatch.setattr(market_data.yf, "Ticker", unexpected_ticker)

    result = market_data.get_market_data(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "currentPrice": 99.5,
            "trailingPE": 24.0,
            "pegRatio": None,
            "priceToBook": None,
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
        },
    )

    assert result is not None
    assert result["currentPrice"] == 101.25
    assert result["field_sources"]["currentPrice"] == "alpaca_latest_quote"
    assert result["valuation_metric_count"] == 1
    assert result["valuation_data_complete"] is False
    assert result["market_data_sources"] == [
        "alpaca_latest_quote",
        "reused_yfinance_info",
    ]


def test_rejects_symbol_when_all_core_valuation_metrics_are_missing(monkeypatch):
    enable_alpaca(monkeypatch)

    result = market_data.get_market_data(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
        },
    )

    assert result is None


def test_market_snapshot_reports_complete_provider_data_and_quality(monkeypatch):
    enable_alpaca(monkeypatch)

    snapshot = market_data.get_market_snapshot(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "currentPrice": 99.5,
            "marketCap": 3_000_000_000_000,
            "averageVolume": 55_000_000,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "trailingPE": 31.0,
            "forwardPE": 27.0,
            "pegRatio": 2.1,
            "priceToBook": 45.0,
            "revenueGrowth": 0.08,
            "earningsGrowth": 0.11,
            "returnOnEquity": 1.45,
            "returnOnAssets": 0.24,
            "debtToEquity": 135.0,
            "profitMargins": 0.27,
            "freeCashflow": 100_000_000_000,
        },
    )

    assert snapshot["currentPrice"] == 101.25
    assert snapshot["alpacaAskPrice"] == 101.25
    assert snapshot["alpacaBidPrice"] == 101.0
    assert snapshot["alpacaMidpoint"] == 101.125
    assert snapshot["provider_status"] == {"alpaca": "success", "yfinance": "reused"}
    assert snapshot["field_sources"]["currentPrice"] == "alpaca_latest_quote"
    assert snapshot["data_quality"]["status"] == "complete"
    assert snapshot["data_quality"]["coverage_ratio"] == 1.0
    assert snapshot["data_quality"]["missing_fields"] == []


def test_market_snapshot_skips_unconfigured_alpaca_without_losing_yfinance(monkeypatch):
    monkeypatch.setattr(market_data, "_alpaca_configured", lambda: False)

    def unexpected_client():
        raise AssertionError("Alpaca client must not be created without credentials")

    monkeypatch.setattr(market_data, "_alpaca_client", unexpected_client)

    snapshot = market_data.get_market_snapshot(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "currentPrice": 99.5,
            "marketCap": 3_000_000_000_000,
            "averageVolume": 55_000_000,
            "trailingPE": 31.0,
        },
    )

    assert snapshot["currentPrice"] == 99.5
    assert snapshot["provider_status"]["alpaca"] == "not_configured"
    assert snapshot["provider_status"]["yfinance"] == "reused"
    assert snapshot["market_data_sources"] == ["reused_yfinance_info"]
