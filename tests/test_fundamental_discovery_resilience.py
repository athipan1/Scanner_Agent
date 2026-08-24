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


def test_discovery_universe_stays_degraded_while_using_healthy_listed_fill(monkeypatch):
    monkeypatch.setattr(fundamental_discovery, "load_sp500_symbols", lambda: ["MSFT"])
    monkeypatch.setattr(fundamental_discovery, "load_nasdaq100_symbols", lambda: ["NVDA"])
    monkeypatch.setattr(
        fundamental_discovery,
        "load_nasdaq_listed_symbols",
        lambda: ["AA", "AB", "BA", "BB", "CA", "CB"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "get_universe_source_status",
        lambda: {
            "sp500": {
                "source": "static_large_cap_priority_fallback",
                "fallback_used": True,
                "effective_count": 1,
                "error": "RuntimeError: benchmark page unavailable",
            },
            "nasdaq100": {
                "source": "static_growth_priority_fallback",
                "fallback_used": True,
                "effective_count": 1,
                "error": "RuntimeError: benchmark page unavailable",
            },
            "nasdaq_listed": {
                "source": "nasdaq_trader",
                "fallback_used": False,
                "effective_count": 6,
                "error": None,
            },
        },
    )

    result = fundamental_discovery.build_us_fundamental_universe(max_universe=7)

    assert result["symbols"] == ["MSFT", "NVDA", "AA", "BA", "CA", "AB", "BB"]
    assert result["sources"]["sp500_fallback_used"] is True
    assert result["sources"]["nasdaq100_fallback_used"] is True
    assert result["sources"]["benchmark_sources_complete"] is False
    assert result["sources"]["universe_degraded"] is True
    assert result["sources"]["broad_listed_fill_enabled"] is True
    assert result["sources"]["universe_degraded_reasons"] == [
        "sp500_static_priority_fallback",
        "nasdaq100_static_priority_fallback",
    ]
    assert result["sources"]["selection_order"] == (
        "degraded_priority_then_round_robin_listed_fill"
    )
    assert result["sources"]["selected_initial_coverage"] == [
        "A",
        "B",
        "C",
        "M",
        "N",
    ]


def test_discovery_universe_uses_broad_fill_when_benchmarks_are_healthy(
    monkeypatch,
):
    monkeypatch.setattr(
        fundamental_discovery,
        "load_sp500_symbols",
        lambda: ["MSFT"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "load_nasdaq100_symbols",
        lambda: ["NVDA"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "load_nasdaq_listed_symbols",
        lambda: ["AA", "AB", "BA", "BB", "CA", "CB"],
    )
    monkeypatch.setattr(
        fundamental_discovery,
        "get_universe_source_status",
        lambda: {
            "sp500": {
                "source": "wikipedia_live",
                "fallback_used": False,
                "effective_count": 1,
                "error": None,
            },
            "nasdaq100": {
                "source": "wikipedia_live",
                "fallback_used": False,
                "effective_count": 1,
                "error": None,
            },
            "nasdaq_listed": {
                "source": "nasdaq_trader",
                "fallback_used": False,
                "effective_count": 6,
                "error": None,
            },
        },
    )

    result = fundamental_discovery.build_us_fundamental_universe(max_universe=7)

    assert result["symbols"] == ["MSFT", "NVDA", "AA", "BA", "CA", "AB", "BB"]
    assert result["sources"]["benchmark_sources_complete"] is True
    assert result["sources"]["universe_degraded"] is False
    assert result["sources"]["broad_listed_fill_enabled"] is True
    assert result["sources"]["selection_order"] == (
        "large_cap_priority_then_round_robin_initial"
    )


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
    assert metadata["provider_worker_cap"] == 4


def test_discovery_reduces_provider_workers_when_universe_is_degraded(monkeypatch):
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
        lambda max_universe: {
            "symbols": [],
            "sources": {"universe_degraded": True},
        },
    )
    monkeypatch.setattr(fundamental_discovery, "ThreadPoolExecutor", RecordingExecutor)

    candidates, errors, metadata = fundamental_discovery.discover_best_fundamentals(
        max_universe=1000,
        top_n=10,
        max_workers=20,
    )

    assert candidates == []
    assert errors == []
    assert observed["max_workers"] == 2
    assert metadata["effective_max_workers"] == 2
    assert metadata["provider_worker_cap"] == 2
