from __future__ import annotations

from typing import Any, Dict, Iterable

from app.data_sources.market_data import get_market_snapshot

DATA_BUNDLE_SCHEMA_VERSION = "scanner-data-bundle.v1"

_FUNDAMENTAL_TO_YFINANCE = {
    "current_price": "regularMarketPrice",
    "average_volume": "averageVolume",
    "market_cap": "marketCap",
    "enterprise_value": "enterpriseValue",
    "sector": "sector",
    "industry": "industry",
    "currency": "currency",
    "exchange": "exchange",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "pe_ratio": "trailingPE",
    "forward_pe": "forwardPE",
    "peg_ratio": "pegRatio",
    "price_to_book": "priceToBook",
    "roe": "returnOnEquity",
    "roa": "returnOnAssets",
    "debt_to_equity": "debtToEquity",
    "profit_margin": "profitMargins",
    "free_cashflow": "freeCashflow",
    "beta": "beta",
    "dividend_yield": "dividendYield",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
    "fifty_two_week_low": "fiftyTwoWeekLow",
}

_STATEMENT_COVERAGE_FIELDS = {
    "annual_income_statement": "has_annual_income_statement",
    "annual_balance_sheet": "has_annual_balance_sheet",
    "annual_cash_flow": "has_annual_cash_flow",
    "quarterly_income_statement": "has_quarterly_income_statement",
    "quarterly_balance_sheet": "has_quarterly_balance_sheet",
    "quarterly_cash_flow": "has_quarterly_cash_flow",
}


def _component_status(value: Any, fields: Iterable[str]) -> str:
    if not isinstance(value, dict):
        return "missing"
    required = list(fields)
    available = [field for field in required if value.get(field) is not None]
    if not available:
        return "missing"
    if len(available) == len(required):
        return "complete"
    return "partial"


def _synthetic_yfinance_info(details: Dict[str, Any]) -> Dict[str, Any]:
    scanner_details = details.get("scanner_v50") or {}
    fundamental = scanner_details.get("fundamental") or {}
    market_rank = scanner_details.get("market_rank") or {}
    info = {
        target: fundamental.get(source)
        for source, target in _FUNDAMENTAL_TO_YFINANCE.items()
        if fundamental.get(source) is not None
    }
    if info.get("regularMarketPrice") is None and market_rank.get("price") is not None:
        info["regularMarketPrice"] = market_rank.get("price")
    return info


def build_fundamental_data_bundle(
    symbol: str,
    financials: Dict[str, Any],
    financial_diagnostics: Dict[str, Any],
    market: Dict[str, Any],
) -> Dict[str, Any]:
    """Build one data-quality contract for all fundamental discovery paths."""

    statement_coverage = {
        output_name: bool(financials.get(source_name))
        for output_name, source_name in _STATEMENT_COVERAGE_FIELDS.items()
    }
    available_statements = [
        name for name, available in statement_coverage.items() if available
    ]
    missing_statements = [
        name for name, available in statement_coverage.items() if not available
    ]
    sources = ["yfinance_financial_statements"]
    for source in market.get("market_data_sources") or []:
        if source not in sources:
            sources.append(source)

    market_quality = market.get("data_quality") or {}
    statement_status = (
        "complete"
        if not missing_statements
        else "partial"
        if available_statements
        else "missing"
    )
    overall_status = (
        "complete"
        if statement_status == "complete" and market_quality.get("status") == "complete"
        else "partial"
        if available_statements or market_quality.get("status") in {"complete", "partial"}
        else "missing"
    )

    return {
        "schema_version": DATA_BUNDLE_SCHEMA_VERSION,
        "symbol": symbol,
        "sources": sources,
        "market_snapshot": market,
        "financial_statements": {
            "yf_symbol": financials.get("yf_symbol"),
            "provider_status": financial_diagnostics.get("status"),
            "provider_errors": financial_diagnostics.get("provider_errors") or [],
            "statement_coverage": statement_coverage,
            "available_statements": available_statements,
            "missing_statements": missing_statements,
        },
        "data_quality": {
            "status": overall_status,
            "market": market_quality,
            "financial_statements": {
                "status": statement_status,
                "available_statements": available_statements,
                "missing_statements": missing_statements,
            },
        },
    }


