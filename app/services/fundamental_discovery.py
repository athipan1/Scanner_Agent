from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from app.analyzers import growth_analyzer, quality_analyzer, valuation_analyzer
from app.data_sources import financial_statements, market_data
from app.models import ErrorDetail, ScannerCandidateContract
from app.scoring import fundamental_score
from app.universe import (
    load_nasdaq100_symbols,
    load_nasdaq_listed_symbols,
    load_sp500_symbols,
    normalize_symbols,
)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_to_decimal(value: Any) -> Optional[float]:
    value = _safe_float(value)
    if value is None:
        return None
    return value / 100.0


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
        "has_annual_income_statement": bool(financials.get("has_annual_income_statement")),
        "has_annual_cash_flow": bool(financials.get("has_annual_cash_flow")),
        "has_annual_balance_sheet": bool(financials.get("has_annual_balance_sheet")),
        "has_quarterly_financials": bool(financials.get("has_quarterly_financials")),
        "has_quarterly_income_statement": bool(financials.get("has_quarterly_income_statement")),
        "has_quarterly_cash_flow": bool(financials.get("has_quarterly_cash_flow")),
        "annual_income_statement_shape": _statement_shape(annual_income),
        "annual_cash_flow_shape": _statement_shape(annual_cash_flow),
        "quarterly_income_statement_shape": _statement_shape(quarterly_income),
        "quarterly_cash_flow_shape": _statement_shape(quarterly_cash_flow),
        "annual_income_statement_rows_sample": _statement_rows(annual_income),
        "annual_cash_flow_rows_sample": _statement_rows(annual_cash_flow),
    }


def build_us_fundamental_universe(max_universe: int = 1000) -> Dict[str, Any]:
    """
    Builds a broad US universe with priority on S&P 500 + Nasdaq-100,
    then expands into NASDAQ listed equities.
    """
    sp500 = load_sp500_symbols()
    nasdaq100 = load_nasdaq100_symbols()
    nasdaq_listed = load_nasdaq_listed_symbols()
    symbols = normalize_symbols(sp500 + nasdaq100 + nasdaq_listed)

    if max_universe and max_universe > 0:
        symbols = symbols[:max_universe]

    return {
        "symbols": symbols,
        "sources": {
            "sp500_count": len(sp500),
            "nasdaq100_count": len(nasdaq100),
            "nasdaq_listed_count": len(nasdaq_listed),
            "selected_universe_count": len(symbols),
        },
    }


