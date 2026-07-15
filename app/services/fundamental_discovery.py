from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
from typing import Any, Dict, List, Optional, Tuple

from app.analyzers import growth_analyzer, quality_analyzer, valuation_analyzer
from app.data_sources import financial_statements, market_data
from app.models import ErrorDetail, ScannerCandidateContract
from app.scoring import fundamental_score
from app.services.bucket_hints import build_strategy_bucket_hints
from app.universe import (
    US_GROWTH_UNIVERSE,
    US_LARGE_CAP_FALLBACK,
    diversify_symbols_by_initial,
    load_nasdaq100_symbols,
    load_nasdaq_listed_symbols,
    load_sp500_symbols,
    normalize_symbols,
)

_NON_TRADABLE_DISCOVERY_SYMBOLS = {"CASH", "USD", "USDT", "USDC"}
_MAX_PROVIDER_WORKERS = 4
_ERROR_SAMPLE_LIMIT = 5


def _is_discoverable_stock_symbol(symbol: str) -> bool:
    symbol = str(symbol or "").strip().upper()
    if not symbol or symbol in _NON_TRADABLE_DISCOVERY_SYMBOLS:
        return False
    return "/" not in symbol and ":" not in symbol


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct_to_decimal(value: Any) -> Optional[float]:
    number = _safe_float(value)
    return None if number is None else number / 100.0


def _statement_shape(statement: Any) -> Optional[Dict[str, int]]:
    try:
        if statement is None or statement.empty:
            return None
        return {"rows": int(statement.shape[0]), "columns": int(statement.shape[1])}
    except Exception:
        return None


def _statement_rows(statement: Any, limit: int = 30) -> List[str]:
    try:
        if statement is None or statement.empty:
            return []
        return [str(row) for row in list(statement.index)[:limit]]
    except Exception:
        return []


def _annual_diagnostics(financials: Dict[str, Any]) -> Dict[str, Any]:
    annual_income = financials.get("annual_income_statement")
    annual_cash_flow = financials.get("annual_cash_flow")
    quarterly_income = financials.get("quarterly_income_statement")
    quarterly_cash_flow = financials.get("quarterly_cash_flow")
    return {
        "yf_symbol": financials.get("yf_symbol"),
        "has_annual_financials": bool(financials.get("has_annual_financials")),
        "has_annual_income_statement": bool(
            financials.get("has_annual_income_statement")
        ),
        "has_annual_cash_flow": bool(financials.get("has_annual_cash_flow")),
        "has_annual_balance_sheet": bool(
            financials.get("has_annual_balance_sheet")
        ),
        "has_quarterly_financials": bool(
            financials.get("has_quarterly_financials")
        ),
        "has_quarterly_income_statement": bool(
            financials.get("has_quarterly_income_statement")
        ),
        "has_quarterly_cash_flow": bool(
            financials.get("has_quarterly_cash_flow")
        ),
        "annual_income_statement_shape": _statement_shape(annual_income),
        "annual_cash_flow_shape": _statement_shape(annual_cash_flow),
        "quarterly_income_statement_shape": _statement_shape(quarterly_income),
        "quarterly_cash_flow_shape": _statement_shape(quarterly_cash_flow),
        "annual_income_statement_rows_sample": _statement_rows(annual_income),
        "annual_cash_flow_rows_sample": _statement_rows(annual_cash_flow),
    }


def _initial_coverage(symbols: List[str]) -> List[str]:
    return sorted({symbol[0] for symbol in symbols if symbol})


