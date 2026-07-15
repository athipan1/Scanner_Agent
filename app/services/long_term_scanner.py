from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

from app.analyzers import growth_analyzer, quality_analyzer, valuation_analyzer
from app.data_sources import financial_statements, market_data
from app.models import (
    ErrorDetail,
    FundamentalCandidate,
    GrowthMetrics,
    QualityMetrics,
    ValuationMetrics,
)
from app.scoring import fundamental_score


def analyze_stock(symbol: str, exchange: str = "SET") -> Tuple[str, FundamentalCandidate]:
    """Perform a full fundamental analysis on one stock symbol."""

    financials = financial_statements.get_financials(symbol, exchange)
    if not financials:
        raise ValueError("missing financial statements")

    market = market_data.get_market_data(
        symbol,
        exchange,
        yfinance_info=financials.get("info"),
    )
    if not market:
        raise ValueError("missing market data")

    quality_metrics = {
        "roe": quality_analyzer.calculate_roe(financials),
        "roa": quality_analyzer.calculate_roa(financials),
        "debt_to_equity": quality_analyzer.calculate_debt_to_equity(financials),
        "free_cash_flow": quality_analyzer.calculate_free_cash_flow(financials),
        "profit_margins": quality_analyzer.calculate_profit_margins(financials),
    }
    growth_metrics = {
        "revenue_cagr": growth_analyzer.calculate_revenue_cagr(financials),
        "eps_growth": growth_analyzer.calculate_eps_growth(financials),
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
        raise ValueError("could not calculate a final score due to missing data")

    grade = fundamental_score.get_grade(final_score)
    thesis = (
        f"{symbol} demonstrates "
        f"{'strong' if (quality_score or 0) > 70 else 'fair'} business quality, "
        f"with {'robust' if (growth_score or 0) > 70 else 'moderate'} growth prospects. "
        f"The stock appears "
        f"{'undervalued' if (valuation_score or 0) > 70 else 'fairly valued'}."
    )

    return symbol, FundamentalCandidate(
        symbol=symbol,
        grade=grade,
        fundamental_score=round(final_score, 2),
        quality=QualityMetrics(
            **{
                **quality_metrics,
                "score": round(quality_score, 2)
                if quality_score is not None
                else None,
            }
        ),
        growth=GrowthMetrics(
            **{
                **growth_metrics,
                "score": round(growth_score, 2)
                if growth_score is not None
                else None,
            }
        ),
        valuation=ValuationMetrics(
            **{
                **valuation_metrics,
                "score": round(valuation_score, 2)
                if valuation_score is not None
                else None,
            }
        ),
        thesis=thesis,
    )


def scan_long_term(
    symbols: List[str], exchange: str = "SET"
) -> Tuple[List[FundamentalCandidate], List[ErrorDetail]]:
    """Scan a bounded list for long-term investment opportunities."""

    candidates: List[FundamentalCandidate] = []
    errors: List[ErrorDetail] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_symbol = {
            executor.submit(analyze_stock, symbol, exchange): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                _, result = future.result()
                candidates.append(result)
            except Exception as exc:
                errors.append(ErrorDetail(symbol=symbol, error=str(exc)))

    candidates.sort(key=lambda candidate: candidate.fundamental_score, reverse=True)
    return candidates, errors
