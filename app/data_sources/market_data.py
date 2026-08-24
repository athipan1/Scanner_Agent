import logging
import math
import os
from datetime import datetime, time, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

import yfinance as yf
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from app.config import settings
from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)

_CORE_VALUATION_KEYS = ("trailingPE", "pegRatio", "priceToBook")

_INFO_FIELDS = (
    "marketCap",
    "enterpriseValue",
    "sector",
    "industry",
    "quoteType",
    "currency",
    "exchange",
    "marketState",
    "averageVolume",
    "averageVolume10days",
    "averageDailyVolume10Day",
    "regularMarketVolume",
    "trailingPE",
    "forwardPE",
    "pegRatio",
    "priceToBook",
    "revenueGrowth",
    "earningsGrowth",
    "returnOnEquity",
    "returnOnAssets",
    "debtToEquity",
    "profitMargins",
    "grossMargins",
    "operatingMargins",
    "freeCashflow",
    "operatingCashflow",
    "totalRevenue",
    "ebitda",
    "beta",
    "dividendYield",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "currentPrice",
    "regularMarketPrice",
    "previousClose",
)

_DATA_QUALITY_GROUPS = {
    "quote": ("currentPrice",),
    "liquidity": ("marketCap", "averageVolume"),
    "profile": ("sector", "industry"),
    "valuation": ("trailingPE", "forwardPE", "pegRatio", "priceToBook"),
    "growth": ("revenueGrowth", "earningsGrowth"),
    "quality": (
        "returnOnEquity",
        "returnOnAssets",
        "debtToEquity",
        "profitMargins",
        "freeCashflow",
    ),
}

_PLACEHOLDER_KEYS = {
    "",
    "YOUR_API_KEY",
    "YOUR_SECRET_KEY",
    "YOUR_APCA_API_KEY_ID",
    "YOUR_APCA_API_SECRET_KEY",
}

_US_EQUITY_EXCHANGES = {
    "AMEX",
    "ARCA",
    "BATS",
    "IEX",
    "NASDAQ",
    "NGM",
    "NMS",
    "NYSE",
    "NYQ",
    "PCX",
}
_US_EASTERN = ZoneInfo("America/New_York")
_US_REGULAR_OPEN = time(9, 30)
_US_REGULAR_CLOSE = time(16, 0)
_US_PREMARKET_OPEN = time(4, 0)
_US_AFTER_HOURS_CLOSE = time(20, 0)
DEFAULT_QUOTE_STALE_AFTER_SECONDS = 300
MAX_FUTURE_QUOTE_SKEW_SECONDS = 60
_SIMULATED_MARKET_ENV = "SCANNER_SIMULATED_MARKET_ENABLED"
_SIMULATED_MARKET_TRUE_VALUES = {"1", "true", "yes", "on"}
_SIMULATED_MARKET_DEFAULT_PRICE = 100.0
_SIMULATED_MARKET_DEFAULT_SPREAD_BPS = 8.0
_SIMULATED_MARKET_DEFAULT_AVERAGE_VOLUME = 2_500_000.0
_SIMULATED_MARKET_DEFAULT_REGULAR_VOLUME = 3_000_000.0
_SIMULATED_MARKET_DEFAULT_ATR_PCT = 0.02


@lru_cache(maxsize=1)
def _alpaca_client() -> StockHistoricalDataClient:
    """Reuse one thread-safe Alpaca data client instead of one client per symbol."""

    return StockHistoricalDataClient(
        api_key=settings.APCA_API_KEY_ID,
        secret_key=settings.APCA_API_SECRET_KEY,
    )


def _alpaca_configured() -> bool:
    key = str(settings.APCA_API_KEY_ID or "").strip()
    secret = str(settings.APCA_API_SECRET_KEY or "").strip()
    return key not in _PLACEHOLDER_KEYS and secret not in _PLACEHOLDER_KEYS


def _safe_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_price(*values: Any) -> Optional[float]:
    for value in values:
        price = _safe_number(value)
        if price is not None and price > 0:
            return price
    return None


