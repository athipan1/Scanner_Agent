from __future__ import annotations

from typing import Any, Dict, Iterable

from app.data_sources.market_data import get_market_snapshot
from app.services.opportunity_profile import build_opportunity_profile

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


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _normalize_indicator_values(values: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill execution evidence from already-fetched TradingView indicators.

    This performs no provider call. It exists so ATR% and relative-volume coverage do
    not depend on one provider naming a pre-computed ratio exactly the way Scanner
    expects.
    """

    normalized = dict(values or {})
    close = _safe_float(normalized.get("close"))
    atr = _safe_float(normalized.get("atr"))
    if _safe_float(normalized.get("atr_pct")) is None and close and close > 0 and atr is not None:
        normalized["atr_pct"] = round(atr / close, 8)

    volume = _safe_float(normalized.get("volume"))
    volume_ma = _safe_float(normalized.get("volume_ma"))
    if (
        _safe_float(normalized.get("volume_ratio")) is None
        and volume is not None
        and volume_ma is not None
        and volume_ma > 0
    ):
        normalized["volume_ratio"] = round(volume / volume_ma, 8)
    return normalized


def _backfill_bundle_opportunity_inputs(bundle: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(bundle)
    technical = dict(enriched.get("technical") or {})
    indicators = _normalize_indicator_values(dict(technical.get("indicator_values") or {}))
    if technical or indicators:
        technical["indicator_values"] = indicators
        enriched["technical"] = technical
    return enriched


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


def _attach_profile(bundle: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _backfill_bundle_opportunity_inputs(bundle)
    profile = build_opportunity_profile(normalized)
    normalized["opportunity_profile"] = profile
    quality = dict(normalized.get("data_quality") or {})
    quality["opportunity_evidence"] = profile.get("evidence_quality") or {}
    normalized["data_quality"] = quality
    return normalized


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

    bundle = {
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
    return _attach_profile(bundle)


def build_candidate_data_bundle(symbol: str, details: Dict[str, Any]) -> Dict[str, Any]:
    """Build a source-aware bundle for a candidate already selected by Scanner."""

    scanner_details = details.get("scanner_v50") or {}
    technical = _normalize_indicator_values(scanner_details.get("indicator_values") or {})
    market_rank = scanner_details.get("market_rank") or {}
    fundamental = scanner_details.get("fundamental") or {}
    sector_rotation = scanner_details.get("sector_rotation") or {}
    backtest = scanner_details.get("backtest") or {}
    exchange = details.get("resolved_exchange") or fundamental.get("exchange") or "NASDAQ"

    market_snapshot = get_market_snapshot(
        symbol,
        exchange=exchange,
        yfinance_info=_synthetic_yfinance_info(details) or None,
        include_execution_history=True,
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

    bundle = {
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
    return _attach_profile(bundle)


def enrich_candidate_metadata(symbol: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a complete data bundle without changing candidate scoring."""

    details = metadata.get("details")
    if not isinstance(details, dict):
        return metadata
    existing_bundle = details.get("data_bundle")
    if isinstance(existing_bundle, dict):
        normalized_bundle = _backfill_bundle_opportunity_inputs(existing_bundle)
        existing_profile = normalized_bundle.get("opportunity_profile")
        if isinstance(existing_profile, dict) and normalized_bundle == existing_bundle:
            return metadata
        enriched = dict(metadata)
        enriched_details = dict(details)
        if not isinstance(existing_profile, dict):
            normalized_bundle = _attach_profile(normalized_bundle)
        enriched_details["data_bundle"] = normalized_bundle
        enriched["details"] = enriched_details
        return enriched
    if not isinstance(details.get("scanner_v50"), dict):
        return metadata

    enriched = dict(metadata)
    enriched_details = dict(details)
    try:
        enriched_details["data_bundle"] = build_candidate_data_bundle(symbol, enriched_details)
    except Exception as exc:
        fallback_bundle = {
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
        enriched_details["data_bundle"] = _attach_profile(fallback_bundle)
    enriched["details"] = enriched_details
    return enriched