def build_us_fundamental_universe(max_universe: int = 1000) -> Dict[str, Any]:
    """Build a broad, deterministic, common-equity US universe."""

    live_sp500 = load_sp500_symbols()
    live_nasdaq100 = load_nasdaq100_symbols()
    nasdaq_listed = load_nasdaq_listed_symbols()

    sp500 = live_sp500 or list(US_LARGE_CAP_FALLBACK)
    nasdaq100 = live_nasdaq100 or list(US_GROWTH_UNIVERSE)
    priority = normalize_symbols(sp500 + nasdaq100)
    priority_set = set(priority)
    listed_fill = diversify_symbols_by_initial(
        symbol for symbol in nasdaq_listed if symbol not in priority_set
    )
    raw_symbols = normalize_symbols(priority + listed_fill)
    symbols = [symbol for symbol in raw_symbols if _is_discoverable_stock_symbol(symbol)]
    excluded_count = len(raw_symbols) - len(symbols)

    if max_universe and max_universe > 0:
        symbols = symbols[:max_universe]

    return {
        "symbols": symbols,
        "sources": {
            "sp500_count": len(live_sp500),
            "nasdaq100_count": len(live_nasdaq100),
            "nasdaq_listed_count": len(nasdaq_listed),
            "sp500_fallback_used": not bool(live_sp500),
            "nasdaq100_fallback_used": not bool(live_nasdaq100),
            "priority_large_cap_count": len(priority),
            "listed_initial_coverage": _initial_coverage(nasdaq_listed),
            "selected_initial_coverage": _initial_coverage(symbols),
            "selection_order": "large_cap_priority_then_round_robin_initial",
            "listed_security_filter": "common_equity_description_v1",
            "excluded_non_tradable_symbol_count": excluded_count,
            "selected_universe_count": len(symbols),
        },
    }


def _metric_coverage(*groups: Dict[str, Any]) -> Dict[str, Any]:
    total = sum(len(group) for group in groups)
    available = sum(
        _safe_float(value) is not None
        for group in groups
        for value in group.values()
    )
    return {
        "available": available,
        "total": total,
        "ratio": round(available / total, 4) if total else 0.0,
    }


def _financial_provider_error(diagnostics: Dict[str, Any]) -> str:
    errors = diagnostics.get("provider_errors") or []
    if not errors:
        return "financial provider error: unspecified provider failure"
    first = errors[0] if isinstance(errors[0], dict) else {"error": str(errors[0])}
    stage = first.get("stage") or "unknown_stage"
    message = first.get("error") or "provider failure"
    return f"financial provider error [{stage}]: {message}"


