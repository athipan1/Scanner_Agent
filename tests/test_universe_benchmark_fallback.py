import pandas as pd

from app import universe
from app.services import fundamental_discovery


def _clear_universe_caches():
    universe.load_nasdaq_listed_symbols.cache_clear()
    universe.load_other_listed_symbols.cache_clear()
    universe.load_sp500_symbols.cache_clear()
    universe.load_nasdaq100_symbols.cache_clear()
    universe.load_us_listed_universe.cache_clear()
    universe.load_us_phase1_universe.cache_clear()
    universe._SOURCE_STATUS.clear()


def test_benchmark_page_failure_keeps_effective_priority_and_broad_listed_fill(
    monkeypatch,
):
    _clear_universe_caches()

    def fail_read_html(*args, **kwargs):
        raise RuntimeError("benchmark page unavailable")

    listed = pd.DataFrame(
        {
            "Symbol": [f"X{i:03d}" for i in range(250)],
            "Security Name": [f"Example Common Stock {i}" for i in range(250)],
            "ETF": ["N"] * 250,
            "Test Issue": ["N"] * 250,
            "Financial Status": ["N"] * 250,
            "Market Category": ["Q"] * 250,
        }
    )

    monkeypatch.setattr(universe.pd, "read_html", fail_read_html)
    monkeypatch.setattr(
        universe,
        "_read_nasdaq_trader_file",
        lambda file_name: listed if file_name == "nasdaqlisted.txt" else pd.DataFrame(),
    )

    result = fundamental_discovery.build_us_fundamental_universe(max_universe=200)
    status = universe.get_universe_source_status()

    assert status["sp500"]["fallback_used"] is True
    assert status["sp500"]["source"] == "static_large_cap_priority_fallback"
    assert status["nasdaq100"]["fallback_used"] is True
    assert status["nasdaq100"]["source"] == "static_growth_priority_fallback"
    assert status["nasdaq_listed"]["fallback_used"] is False
    assert result["sources"]["broad_listed_fill_enabled"] is True
    assert result["sources"]["selected_universe_count"] == 200
    assert any(symbol.startswith("X") for symbol in result["symbols"])

    _clear_universe_caches()


def test_partial_benchmark_tables_do_not_masquerade_as_live_membership(monkeypatch):
    _clear_universe_caches()

    monkeypatch.setattr(
        universe.pd,
        "read_html",
        lambda *args, **kwargs: [pd.DataFrame({"Symbol": ["AAPL", "MSFT"]})],
    )

    sp500 = universe.load_sp500_symbols()
    status = universe.get_universe_source_status()["sp500"]

    assert sp500 == universe.US_LARGE_CAP_FALLBACK
    assert status["fallback_used"] is True
    assert "partial benchmark membership" in status["error"]

    _clear_universe_caches()
