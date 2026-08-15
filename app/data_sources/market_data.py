import logging
import math
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

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
    "averageVolume",
    "averageVolume10days",
    "averageDailyVolume10Day",
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


def get_market_snapshot(
    symbol: str,
    exchange: str = "SET",
    yfinance_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch a resilient, provenance-aware market and company snapshot.

    Missing optional fields never discard a candidate. Instead, the response
    records field coverage and provider failures so Manager_Agent can distinguish
    incomplete data from a genuinely weak investment signal.
    """

    clean_symbol = str(symbol or "").upper().strip()
    yf_symbol = map_symbol_for_yfinance(clean_symbol, exchange)
    snapshot: Dict[str, Any] = {
        "symbol": clean_symbol,
        "yf_symbol": yf_symbol,
        "requested_exchange": exchange,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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
                    snapshot["alpacaSpreadBps"] = round((spread / midpoint) * 10_000, 4) if midpoint > 0 else None
                price = _positive_price(ask_price, bid_price, midpoint)
                if price is not None:
                    snapshot["currentPrice"] = price
                    field_sources["currentPrice"] = "alpaca_latest_quote"
                quote_timestamp = getattr(quote, "timestamp", None)
                if quote_timestamp is not None:
                    snapshot["alpacaQuoteTimestamp"] = str(quote_timestamp)
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
        if value is not None:
            snapshot[key] = value
            field_sources.setdefault(key, "yfinance_info")

    fast_field_map = {
        "previousClose": ("previous_close", "previousClose"),
        "regularMarketPrice": ("last_price", "lastPrice"),
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
            field_sources["currentPrice"] = field_sources.get("regularMarketPrice", "yfinance_info")

    if snapshot.get("averageVolume") is None:
        fallback_volume = _safe_number(
            snapshot.get("averageVolume10days") or info.get("averageDailyVolume10Day")
        )
        if fallback_volume is not None:
            snapshot["averageVolume"] = fallback_volume
            field_sources["averageVolume"] = field_sources.get("averageVolume10days", "yfinance_info")

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
