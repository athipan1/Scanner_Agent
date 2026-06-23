from app.services import fundamental_discovery


def test_cash_like_symbols_are_not_discoverable():
    for symbol in ["CASH", "USD", "USDT", "USDC", ""]:
        assert fundamental_discovery._is_discoverable_stock_symbol(symbol) is False

    assert fundamental_discovery._is_discoverable_stock_symbol("ACGL") is True
    assert fundamental_discovery._is_discoverable_stock_symbol("AAPL") is True


def test_build_universe_filters_cash_like_symbols(monkeypatch):
    monkeypatch.setattr(fundamental_discovery, "load_sp500_symbols", lambda: ["AAPL", "CASH"])
    monkeypatch.setattr(fundamental_discovery, "load_nasdaq100_symbols", lambda: ["MSFT", "USD"])
    monkeypatch.setattr(fundamental_discovery, "load_nasdaq_listed_symbols", lambda: ["ACGL", "USDT", "USDC"])

    universe = fundamental_discovery.build_us_fundamental_universe(max_universe=100)

    assert universe["symbols"] == ["AAPL", "MSFT", "ACGL"]
    assert universe["sources"]["excluded_non_tradable_symbol_count"] == 4