@lru_cache(maxsize=512)
def _yfinance_execution_history(yf_symbol: str) -> Dict[str, Any]:
    """Return cached daily execution evidence for Scanner candidate enrichment.

    ATR is computed from true range over the latest 14 valid daily bars. This is a
    provider-backed fallback, not a synthetic volatility guess. Callers opt in so
    generic market snapshots that already reuse yfinance info keep their no-extra-
    provider-call contract.
    """

    try:
        history = yf.Ticker(yf_symbol).history(
            period="45d",
            interval="1d",
            auto_adjust=False,
        )
        if history is None or getattr(history, "empty", True):
            return {"_error": "empty_history"}

        true_ranges: list[float] = []
        closes: list[float] = []
        volumes: list[float] = []
        previous_close: Optional[float] = None
        for _, row in history.iterrows():
            high = _safe_number(row.get("High"))
            low = _safe_number(row.get("Low"))
            close = _safe_number(row.get("Close"))
            volume = _safe_number(row.get("Volume"))
            if high is None or low is None or close is None or close <= 0:
                continue
            true_range = high - low
            if previous_close is not None:
                true_range = max(
                    true_range,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            if true_range >= 0:
                true_ranges.append(true_range)
            closes.append(close)
            if volume is not None and volume >= 0:
                volumes.append(volume)
            previous_close = close

        if not closes:
            return {"_error": "history_has_no_valid_close"}

        result: Dict[str, Any] = {"historyBarCount": len(closes)}
        if len(true_ranges) >= 14:
            atr14 = sum(true_ranges[-14:]) / 14.0
            result["historicalAtr14"] = round(atr14, 8)
            result["historicalAtrPct"] = round(atr14 / closes[-1], 8)
        if volumes:
            recent_volumes = volumes[-20:]
            result["historicalAverageVolume20d"] = round(
                sum(recent_volumes) / len(recent_volumes),
                4,
            )
        return result
    except Exception as exc:
        logger.warning(
            "Error fetching execution history for %s from yfinance: %s",
            yf_symbol,
            exc,
        )
        return {"_error": str(exc)[:300]}


def _first_value(mapping: Any, names: Iterable[str]) -> Any:
    for name in names:
        try:
            value = mapping.get(name)
        except (AttributeError, KeyError, TypeError):
            try:
                value = mapping[name]
            except (KeyError, TypeError, AttributeError):
                value = None
        if value is not None:
            return value
    return None


def _coerce_utc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_us_equity_exchange(*values: Any) -> bool:
    return any(str(value or "").strip().upper() in _US_EQUITY_EXCHANGES for value in values)


def _clock_market_session(observed_at: datetime) -> str:
    eastern = observed_at.astimezone(_US_EASTERN)
    if eastern.weekday() >= 5:
        return "closed"
    local_time = eastern.time().replace(tzinfo=None)
    if _US_REGULAR_OPEN <= local_time < _US_REGULAR_CLOSE:
        return "regular"
    if _US_PREMARKET_OPEN <= local_time < _US_REGULAR_OPEN:
        return "premarket"
    if _US_REGULAR_CLOSE <= local_time < _US_AFTER_HOURS_CLOSE:
        return "after_hours"
    return "closed"


def _normalize_market_state(value: Any) -> Optional[str]:
    state = str(value or "").strip().upper()
    if state in {"REGULAR", "OPEN"}:
        return "regular"
    if state in {"PRE", "PREPRE"}:
        return "premarket"
    if state in {"POST", "POSTPOST"}:
        return "after_hours"
    if state in {"CLOSED", "CLOSE"}:
        return "closed"
    return None


def classify_quote_quality(
    *,
    requested_exchange: str,
    provider_exchange: Any = None,
    market_state: Any = None,
    quote_timestamp: Any = None,
    observed_at: Optional[datetime] = None,
    stale_after_seconds: int = DEFAULT_QUOTE_STALE_AFTER_SECONDS,
) -> Dict[str, Any]:
    """Classify quote freshness without treating a closed US session as a provider failure."""

    observed = _coerce_utc_datetime(observed_at) or datetime.now(timezone.utc)
    is_us_equity = _is_us_equity_exchange(requested_exchange, provider_exchange)
    if not is_us_equity:
        return {
            "status": "not_applicable",
            "quote_is_fresh": None,
            "quote_age_seconds": None,
            "market_session": "not_applicable",
            "market_open": None,
            "session_source": "not_applicable",
            "stale_after_seconds": max(1, int(stale_after_seconds)),
        }

    provider_session = _normalize_market_state(market_state)
    session = provider_session or _clock_market_session(observed)
    session_source = "provider_market_state" if provider_session else "weekday_clock"
    parsed_quote = _coerce_utc_datetime(quote_timestamp)
    quote_age_seconds = None
    if parsed_quote is not None:
        quote_age_seconds = round((observed - parsed_quote).total_seconds(), 3)

    threshold = max(1, int(stale_after_seconds))
    if session != "regular":
        status = "market_closed"
        quote_is_fresh = False
    elif parsed_quote is None:
        status = "missing_quote_timestamp"
        quote_is_fresh = False
    elif quote_age_seconds is None:
        status = "stale_quote"
        quote_is_fresh = False
    elif quote_age_seconds < -MAX_FUTURE_QUOTE_SKEW_SECONDS:
        status = "stale_quote"
        quote_is_fresh = False
    elif quote_age_seconds > threshold:
        status = "stale_quote"
        quote_is_fresh = False
    else:
        status = "fresh"
        quote_is_fresh = True

    return {
        "status": status,
        "quote_is_fresh": quote_is_fresh,
        "quote_age_seconds": quote_age_seconds,
        "market_session": session,
        "market_open": session == "regular",
        "session_source": session_source,
        "stale_after_seconds": threshold,
    }


def _group_status(snapshot: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    field_list = list(fields)
    available = [field for field in field_list if snapshot.get(field) is not None]
    missing = [field for field in field_list if field not in available]
    if not available:
        status = "missing"
    elif missing:
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "available_fields": available,
        "missing_fields": missing,
        "coverage_ratio": round(len(available) / len(field_list), 4) if field_list else 1.0,
    }


def _build_data_quality(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    groups = {
        name: _group_status(snapshot, fields)
        for name, fields in _DATA_QUALITY_GROUPS.items()
    }
    tracked_fields = [field for fields in _DATA_QUALITY_GROUPS.values() for field in fields]
    unique_fields = list(dict.fromkeys(tracked_fields))
    available_fields = [field for field in unique_fields if snapshot.get(field) is not None]
    missing_fields = [field for field in unique_fields if field not in available_fields]
    critical_complete = all(
        groups[group]["status"] != "missing" for group in ("quote", "liquidity")
    )
    return {
        "status": "complete" if not missing_fields else "partial" if available_fields else "missing",
        "critical_data_available": critical_complete,
        "coverage_ratio": round(len(available_fields) / len(unique_fields), 4) if unique_fields else 1.0,
        "available_fields": available_fields,
        "missing_fields": missing_fields,
        "groups": groups,
    }


def _simulated_market_requested() -> bool:
    return str(os.getenv(_SIMULATED_MARKET_ENV, "")).strip().lower() in _SIMULATED_MARKET_TRUE_VALUES


def _simulated_market_number(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: Optional[float] = None,
) -> float:
    raw = os.getenv(name)
    value = default if raw is None or not str(raw).strip() else _safe_number(raw)
    if value is None or value < minimum or (maximum is not None and value > maximum):
        range_text = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        raise RuntimeError(f"{name} must be finite and within {range_text}")
    return float(value)


def _build_simulated_market_snapshot(
    *,
    clean_symbol: str,
    yf_symbol: str,
    exchange: str,
    observed_at: datetime,
    yfinance_info: Optional[Dict[str, Any]],
    include_execution_history: bool,
) -> Dict[str, Any]:
    """Build deterministic execution evidence for isolated PAPER/dev smoke tests.

    This path intentionally executes before Alpaca/yfinance provider access so a
    closed market or provider outage cannot prevent downstream integration testing.
    It is disabled by default and fails closed outside PAPER + SCANNER_DEV_MODE.
    """

    if str(settings.TRADING_MODE or "").strip().upper() != "PAPER":
        raise RuntimeError(
            "SCANNER_SIMULATED_MARKET_ENABLED is allowed only when TRADING_MODE=PAPER"
        )
    if not bool(settings.SCANNER_DEV_MODE):
        raise RuntimeError(
            "SCANNER_SIMULATED_MARKET_ENABLED requires SCANNER_DEV_MODE=true"
        )
    if not _is_us_equity_exchange(exchange):
        raise RuntimeError(
            "SCANNER_SIMULATED_MARKET_ENABLED supports US equity exchanges only"
        )

    info = dict(yfinance_info or {})
    snapshot: Dict[str, Any] = {
        "symbol": clean_symbol,
        "yf_symbol": yf_symbol,
        "requested_exchange": exchange,
        "fetched_at": observed_at.isoformat(),
    }
    field_sources: Dict[str, str] = {}
    for key in _INFO_FIELDS:
        value = info.get(key)
        if value is not None:
            snapshot[key] = value
            field_sources[key] = "reused_yfinance_info"

    price = _positive_price(
        os.getenv("SCANNER_SIMULATED_MARKET_PRICE"),
        snapshot.get("currentPrice"),
        snapshot.get("regularMarketPrice"),
        snapshot.get("previousClose"),
    ) or _SIMULATED_MARKET_DEFAULT_PRICE
    spread_bps = _simulated_market_number(
        "SCANNER_SIMULATED_MARKET_SPREAD_BPS",
        _SIMULATED_MARKET_DEFAULT_SPREAD_BPS,
        minimum=0.0,
        maximum=50.0,
    )
    average_volume = _simulated_market_number(
        "SCANNER_SIMULATED_MARKET_AVERAGE_VOLUME",
        _SIMULATED_MARKET_DEFAULT_AVERAGE_VOLUME,
        minimum=1.0,
    )
    regular_volume = _simulated_market_number(
        "SCANNER_SIMULATED_MARKET_REGULAR_VOLUME",
        _SIMULATED_MARKET_DEFAULT_REGULAR_VOLUME,
        minimum=0.0,
    )
    atr_pct = _simulated_market_number(
        "SCANNER_SIMULATED_MARKET_ATR_PCT",
        _SIMULATED_MARKET_DEFAULT_ATR_PCT,
        minimum=0.0001,
        maximum=0.20,
    )

    half_spread = price * spread_bps / 20_000.0
    bid = max(0.01, price - half_spread)
    ask = max(bid, price + half_spread)
    quote_timestamp = observed_at.isoformat()

    snapshot.update(
        {
            "currentPrice": price,
            "regularMarketPrice": price,
            "exchange": str(snapshot.get("exchange") or exchange).upper(),
            "marketState": "REGULAR",
            "averageVolume": average_volume,
            "regularMarketVolume": regular_volume,
            "historicalAtr14": round(price * atr_pct, 8),
            "historicalAtrPct": round(atr_pct, 8),
            "historicalAverageVolume20d": average_volume,
            "historyBarCount": 45 if include_execution_history else 0,
            "alpacaBidPrice": round(bid, 8),
            "alpacaAskPrice": round(ask, 8),
            "alpacaBidSize": 500.0,
            "alpacaAskSize": 500.0,
            "alpacaMidpoint": round(price, 8),
            "alpacaSpread": round(ask - bid, 8),
            "alpacaSpreadBps": round(spread_bps, 4),
            "alpacaQuoteTimestamp": quote_timestamp,
            "simulatedMarket": {
                "enabled": True,
                "fixture": "open_us_regular_session",
                "broker_orders_allowed": False,
                "provider_calls_bypassed": True,
            },
        }
    )

    simulated_fields = (
        "currentPrice",
        "regularMarketPrice",
        "marketState",
        "averageVolume",
        "regularMarketVolume",
        "historicalAtr14",
        "historicalAtrPct",
        "historicalAverageVolume20d",
        "alpacaBidPrice",
        "alpacaAskPrice",
        "alpacaBidSize",
        "alpacaAskSize",
        "alpacaMidpoint",
        "alpacaSpread",
        "alpacaSpreadBps",
        "alpacaQuoteTimestamp",
    )
    for field in simulated_fields:
        field_sources[field] = "simulated_market_fixture"

    quote_quality = classify_quote_quality(
        requested_exchange=exchange,
        provider_exchange=snapshot.get("exchange"),
        market_state="REGULAR",
        quote_timestamp=quote_timestamp,
        observed_at=observed_at,
    )
    snapshot["quote_quality"] = quote_quality
    snapshot["quoteQualityStatus"] = quote_quality["status"]
    snapshot["alpacaQuoteAgeSeconds"] = quote_quality["quote_age_seconds"]
    snapshot["usMarketSession"] = quote_quality["market_session"]
    snapshot["usMarketOpen"] = quote_quality["market_open"]

    valuation_metric_count = sum(snapshot.get(key) is not None for key in _CORE_VALUATION_KEYS)
    sources = ["simulated_market_fixture"]
    if info:
        sources.insert(0, "reused_yfinance_info")
    provider_status = {
        "simulated_market": "success",
        "alpaca": "bypassed",
        "yfinance": "reused" if info else "bypassed",
    }
    if include_execution_history:
        provider_status["yfinance_history"] = "bypassed"
    snapshot.update(
        {
            "valuation_metric_count": valuation_metric_count,
            "valuation_data_complete": valuation_metric_count == len(_CORE_VALUATION_KEYS),
            "market_data_sources": sources,
            "provider_status": provider_status,
            "provider_errors": [],
            "field_sources": field_sources,
        }
    )
    snapshot["data_quality"] = _build_data_quality(snapshot)
    return snapshot


def get_market_snapshot(
    symbol: str,
    exchange: str = "SET",
    yfinance_info: Optional[Dict[str, Any]] = None,
    *,
    include_execution_history: bool = False,
) -> Dict[str, Any]:
    """Fetch a resilient, provenance-aware market and company snapshot.

    ``include_execution_history`` is deliberately opt-in. Candidate enrichment uses
    it to backfill ATR evidence, while generic callers that already supplied
    yfinance info retain the existing no-extra-provider-call behavior.

    For isolated integration tests only, ``SCANNER_SIMULATED_MARKET_ENABLED=true``
    creates deterministic US execution evidence before any provider access. The
    simulation is rejected unless Scanner is running in PAPER + dev mode.
    """

    clean_symbol = str(symbol or "").upper().strip()
    yf_symbol = map_symbol_for_yfinance(clean_symbol, exchange)
    observed_at = datetime.now(timezone.utc)

    if _simulated_market_requested():
        return _build_simulated_market_snapshot(
            clean_symbol=clean_symbol,
            yf_symbol=yf_symbol,
            exchange=exchange,
            observed_at=observed_at,
            yfinance_info=yfinance_info,
            include_execution_history=include_execution_history,
        )

    snapshot: Dict[str, Any] = {
        "symbol": clean_symbol,
        "yf_symbol": yf_symbol,
        "requested_exchange": exchange,
        "fetched_at": observed_at.isoformat(),
    }
    sources = []
    provider_errors = []
    provider_status: Dict[str, str] = {}
    field_sources: Dict[str, str] = {}

    if _alpaca_configured():
        try:
            request_params = StockLatestQuoteRequest(symbol_or_symbols=clean_symbol)
            latest_quote = _alpaca_client().get_stock_latest_quote(request_params)
            quote = latest_quote.get(clean_symbol) if latest_quote else None
            if quote is not None:
                ask_price = _safe_number(getattr(quote, "ask_price", None))
                bid_price = _safe_number(getattr(quote, "bid_price", None))
                ask_size = _safe_number(getattr(quote, "ask_size", None))
                bid_size = _safe_number(getattr(quote, "bid_size", None))
                snapshot.update(
                    {
                        "alpacaAskPrice": ask_price,
                        "alpacaBidPrice": bid_price,
                        "alpacaAskSize": ask_size,
                        "alpacaBidSize": bid_size,
                    }
                )
                midpoint = None
                if ask_price and ask_price > 0 and bid_price and bid_price > 0:
                    midpoint = (ask_price + bid_price) / 2
                    spread = ask_price - bid_price
                    snapshot["alpacaMidpoint"] = midpoint
                    snapshot["alpacaSpread"] = spread
                    snapshot["alpacaSpreadBps"] = (
                        round((spread / midpoint) * 10_000, 4) if midpoint > 0 else None
                    )
                price = _positive_price(ask_price, bid_price, midpoint)
                if price is not None:
                    snapshot["currentPrice"] = price
                    field_sources["currentPrice"] = "alpaca_latest_quote"
                quote_timestamp = _coerce_utc_datetime(getattr(quote, "timestamp", None))
                if quote_timestamp is not None:
                    snapshot["alpacaQuoteTimestamp"] = quote_timestamp.isoformat()
                elif getattr(quote, "timestamp", None) is not None:
                    snapshot["alpacaQuoteTimestamp"] = str(getattr(quote, "timestamp"))
                sources.append("alpaca_latest_quote")
                provider_status["alpaca"] = "success"
            else:
                provider_status["alpaca"] = "no_quote"
        except Exception as exc:
            provider_status["alpaca"] = "error"
            provider_errors.append(
                {"provider": "alpaca", "stage": "latest_quote", "error": str(exc)[:300]}
            )
            logger.warning("Error fetching market data for %s from Alpaca: %s", clean_symbol, exc)
    else:
        provider_status["alpaca"] = "not_configured"

    info = dict(yfinance_info or {})
    fast_info: Any = {}
    if info:
        sources.append("reused_yfinance_info")
        provider_status["yfinance"] = "reused"
    else:
        try:
            ticker = yf.Ticker(yf_symbol)
            try:
                fast_info = getattr(ticker, "fast_info", {}) or {}
            except Exception as exc:
                provider_errors.append(
                    {"provider": "yfinance", "stage": "fast_info", "error": str(exc)[:300]}
                )
                fast_info = {}
            try:
                getter = getattr(ticker, "get_info", None)
                info = (getter() if callable(getter) else ticker.info) or {}
            except Exception:
                info = ticker.info or {}
            sources.append("yfinance_info")
            provider_status["yfinance"] = "success"
        except Exception as exc:
            provider_status["yfinance"] = "error"
            provider_errors.append(
                {"provider": "yfinance", "stage": "ticker_info", "error": str(exc)[:300]}
            )
            logger.error("Error fetching market data for %s from yfinance: %s", clean_symbol, exc)
            info = {}
            fast_info = {}

    for key in _INFO_FIELDS:
        value = info.get(key)
        if value is not None and snapshot.get(key) is None:
            snapshot[key] = value
            field_sources[key] = "yfinance_info"

    fast_field_map = {
        "previousClose": ("previous_close", "previousClose"),
        "regularMarketPrice": ("last_price", "lastPrice"),
        "regularMarketVolume": ("last_volume", "lastVolume"),
        "dayHigh": ("day_high", "dayHigh"),
        "dayLow": ("day_low", "dayLow"),
        "fiftyTwoWeekHigh": ("year_high", "yearHigh"),
        "fiftyTwoWeekLow": ("year_low", "yearLow"),
        "averageVolume10days": ("ten_day_average_volume", "tenDayAverageVolume"),
        "averageVolume": ("three_month_average_volume", "threeMonthAverageVolume"),
        "marketCap": ("market_cap", "marketCap"),
        "currency": ("currency",),
    }
    for target, aliases in fast_field_map.items():
        if snapshot.get(target) is not None:
            continue
        value = _first_value(fast_info, aliases)
        if value is not None:
            snapshot[target] = value
            field_sources[target] = "yfinance_fast_info"

    if "currentPrice" not in snapshot:
        price = _positive_price(
            snapshot.get("regularMarketPrice"),
            info.get("currentPrice"),
            info.get("regularMarketPrice"),
            snapshot.get("previousClose"),
        )
        if price is not None:
            snapshot["currentPrice"] = price
            field_sources["currentPrice"] = field_sources.get(
                "regularMarketPrice", "yfinance_info"
            )

    if snapshot.get("averageVolume") is None:
        fallback_volume = _safe_number(
            snapshot.get("averageVolume10days") or info.get("averageDailyVolume10Day")
        )
        if fallback_volume is not None:
            snapshot["averageVolume"] = fallback_volume
            field_sources["averageVolume"] = field_sources.get(
                "averageVolume10days", "yfinance_info"
            )

    if include_execution_history and _is_us_equity_exchange(exchange, snapshot.get("exchange")):
        execution_history = dict(_yfinance_execution_history(yf_symbol))
        history_error = execution_history.pop("_error", None)
        if history_error:
            provider_status["yfinance_history"] = "error"
            provider_errors.append(
                {
                    "provider": "yfinance",
                    "stage": "execution_history",
                    "error": str(history_error)[:300],
                }
            )
        elif execution_history:
            provider_status["yfinance_history"] = "success"
            sources.append("yfinance_execution_history")
            for key, value in execution_history.items():
                snapshot[key] = value
                field_sources[key] = "yfinance_execution_history"
            if snapshot.get("averageVolume") is None and snapshot.get(
                "historicalAverageVolume20d"
            ) is not None:
                snapshot["averageVolume"] = snapshot["historicalAverageVolume20d"]
                field_sources["averageVolume"] = "yfinance_execution_history"

    quote_quality = classify_quote_quality(
        requested_exchange=exchange,
        provider_exchange=snapshot.get("exchange"),
        market_state=snapshot.get("marketState"),
        quote_timestamp=snapshot.get("alpacaQuoteTimestamp"),
        observed_at=observed_at,
    )
    snapshot["quote_quality"] = quote_quality
    snapshot["quoteQualityStatus"] = quote_quality["status"]
    snapshot["alpacaQuoteAgeSeconds"] = quote_quality["quote_age_seconds"]
    snapshot["usMarketSession"] = quote_quality["market_session"]
    snapshot["usMarketOpen"] = quote_quality["market_open"]

    valuation_metric_count = sum(snapshot.get(key) is not None for key in _CORE_VALUATION_KEYS)
    snapshot.update(
        {
            "valuation_metric_count": valuation_metric_count,
            "valuation_data_complete": valuation_metric_count == len(_CORE_VALUATION_KEYS),
            "market_data_sources": sources,
            "provider_status": provider_status,
            "provider_errors": provider_errors,
            "field_sources": field_sources,
        }
    )
    snapshot["data_quality"] = _build_data_quality(snapshot)
    return snapshot


def get_market_data(
    symbol: str,
    exchange: str = "SET",
    yfinance_info: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Backward-compatible strict market data wrapper for fundamental analysis."""

    market_data = get_market_snapshot(symbol, exchange, yfinance_info=yfinance_info)
    if market_data.get("currentPrice") is None:
        logger.warning("Missing current price for %s. Cannot proceed with analysis.", symbol)
        return None
    if market_data.get("valuation_metric_count", 0) == 0:
        logger.warning("Missing all core valuation metrics for %s. Cannot proceed with analysis.", symbol)
        return None
    return market_data
