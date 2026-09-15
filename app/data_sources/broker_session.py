"""Read-only Paper clock authority; quote/provider states cannot open a session."""

import json
import re
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen

from app.config import settings

CLOCK_URL = "https://paper-api.alpaca.markets/v2/clock"
MAX_CLOCK_AGE_SECONDS = 30
_lock = Lock()
_cached = None
_cached_at = 0.0


def read_broker_clock() -> dict:
    """Cache for at most five seconds; validation also checks session boundaries."""
    global _cached, _cached_at
    with _lock:
        if _cached is not None and monotonic() - _cached_at < 5:
            return {**_cached, "cache_hit": True}
        try:
            request = Request(CLOCK_URL, headers={
                "APCA-API-KEY-ID": settings.APCA_API_KEY_ID,
                "APCA-API-SECRET-KEY": settings.APCA_API_SECRET_KEY,
            })
            with urlopen(request, timeout=3) as response:
                clock = json.load(response)
            if not isinstance(clock, dict):
                raise TypeError("clock must be an object")
            result = {key: clock.get(key) for key in
                      ("timestamp", "is_open", "next_open", "next_close")}
            result.update(source="alpaca_paper_clock", cache_hit=False,
                          fetched_at=datetime.now(timezone.utc).isoformat())
            _cached, _cached_at = result, monotonic()
            return dict(result)
        except (OSError, ValueError, TypeError) as exc:
            # Never return stale authority or include URLs/credentials in errors.
            return {"source": "alpaca_paper_clock", "error": type(exc).__name__}


def _timestamp(value):
    # Alpaca emits RFC3339 nanoseconds; Python 3.9's fromisoformat only
    # supports 3/6 fractional digits. Normalize precision, never timezone.
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})",
        value,
    )
    if not match:
        return None
    whole, fraction, offset = match.groups()
    normalized = whole + ("." + fraction[:6].ljust(6, "0") if fraction else "")
    try:
        parsed = datetime.fromisoformat(normalized + offset.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def validate_broker_clock(clock: dict, observed: datetime) -> dict:
    clock = clock if isinstance(clock, dict) else {}
    observed = _timestamp(observed)
    timestamp = _timestamp(clock.get("timestamp"))
    age = (observed - timestamp).total_seconds() if timestamp and observed else None
    is_open = clock.get("is_open")
    next_open = _timestamp(clock.get("next_open"))
    next_close = _timestamp(clock.get("next_close"))
    boundary = next_close if is_open is True else next_open
    ordered = (next_close < next_open if is_open is True else next_open < next_close) if next_open and next_close else False
    valid = (clock.get("source") == "alpaca_paper_clock"
             and type(is_open) is bool and age is not None
             and -2 <= age <= MAX_CLOCK_AGE_SECONDS
             and ordered and boundary is not None and boundary > observed
             and not clock.get("error"))
    return {**clock, "valid": valid, "age_seconds": age,
            "next_session_boundary": boundary.isoformat() if boundary else None,
            "max_age_seconds": MAX_CLOCK_AGE_SECONDS,
            "rejection_code": None if valid else "BROKER_SESSION_UNVERIFIED"}
