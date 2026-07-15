import logging
from functools import lru_cache
from typing import Any, Dict, Optional

import yfinance as yf
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from app.config import settings
from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)

_VALUATION_KEYS = (
    "marketCap",
    "industry",
    "sector",
    "pegRatio",
    "trailingPE",
    "forwardPE",
    "priceToBook",
)
_CORE_VALUATION_KEYS = ("trailingPE", "pegRatio", "priceToBook")


@lru_cache(maxsize=1)
def _alpaca_client() -> StockHistoricalDataClient:
    """Reuse one thread-safe Alpaca data client instead of one client per symbol."""

    return StockHistoricalDataClient(
        api_key=settings.APCA_API_KEY_ID,
        secret_key=settings.APCA_API_SECRET_KEY,
    )


def _positive_price(*values: Any) -> Optional[float]:
    for value in values:
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


def get_market_data(
    symbol: str,
    exchange: str = "SET",
    yfinance_info: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch price and valuation data without requiring every optional ratio.

    Fundamental discovery previously rejected a symbol unless P/E, PEG and P/B
    were all present. PEG is legitimately absent for many companies, so the rule
    discarded otherwise analyzable stocks. This function now requires a valid
    price plus at least one core valuation metric. Missing metrics remain `None`
    and are therefore not awarded points by the valuation scorer.
    """

    market_data: Dict[str, Any] = {}
    sources = []

    try:
        request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        latest_quote = _alpaca_client().get_stock_latest_quote(request_params)
        quote = latest_quote.get(symbol) if latest_quote else None
        if quote is not None:
            price = _positive_price(
                getattr(quote, "ask_price", None),
                getattr(quote, "bid_price", None),
            )
            if price is not None:
                market_data["currentPrice"] = price
                sources.append("alpaca_latest_quote")
        if "currentPrice" not in market_data:
            logger.warning("Could not fetch a positive price for %s from Alpaca", symbol)
    except Exception as exc:
        logger.error("Error fetching market data for %s from Alpaca: %s", symbol, exc)

    info = dict(yfinance_info or {})
    if not info:
        try:
            yf_symbol = map_symbol_for_yfinance(symbol, exchange)
            info = yf.Ticker(yf_symbol).info or {}
            sources.append("yfinance_info")
        except Exception as exc:
            logger.error("Error fetching market data for %s from yfinance: %s", symbol, exc)
            info = {}
    else:
        sources.append("reused_yfinance_info")

    if "currentPrice" not in market_data:
        price = _positive_price(
            info.get("currentPrice"),
            info.get("regularMarketPrice"),
            info.get("previousClose"),
        )
        if price is not None:
            market_data["currentPrice"] = price

    for key in _VALUATION_KEYS:
        market_data[key] = info.get(key)

    valuation_metric_count = sum(
        market_data.get(key) is not None for key in _CORE_VALUATION_KEYS
    )
    market_data.update(
        {
            "valuation_metric_count": valuation_metric_count,
            "valuation_data_complete": valuation_metric_count == len(_CORE_VALUATION_KEYS),
            "market_data_sources": sources,
        }
    )

    if market_data.get("currentPrice") is None:
        logger.warning("Missing current price for %s. Cannot proceed with analysis.", symbol)
        return None
    if valuation_metric_count == 0:
        logger.warning(
            "Missing all core valuation metrics for %s. Cannot proceed with analysis.",
            symbol,
        )
        return None

    return market_data