def analyze_fundamental_candidate(symbol: str, exchange: str = "NASDAQ") -> ScannerCandidateContract:
    financials = financial_statements.get_financials(symbol, exchange)
    market = market_data.get_market_data(symbol, exchange)

    if not financials:
        raise ValueError("missing financial statements")
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

    reasons = [
        f"คะแนนพื้นฐานรวม {float(final_score):.2f}",
        f"Quality {float(quality_score):.2f}" if quality_score is not None else "Quality data unavailable",
        f"Growth {float(growth_score):.2f}" if growth_score is not None else "Growth data unavailable",
        f"Valuation {float(valuation_score):.2f}" if valuation_score is not None else "Valuation data unavailable",
    ]
    if growth_metrics.get("revenue_3y_cagr") is not None:
        reasons.append(f"Revenue 3Y CAGR {float(growth_metrics['revenue_3y_cagr']):.2f}%")
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
        "quality_score": round(float(quality_score), 4) if quality_score is not None else None,
        "growth_score": round(float(growth_score), 4) if growth_score is not None else None,
        "valuation_score": round(float(valuation_score), 4) if valuation_score is not None else None,
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
        "qoq_revenue_growth": _pct_to_decimal(growth_metrics.get("qoq_revenue_growth")),
        "qoq_eps_growth": _pct_to_decimal(growth_metrics.get("qoq_eps_growth")),
        "qoq_fcf_growth": _pct_to_decimal(growth_metrics.get("qoq_fcf_growth")),
        "pe_ratio": _safe_float(valuation_metrics.get("pe_ratio")),
        "peg_ratio": _safe_float(valuation_metrics.get("peg_ratio")),
        "pb_ratio": _safe_float(valuation_metrics.get("pb_ratio")),
        "market_cap": market.get("marketCap"),
        "yf_symbol": annual_diagnostics.get("yf_symbol"),
        "has_annual_income_statement": annual_diagnostics.get("has_annual_income_statement"),
        "has_annual_cash_flow": annual_diagnostics.get("has_annual_cash_flow"),
    }

    return ScannerCandidateContract(
        symbol=symbol,
        candidate_score=round(float(final_score) / 100.0, 4),
        recommendation_hint="FUNDAMENTAL_TOP_10",
        exchange=exchange,
        screener="america",
        tags=["fundamental", "broad-market", "manager-handoff", "growth-v2", "annual-diagnostics"],
        reasons=reasons,
        raw_scores=raw_scores,
        metadata={
            "grade": fundamental_score.get_grade(final_score),
            "sector": market.get("sector"),
            "industry": market.get("industry"),
            "growth_metrics": growth_metrics,
            "annual_diagnostics": annual_diagnostics,
            "yf_symbol": annual_diagnostics.get("yf_symbol"),
            "has_annual_income_statement": annual_diagnostics.get("has_annual_income_statement"),
            "has_annual_cash_flow": annual_diagnostics.get("has_annual_cash_flow"),
            "source": "real_market_fundamental_discovery",
        },
    )


def discover_best_fundamentals(
    max_universe: int = 1000,
    top_n: int = 10,
    exchange: str = "NASDAQ",
    max_workers: int = 10,
) -> Tuple[List[ScannerCandidateContract], List[ErrorDetail], Dict[str, Any]]:
    universe_info = build_us_fundamental_universe(max_universe=max_universe)
    symbols = universe_info["symbols"]
    candidates: List[ScannerCandidateContract] = []
    errors: List[ErrorDetail] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(analyze_fundamental_candidate, symbol, exchange): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                candidates.append(future.result())
            except Exception as exc:
                errors.append(ErrorDetail(symbol=symbol, error=str(exc)))

    candidates.sort(
        key=lambda c: (
            c.candidate_score or 0.0,
            c.raw_scores.get("quality_score") or 0.0,
            c.raw_scores.get("growth_score") or 0.0,
            c.raw_scores.get("revenue_3y_cagr") or 0.0,
            c.raw_scores.get("fcf_growth") or 0.0,
            c.raw_scores.get("valuation_score") or 0.0,
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
            "has_annual_income_statement": candidate.metadata.get("has_annual_income_statement"),
            "has_annual_cash_flow": candidate.metadata.get("has_annual_cash_flow"),
            "revenue_3y_cagr": candidate.raw_scores.get("revenue_3y_cagr"),
            "eps_growth": candidate.raw_scores.get("eps_growth"),
            "fcf_growth": candidate.raw_scores.get("fcf_growth"),
        }
        for candidate in top_candidates
    ]

    metadata = {
        **universe_info["sources"],
        "analyzed_count": len(candidates),
        "error_count": len(errors),
        "top_n": top_n,
        "exchange": exchange,
        "growth_v2_fields": [
            "revenue_3y_cagr",
            "eps_growth",
            "fcf_growth",
            "qoq_revenue_growth",
            "qoq_eps_growth",
            "qoq_fcf_growth",
        ],
        "annual_diagnostics_fields": [
            "yf_symbol",
            "has_annual_income_statement",
            "has_annual_cash_flow",
            "annual_income_statement_shape",
            "annual_cash_flow_shape",
            "annual_income_statement_rows_sample",
            "annual_cash_flow_rows_sample",
        ],
        "top_candidate_annual_diagnostics": diagnostics,
    }
    return top_candidates, errors, metadata