def build_candidate_data_bundle(symbol: str, details: Dict[str, Any]) -> Dict[str, Any]:
    """Build a source-aware bundle for a candidate already selected by Scanner."""

    scanner_details = details.get("scanner_v50") or {}
    technical = scanner_details.get("indicator_values") or {}
    market_rank = scanner_details.get("market_rank") or {}
    fundamental = scanner_details.get("fundamental") or {}
    sector_rotation = scanner_details.get("sector_rotation") or {}
    backtest = scanner_details.get("backtest") or {}
    exchange = details.get("resolved_exchange") or fundamental.get("exchange") or "NASDAQ"

    market_snapshot = get_market_snapshot(
        symbol,
        exchange=exchange,
        yfinance_info=_synthetic_yfinance_info(details) or None,
    )

    component_status = {
        "market": (market_snapshot.get("data_quality") or {}).get("status", "missing"),
        "technical": _component_status(
            technical,
            ("close", "rsi", "macd", "sma50", "sma200", "atr"),
        ),
        "market_rank": _component_status(
            market_rank,
            ("price", "return_20d", "return_60d", "volume_ratio", "trend_score"),
        ),
        "fundamental": _component_status(
            fundamental,
            (
                "market_cap",
                "revenue_growth",
                "earnings_growth",
                "pe_ratio",
                "roe",
                "debt_to_equity",
                "profit_margin",
            ),
        ),
        "sector_rotation": _component_status(sector_rotation, ("sector", "score")),
        "backtest": _component_status(backtest, ("score",)),
    }

    complete = [name for name, status in component_status.items() if status == "complete"]
    partial = [name for name, status in component_status.items() if status == "partial"]
    missing = [name for name, status in component_status.items() if status == "missing"]
    weighted_available = len(complete) + (0.5 * len(partial))
    coverage_ratio = round(weighted_available / len(component_status), 4)

    sources = ["tradingview"]
    for source in market_snapshot.get("market_data_sources") or []:
        if source not in sources:
            sources.append(source)
    for source, present in (
        ("yfinance_history", bool(market_rank)),
        ("yfinance_fundamentals", bool(fundamental)),
        ("sector_rotation", bool(sector_rotation)),
        ("scanner_backtest", bool(backtest)),
    ):
        if present and source not in sources:
            sources.append(source)

    return {
        "schema_version": DATA_BUNDLE_SCHEMA_VERSION,
        "symbol": symbol,
        "sources": sources,
        "market_snapshot": market_snapshot,
        "technical": {
            "provider": "tradingview",
            "resolved_exchange": exchange,
            "recommendation": details.get("raw_recommendation"),
            "indicator_values": technical,
            "relative_strength_values": scanner_details.get("relative_strength_values") or {},
            "growth_values": scanner_details.get("growth_values") or {},
        },
        "market_rank": market_rank,
        "fundamental": fundamental,
        "sector_rotation": sector_rotation,
        "backtest": backtest,
        "data_quality": {
            "status": "complete" if not partial and not missing else "partial" if complete or partial else "missing",
            "coverage_ratio": coverage_ratio,
            "component_status": component_status,
            "complete_components": complete,
            "partial_components": partial,
            "missing_components": missing,
            "market_provider_status": market_snapshot.get("provider_status") or {},
            "market_provider_errors": market_snapshot.get("provider_errors") or [],
            "market_missing_fields": (market_snapshot.get("data_quality") or {}).get("missing_fields", []),
        },
    }


def enrich_candidate_metadata(symbol: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a complete data bundle without changing candidate scoring."""

    details = metadata.get("details")
    if not isinstance(details, dict):
        return metadata
    if isinstance(details.get("data_bundle"), dict):
        return metadata
    if not isinstance(details.get("scanner_v50"), dict):
        return metadata

    enriched = dict(metadata)
    enriched_details = dict(details)
    try:
        enriched_details["data_bundle"] = build_candidate_data_bundle(symbol, enriched_details)
    except Exception as exc:
        enriched_details["data_bundle"] = {
            "schema_version": DATA_BUNDLE_SCHEMA_VERSION,
            "symbol": symbol,
            "sources": ["tradingview"],
            "market_snapshot": {},
            "data_quality": {
                "status": "partial",
                "coverage_ratio": 0.0,
                "component_status": {"market": "missing"},
                "complete_components": [],
                "partial_components": [],
                "missing_components": ["market"],
                "market_provider_errors": [
                    {
                        "provider": "enrichment",
                        "stage": "candidate_data_bundle",
                        "error": str(exc)[:300],
                    }
                ],
            },
        }
    enriched["details"] = enriched_details
    return enriched
