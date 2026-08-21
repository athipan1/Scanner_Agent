from datetime import datetime, timezone

from app.data_sources.market_data import classify_quote_quality


def test_regular_session_recent_quote_is_fresh():
    observed_at = datetime(2026, 8, 20, 15, 0, 0, tzinfo=timezone.utc)
    result = classify_quote_quality(
        requested_exchange="NASDAQ",
        market_state="REGULAR",
        quote_timestamp=datetime(2026, 8, 20, 14, 59, 30, tzinfo=timezone.utc),
        observed_at=observed_at,
        stale_after_seconds=300,
    )

    assert result["status"] == "fresh"
    assert result["market_session"] == "regular"
    assert result["market_open"] is True
    assert result["quote_is_fresh"] is True
    assert result["quote_age_seconds"] == 30.0


def test_regular_session_old_quote_is_stale_quote():
    observed_at = datetime(2026, 8, 20, 15, 0, 0, tzinfo=timezone.utc)
    result = classify_quote_quality(
        requested_exchange="NYSE",
        market_state="REGULAR",
        quote_timestamp=datetime(2026, 8, 20, 14, 50, 0, tzinfo=timezone.utc),
        observed_at=observed_at,
        stale_after_seconds=300,
    )

    assert result["status"] == "stale_quote"
    assert result["market_open"] is True
    assert result["quote_is_fresh"] is False


def test_after_hours_quote_is_market_closed_not_provider_failure():
    observed_at = datetime(2026, 8, 20, 22, 0, 0, tzinfo=timezone.utc)
    result = classify_quote_quality(
        requested_exchange="NASDAQ",
        market_state="POST",
        quote_timestamp=datetime(2026, 8, 20, 21, 59, 55, tzinfo=timezone.utc),
        observed_at=observed_at,
    )

    assert result["status"] == "market_closed"
    assert result["market_session"] == "after_hours"
    assert result["market_open"] is False


def test_provider_closed_state_wins_over_weekday_clock_for_holiday_safety():
    observed_at = datetime(2026, 12, 25, 15, 0, 0, tzinfo=timezone.utc)
    result = classify_quote_quality(
        requested_exchange="NYSE",
        market_state="CLOSED",
        quote_timestamp=datetime(2026, 12, 24, 20, 59, 0, tzinfo=timezone.utc),
        observed_at=observed_at,
    )

    assert result["status"] == "market_closed"
    assert result["session_source"] == "provider_market_state"


def test_non_us_exchange_is_not_applicable():
    result = classify_quote_quality(
        requested_exchange="SET",
        observed_at=datetime(2026, 8, 20, 15, 0, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "not_applicable"
    assert result["market_session"] == "not_applicable"
