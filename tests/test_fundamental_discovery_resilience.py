from app.models import ErrorDetail
from app.services import fundamental_discovery
from app.universe import diversify_symbols_by_initial


def test_diversified_symbols_round_robin_across_initials():
    symbols = ["AA", "AB", "AC", "BA", "BB", "CA", "CB", "CC"]

    assert diversify_symbols_by_initial(symbols) == [
        "AA",
        "BA",
        "CA",
        "AB",
        "BB",
        "CB",
        "AC",
        "CC",
    ]


def test_discovery_universe_uses_large_cap_fallback_and_diversified_fill(monkeypatch):
    monkeypatch.setattr(fundamental_discovery, "load_sp500_symbols", lambda: [])
    monkeypatch.setattr(fundamental_discovery, "load_nasdaq100_symbols", lambda: [])
    monkeypatch.setattr(
        fundamental_discovery,
        "load_nasdaq_listed_symbols",
        lambda: ["AA", "AB", "BA", "BB", "CA", "CB"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "US_LARGE_CAP_FALLBACK",
        ["MSFT"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "US_GROWTH_UNIVERSE",
        ["NVDA"],
    )

    result = fundamental_discovery.build_us_fundamental_universe(max_universe=7)

    assert result["symbols"] == ["MSFT", "NVDA", "AA", "BA", "CA", "AB", "BB"]
    assert result["sources"]["sp500_fallback_used"] is True
    assert result["sources"]["nasdaq100_fallback_used"] is True
    assert result["sources"]["selection_order"] == (
        "large_cap_priority_then_round_robin_initial"
    )
    assert result["sources"]["selected_initial_coverage"] == ["A", "B", "C", "M", "N"]


def test_error_diagnostics_classify_provider_and_data_failures():
    diagnostics = fundamental_discovery._error_diagnostics(
        [
            ErrorDetail(symbol="AAA", error="HTTP 429 Too Many Requests"),
            ErrorDetail(symbol="BBB", error="missing financial statements"),
            ErrorDetail(symbol="CCC", error="missing market data"),
            ErrorDetail(symbol="DDD", error="request timed out"),
        ]
    )

    assert diagnostics["error_categories"] == {
        "missing_financial_statements": 1,
        "missing_market_data": 1,
        "provider_rate_limited": 1,
        "provider_timeout": 1,
    }
    assert diagnostics["provider_pressure_detected"] is True
    assert diagnostics["error_samples"]["provider_rate_limited"][0]["symbol"] == "AAA"


def test_discovery_caps_provider_workers(monkeypatch):
    observed = {}

    class RecordingExecutor:
        def __init__(self, max_workers):
            observed["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, symbol, exchange):
            raise AssertionError("no symbols should be submitted")

    monkeypatch.setattr(
        fundamental_discovery,
        "build_us_fundamental_universe",
        lambda max_universe: {"symbols": [], "sources": {}},
    )
    monkeypatch.setattr(fundamental_discovery, "ThreadPoolExecutor", RecordingExecutor)

    candidates, errors, metadata = fundamental_discovery.discover_best_fundamentals(
        max_universe=1000,
        top_n=10,
        max_workers=20,
    )

    assert candidates == []
    assert errors == []
    assert observed["max_workers"] == 4
    assert metadata["requested_max_workers"] == 20
    assert metadata["effective_max_workers"] == 4
