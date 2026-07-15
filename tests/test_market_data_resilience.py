from app.data_sources import market_data


class Quote:
    ask_price = 101.25
    bid_price = 101.0


class Client:
    def get_stock_latest_quote(self, request):
        return {"AAPL": Quote()}


def test_reuses_existing_yfinance_info_and_accepts_partial_valuation(monkeypatch):
    monkeypatch.setattr(market_data, "_alpaca_client", lambda: Client())

    def unexpected_ticker(symbol):
        raise AssertionError("yfinance Ticker must not be called when info is reused")

    monkeypatch.setattr(market_data.yf, "Ticker", unexpected_ticker)

    result = market_data.get_market_data(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "trailingPE": 24.0,
            "pegRatio": None,
            "priceToBook": None,
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
        },
    )

    assert result is not None
    assert result["currentPrice"] == 101.25
    assert result["valuation_metric_count"] == 1
    assert result["valuation_data_complete"] is False
    assert result["market_data_sources"] == [
        "alpaca_latest_quote",
        "reused_yfinance_info",
    ]


def test_rejects_symbol_when_all_core_valuation_metrics_are_missing(monkeypatch):
    monkeypatch.setattr(market_data, "_alpaca_client", lambda: Client())

    result = market_data.get_market_data(
        "AAPL",
        "NASDAQ",
        yfinance_info={
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
        },
    )

    assert result is None