def analyze_fundamental_candidate(
    symbol: str,
    exchange: str = "NASDAQ",
) -> ScannerCandidateContract:
    symbol = str(symbol or "").strip().upper()
    if not _is_discoverable_stock_symbol(symbol):
        raise ValueError(f"non-tradable discovery symbol: {symbol}")

    financials, financial_diagnostics = (
        financial_statements.get_financials_with_diagnostics(symbol, exchange)
    )
    if not financials:
        if financial_diagnostics.get("status") == "provider_error":
            raise ValueError(_financial_provider_error(financial_diagnostics))
        raise ValueError("missing financial statements")

    market = market_data.get_market_data(
        symbol,
        exchange,
        yfinance_info=financials.get("info"),
    )
    if not market:
        raise ValueError("missing market data")

    annual_diagnostics = _annual_diagnostics(financials)
    quality_metrics = {
        "roe": quality_analyzer.calculate_roe(financials),
        "roa": quality_analyzer.calculate_roa(financials),
        "debt_to_equity": quality_analyzer.calculate_debt_to_equity(financials),
        "free_cash_flow": quality_analyzer.calculate_free_cash_flow(financials),
        "profit_margins": quality_analyzer.calculate_profit_margins(financials),
    }
    growth_metrics = {
        "revenue_cagr": growth_analyzer.calculate_revenue_cagr(financials),
        "revenue_3y_cagr": growth_analyzer.calculate_revenue_cagr(financials),
        "eps_growth": growth_analyzer.calculate_eps_growth(financials),
        "fcf_growth": growth_analyzer.calculate_fcf_growth(financials),
        "fcf_3y_cagr": growth_analyzer.calculate_fcf_growth(financials),
        "qoq_revenue_growth": growth_analyzer.calculate_qoq_revenue_growth(financials),
        "qoq_eps_growth": growth_analyzer.calculate_qoq_eps_growth(financials),
        "qoq_fcf_growth": growth_analyzer.calculate_qoq_fcf_growth(financials),
    }
    valuation_metrics = {
        "pe_ratio": valuation_analyzer.get_pe_ratio(market),
        "peg_ratio": valuation_analyzer.get_peg_ratio(market),
        "pb_ratio": valuation_analyzer.get_pb_ratio(market),
    }

    quality_score = fundamental_score.calculate_quality_score(quality_metrics)
    growth_score = fundamental_score.calculate_growth_score(growth_metrics)
    valuation_score = fundamental_score.calculate_valuation_score(valuation_metrics)
    final_score = fundamental_score.calculate_fundamental_score(
        {
            "quality_score": quality_score,
            "growth_score": growth_score,
            "valuation_score": valuation_score,
        }
    )
    if final_score is None:
        raise ValueError("final fundamental score is unavailable")

    evidence_coverage = _metric_coverage(
        quality_metrics,
        growth_metrics,
        valuation_metrics,
    )
    reasons = [
        f"คะแนนพื้นฐานรวม {float(final_score):.2f}",
        f"Quality {float(quality_score):.2f}"
        if quality_score is not None
        else "Quality data unavailable",
        f"Growth {float(growth_score):.2f}"
        if growth_score is not None
        else "Growth data unavailable",
        f"Valuation {float(valuation_score):.2f}"
        if valuation_score is not None
        else "Valuation data unavailable",
        f"Evidence coverage {evidence_coverage['available']}/{evidence_coverage['total']}",
    ]
    if growth_metrics.get("revenue_3y_cagr") is not None:
        reasons.append(
            f"Revenue 3Y CAGR {float(growth_metrics['revenue_3y_cagr']):.2f}%"
        )
    if growth_metrics.get("fcf_growth") is not None:
        reasons.append(f"FCF Growth {float(growth_metrics['fcf_growth']):.2f}%")
    if annual_diagnostics.get("yf_symbol"):
        reasons.append(f"Yahoo Finance symbol {annual_diagnostics['yf_symbol']}")
    reasons.append(
        "Annual diagnostics: "
        f"income={annual_diagnostics.get('has_annual_income_statement')}, "
        f"cash_flow={annual_diagnostics.get('has_annual_cash_flow')}"
    )

    raw_scores = {
        "fundamental_score": round(float(final_score), 4),
        "quality_score": round(float(quality_score), 4)
        if quality_score is not None
        else None,
        "growth_score": round(float(growth_score), 4)
        if growth_score is not None
        else None,
        "valuation_score": round(float(valuation_score), 4)
        if valuation_score is not None
        else None,
        "evidence_coverage": evidence_coverage["ratio"],
        "roe": _safe_float(quality_metrics.get("roe")),
        "roa": _safe_float(quality_metrics.get("roa")),
        "debt_to_equity": _safe_float(quality_metrics.get("debt_to_equity")),
        "free_cash_flow": _safe_float(quality_metrics.get("free_cash_flow")),
        "profit_margins": _safe_float(quality_metrics.get("profit_margins")),
        "revenue_cagr": _safe_float(growth_metrics.get("revenue_cagr")),
        "revenue_3y_cagr": _pct_to_decimal(growth_metrics.get("revenue_3y_cagr")),
        "eps_growth": _pct_to_decimal(growth_metrics.get("eps_growth")),
        "fcf_growth": _pct_to_decimal(growth_metrics.get("fcf_growth")),
        "fcf_3y_cagr": _pct_to_decimal(growth_metrics.get("fcf_3y_cagr")),
        "qoq_revenue_growth": _pct_to_decimal(
            growth_metrics.get("qoq_revenue_growth")
        ),
        "qoq_eps_growth": _pct_to_decimal(growth_metrics.get("qoq_eps_growth")),
        "qoq_fcf_growth": _pct_to_decimal(growth_metrics.get("qoq_fcf_growth")),
        "pe_ratio": _safe_float(valuation_metrics.get("pe_ratio")),
        "peg_ratio": _safe_float(valuation_metrics.get("peg_ratio")),
        "pb_ratio": _safe_float(valuation_metrics.get("pb_ratio")),
        "market_cap": _safe_float(market.get("marketCap")),
        "yf_symbol": annual_diagnostics.get("yf_symbol"),
        "has_annual_income_statement": annual_diagnostics.get(
            "has_annual_income_statement"
        ),
        "has_annual_cash_flow": annual_diagnostics.get("has_annual_cash_flow"),
    }
    base_metadata = {
        "grade": fundamental_score.get_grade(final_score),
        "sector": market.get("sector"),
        "industry": market.get("industry"),
        "growth_metrics": growth_metrics,
        "annual_diagnostics": annual_diagnostics,
        "financial_provider_diagnostics": financials.get(
            "financial_provider_diagnostics",
            {},
        ),
        "evidence_coverage": evidence_coverage,
        "valuation_metric_count": market.get("valuation_metric_count"),
        "valuation_data_complete": market.get("valuation_data_complete"),
        "market_data_sources": market.get("market_data_sources", []),
        "yf_symbol": annual_diagnostics.get("yf_symbol"),
        "has_annual_income_statement": annual_diagnostics.get(
            "has_annual_income_statement"
        ),
        "has_annual_cash_flow": annual_diagnostics.get("has_annual_cash_flow"),
        "source": "real_market_fundamental_discovery",
    }
    bucket_hints = build_strategy_bucket_hints(raw_scores, base_metadata)

    return ScannerCandidateContract(
        symbol=symbol,
        candidate_score=round(float(final_score) / 100.0, 4),
        recommendation_hint="FUNDAMENTAL_TOP_10",
        exchange=exchange,
        screener="america",
        tags=[
            "fundamental",
            "broad-market",
            "manager-handoff",
            "growth-v2",
            "annual-diagnostics",
            *bucket_hints.get("bucket_hint_tags", []),
        ],
        reasons=[
            *reasons,
            f"Primary bucket hint {bucket_hints.get('primary_strategy_bucket_hint')}",
        ],
        raw_scores=raw_scores,
        metadata={**base_metadata, **bucket_hints},
    )


