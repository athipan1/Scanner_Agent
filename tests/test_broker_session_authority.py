from datetime import datetime, timedelta, timezone

import pytest

from app.data_sources import market_data
from app.data_sources.broker_session import validate_broker_clock

NOW = datetime(2026, 9, 9, 14, 52, 35, tzinfo=timezone.utc)


def clock(**changes):
    return {"source": "alpaca_paper_clock", "timestamp": NOW.isoformat(),
            "is_open": True, "next_close": "2026-09-09T20:00:00Z",
            "next_open": "2026-09-10T13:30:00Z", **changes}


def classify(**changes):
    return market_data.classify_quote_quality(**{
        "requested_exchange": "NASDAQ", "market_state": "PRE",
        "quote_timestamp": NOW - timedelta(seconds=30), "observed_at": NOW,
        "broker_clock": clock(), "require_broker_clock": True, **changes,
    })


@pytest.mark.parametrize("symbol,age,exchange", [
    ("WDC", 3.729, "NMS"), ("JFIN", 76.152, "NMS"), ("QTTB", 21.720, "NCM"),
])
def test_cached_provider_premarket_does_not_override_fresh_broker(symbol, age, exchange):
    result = classify(provider_exchange=exchange,
                      quote_timestamp=NOW - timedelta(seconds=age))
    assert result["market_session"] == "regular"
    assert result["market_open"] is True
    assert result["status"] == "fresh"
    assert result["provider_market_state"] == "PRE"
    assert result["provider_session_mismatch"] is True
    assert result["observed_at_eastern"].endswith("-04:00")


@pytest.mark.parametrize("change", [
    {"timestamp": (NOW - timedelta(seconds=31)).isoformat()},
    {"timestamp": (NOW + timedelta(seconds=3)).isoformat()},
    {"timestamp": "2026-09-09T14:52:35"},
    {"is_open": "true"}, {"is_open": 1}, {"timestamp": None},
    {"next_close": NOW.isoformat()}, {"next_close": "invalid"},
    {"error": "TimeoutError"}, {"source": "weekday_clock"},
])
def test_invalid_clock_never_uses_provider_open_fallback(change):
    result = classify(broker_clock=clock(**change), market_state="REGULAR")
    assert result["market_open"] is None
    assert result["status"] == "session_unverified"
    assert result["quote_is_fresh"] is False


def test_missing_clock_fails_closed():
    assert classify(broker_clock={})["status"] == "session_unverified"


def test_holiday_or_early_close_overrules_nominal_weekday_hours():
    result = classify(broker_clock=clock(is_open=False,
        next_close="2026-09-10T20:00:00Z"), market_state="REGULAR")
    assert result["market_session"] == "closed"
    assert result["market_open"] is False
    assert result["status"] == "market_closed"


def test_open_clock_does_not_relax_quote_age():
    result = classify(quote_timestamp=NOW - timedelta(seconds=301))
    assert result["market_open"] is True
    assert result["status"] == "stale_quote"


def test_dst_and_utc_timestamps_represent_the_same_instant():
    winter = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
    result = market_data.classify_quote_quality(
        requested_exchange="US", observed_at=winter, quote_timestamp=winter,
        broker_clock=clock(timestamp="2026-12-01T10:00:00-05:00",
                           next_close="2026-12-01T16:00:00-05:00",
                           next_open="2026-12-02T09:30:00-05:00"),
        require_broker_clock=True,
    )
    assert result["status"] == "fresh"
    assert result["observed_at_eastern"].endswith("-05:00")


def test_closed_cached_clock_expires_at_next_open_boundary():
    result = validate_broker_clock(clock(is_open=False, next_open=NOW.isoformat()), NOW)
    assert result["valid"] is False


@pytest.mark.parametrize("bad", [None, [], "open", 1])
def test_malformed_authority_fails_closed(bad):
    assert validate_broker_clock(bad, NOW)["valid"] is False


@pytest.mark.parametrize("change", [
    {"next_open": None}, {"next_open": "invalid"},
    {"next_open": NOW.isoformat()},
    {"next_close": "2026-09-11T20:00:00Z"},
])
def test_incomplete_or_inconsistent_clock_boundary_fails_closed(change):
    assert classify(broker_clock=clock(**change))["status"] == "session_unverified"


def test_default_classifier_requires_authority_even_when_provider_claims_open():
    result = market_data.classify_quote_quality(requested_exchange="NASDAQ",
        market_state="REGULAR", quote_timestamp=NOW, observed_at=NOW)
    assert result["status"] == "session_unverified"


def test_unverified_clock_cannot_qualify_opportunity():
    from app.services.opportunity_profile import build_opportunity_profile
    result = build_opportunity_profile({"market_snapshot": {
        "currentPrice": 100, "averageVolume": 1e7,
        "quoteQualityStatus": "session_unverified", "usMarketSession": "unverified",
        "alpacaBidPrice": 99.99, "alpacaAskPrice": 100.01,
    }})
    assert result["status"] != "qualified"
    assert "broker_session_unverified" in result["reasons"]


def test_clock_reader_cache_is_short_and_fetch_failure_never_returns_stale(monkeypatch):
    import io
    import json
    from app.data_sources import broker_session
    calls = []
    now = [100.0]
    def fetch(request, timeout):
        calls.append(request.full_url)
        return io.StringIO(json.dumps(clock()))
    monkeypatch.setattr(broker_session, "_cached", None)
    monkeypatch.setattr(broker_session, "_cached_at", 0)
    monkeypatch.setattr(broker_session, "monotonic", lambda: now[0])
    monkeypatch.setattr(broker_session, "urlopen", fetch)
    first = broker_session.read_broker_clock()
    second = broker_session.read_broker_clock()
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert calls == ["https://paper-api.alpaca.markets/v2/clock"]
    now[0] += 6
    def unavailable(*args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(broker_session, "urlopen", unavailable)
    failed = broker_session.read_broker_clock()
    assert "timestamp" not in failed and "is_open" not in failed
    assert failed["error"] == "OSError"


@pytest.mark.parametrize("fraction", ["1", "19", "193", "1931", "19313", "193130", "1931309", "19313096", "193130963"])
def test_alpaca_fractional_precision_on_runtime_python(fraction):
    observed = datetime(2026, 9, 15, 9, 59, 13, tzinfo=timezone.utc)
    result = validate_broker_clock(clock(
        timestamp=f"2026-09-15T05:59:12.{fraction}-04:00", is_open=False,
        next_open="2026-09-15T09:30:00-04:00",
        next_close="2026-09-15T16:00:00-04:00",
    ), observed)
    assert result["valid"] is True
    assert 0 < result["age_seconds"] < 1


@pytest.mark.parametrize("timestamp", [
    "2026-09-09T14:52:35.123456789",  # timezone is mandatory
    "2026-09-09T14:52:35.1234567890Z",  # malformed precision
    "2026-09-09T14:52:35.123456789+25:00",
    "2026-09-09T14:52:35.badZ", "2026-09-09T14:52:35Zjunk",
])
def test_nanosecond_support_does_not_accept_malformed_authority(timestamp):
    assert validate_broker_clock(clock(timestamp=timestamp), NOW)["valid"] is False