def _classify_discovery_error(message: str) -> str:
    text = str(message or "").lower()
    if any(token in text for token in ("429", "too many requests", "rate limit")):
        return "provider_rate_limited"
    if "timeout" in text or "timed out" in text:
        return "provider_timeout"
    if "financial provider error" in text:
        return "financial_provider_error"
    if "missing financial" in text:
        return "missing_financial_statements"
    if "missing market" in text or "current price" in text:
        return "missing_market_data"
    if "final fundamental score" in text:
        return "insufficient_scoring_evidence"
    if "non-tradable" in text:
        return "non_tradable_symbol"
    return "analysis_error"


def _error_diagnostics(errors: List[ErrorDetail]) -> Dict[str, Any]:
    categories = Counter()
    samples = defaultdict(list)
    for error in errors:
        category = _classify_discovery_error(error.error)
        categories[category] += 1
        if len(samples[category]) < _ERROR_SAMPLE_LIMIT:
            samples[category].append(
                {"symbol": error.symbol, "error": error.error[:300]}
            )
    return {
        "error_categories": dict(sorted(categories.items())),
        "error_samples": dict(sorted(samples.items())),
        "provider_pressure_detected": bool(
            categories.get("provider_rate_limited")
            or categories.get("provider_timeout")
        ),
        "financial_provider_failures_detected": bool(
            categories.get("financial_provider_error")
        ),
    }


def discover_best_fundamentals(
    max_universe: int = 1000,
    top_n: int = 10,
    exchange: str = "NASDAQ",
    max_workers: int = 10,
) -> Tuple[List[ScannerCandidateContract], List[ErrorDetail], Dict[str, Any]]:
    universe_info = build_us_fundamental_universe(max_universe=max_universe)
    symbols = [
        symbol
        for symbol in universe_info["symbols"]
        if _is_discoverable_stock_symbol(symbol)
    ]
    candidates: List[ScannerCandidateContract] = []
    errors: List[ErrorDetail] = []
    effective_workers = max(1, min(int(max_workers), _MAX_PROVIDER_WORKERS))

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_to_symbol = {
            executor.submit(analyze_fundamental_candidate, symbol, exchange): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                candidate = future.result()
                if _is_discoverable_stock_symbol(candidate.symbol):
                    candidates.append(candidate)
            except Exception as exc:
                errors.append(ErrorDetail(symbol=symbol, error=str(exc)))

    candidates.sort(
        key=lambda candidate: (
            candidate.candidate_score or 0.0,
            candidate.raw_scores.get("evidence_coverage") or 0.0,
            candidate.raw_scores.get("quality_score") or 0.0,
            candidate.raw_scores.get("growth_score") or 0.0,
            candidate.raw_scores.get("revenue_3y_cagr") or 0.0,
            candidate.raw_scores.get("fcf_growth") or 0.0,
            candidate.raw_scores.get("valuation_score") or 0.0,
        ),
        reverse=True,
    )

    top_candidates = candidates[:top_n]
    for rank, candidate in enumerate(top_candidates, start=1):
        candidate.discovery_rank = rank

    diagnostics = [
        {
            "symbol": candidate.symbol,
            "yf_symbol": candidate.metadata.get("yf_symbol"),
            "primary_strategy_bucket_hint": candidate.metadata.get(
                "primary_strategy_bucket_hint"
            ),
            "bucket_hint_scores": candidate.metadata.get("bucket_hint_scores"),
            "has_annual_income_statement": candidate.metadata.get(
                "has_annual_income_statement"
            ),
            "has_annual_cash_flow": candidate.metadata.get(
                "has_annual_cash_flow"
            ),
            "valuation_metric_count": candidate.metadata.get(
                "valuation_metric_count"
            ),
            "evidence_coverage": candidate.raw_scores.get("evidence_coverage"),
            "revenue_3y_cagr": candidate.raw_scores.get("revenue_3y_cagr"),
            "eps_growth": candidate.raw_scores.get("eps_growth"),
            "fcf_growth": candidate.raw_scores.get("fcf_growth"),
        }
        for candidate in top_candidates
    ]
    error_diagnostics = _error_diagnostics(errors)
    attempted_count = len(symbols)

    metadata = {
        **universe_info["sources"],
        "attempted_count": attempted_count,
        "analyzed_count": len(candidates),
        "error_count": len(errors),
        "success_rate": round(len(candidates) / attempted_count, 4)
        if attempted_count
        else 0.0,
        "requested_max_workers": max_workers,
        "effective_max_workers": effective_workers,
        "provider_worker_cap": _MAX_PROVIDER_WORKERS,
        **error_diagnostics,
        "top_n": top_n,
        "exchange": exchange,
        "excluded_non_tradable_symbols": sorted(_NON_TRADABLE_DISCOVERY_SYMBOLS),
        "bucket_hints_enabled": True,
        "growth_v2_fields": [
            "revenue_3y_cagr",
            "eps_growth",
            "fcf_growth",
            "fcf_3y_cagr",
            "qoq_revenue_growth",
            "qoq_eps_growth",
            "qoq_fcf_growth",
        ],
        "diagnostics": diagnostics,
    }
    return top_candidates, errors, metadata
