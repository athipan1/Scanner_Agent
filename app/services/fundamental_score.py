from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

import yfinance as yf


@dataclass
class FundamentalScoreResult:
    symbol: str
    score: float
    current_price: Optional[float]
    average_volume: Optional[float]
    market_cap: Optional[float]
    enterprise_value: Optional[float]
    sector: Optional[str]
    industry: Optional[str]
    currency: Optional[str]
    exchange: Optional[str]
    revenue_growth: Optional[float]
    earnings_growth: Optional[float]
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    peg_ratio: Optional[float]
    price_to_book: Optional[float]
    roe: Optional[float]
    roa: Optional[float]
    debt_to_equity: Optional[float]
    profit_margin: Optional[float]
    free_cashflow: Optional[float]
    beta: Optional[float]
    dividend_yield: Optional[float]
    fifty_two_week_high: Optional[float]
    fifty_two_week_low: Optional[float]
    reason: List[str]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_growth(value: Optional[float]) -> float:
    if value is None:
        return 0.50
    return _clamp01((value + 0.10) / 0.50)


def _score_pe(value: Optional[float]) -> float:
    if value is None or value <= 0:
        return 0.50
    if value <= 15:
        return 0.90
    if value <= 25:
        return 0.75
    if value <= 40:
        return 0.55
    if value <= 70:
        return 0.35
    return 0.20


def _score_roe(value: Optional[float]) -> float:
    if value is None:
        return 0.50
    return _clamp01((value + 0.05) / 0.35)


def _score_debt_to_equity(value: Optional[float]) -> float:
    if value is None:
        return 0.50
    if value <= 50:
        return 0.90
    if value <= 100:
        return 0.70
    if value <= 200:
        return 0.45
    return 0.25


def _score_margin(value: Optional[float]) -> float:
    if value is None:
        return 0.50
    return _clamp01((value + 0.05) / 0.35)


def _empty_result(symbol: str, reason: str) -> FundamentalScoreResult:
    return FundamentalScoreResult(
        symbol=symbol,
        score=0.50,
        current_price=None,
        average_volume=None,
        market_cap=None,
        enterprise_value=None,
        sector=None,
        industry=None,
        currency=None,
        exchange=None,
        revenue_growth=None,
        earnings_growth=None,
        pe_ratio=None,
        forward_pe=None,
        peg_ratio=None,
        price_to_book=None,
        roe=None,
        roa=None,
        debt_to_equity=None,
        profit_margin=None,
        free_cashflow=None,
        beta=None,
        dividend_yield=None,
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        reason=[reason],
    )


@lru_cache(maxsize=1024)
def get_fundamental_score(symbol: str) -> FundamentalScoreResult:
    symbol = symbol.upper().strip()
    reasons: List[str] = []

    try:
        info: Dict = yf.Ticker(symbol).get_info() or {}
    except Exception as exc:
        return _empty_result(symbol, f"ดึงข้อมูลพื้นฐานไม่สำเร็จ: {exc}")

    current_price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))
    average_volume = _safe_float(info.get("averageVolume") or info.get("averageVolume10days") or info.get("averageDailyVolume10Day"))
    market_cap = _safe_float(info.get("marketCap"))
    enterprise_value = _safe_float(info.get("enterpriseValue"))
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    earnings_growth = _safe_float(info.get("earningsGrowth"))
    pe_ratio = _safe_float(info.get("trailingPE"))
    forward_pe = _safe_float(info.get("forwardPE"))
    peg_ratio = _safe_float(info.get("pegRatio"))
    price_to_book = _safe_float(info.get("priceToBook"))
    roe = _safe_float(info.get("returnOnEquity"))
    roa = _safe_float(info.get("returnOnAssets"))
    debt_to_equity = _safe_float(info.get("debtToEquity"))
    profit_margin = _safe_float(info.get("profitMargins"))
    free_cashflow = _safe_float(info.get("freeCashflow"))
    beta = _safe_float(info.get("beta"))
    dividend_yield = _safe_float(info.get("dividendYield"))
    fifty_two_week_high = _safe_float(info.get("fiftyTwoWeekHigh"))
    fifty_two_week_low = _safe_float(info.get("fiftyTwoWeekLow"))
    sector = info.get("sector")
    industry = info.get("industry")
    currency = info.get("currency")
    exchange = info.get("exchange")

    growth_score = (_score_growth(revenue_growth) * 0.55) + (_score_growth(earnings_growth) * 0.45)
    valuation_score = (_score_pe(pe_ratio) * 0.45) + (_score_pe(forward_pe) * 0.55)
    quality_score = (
        (_score_roe(roe) * 0.40)
        + (_score_margin(profit_margin) * 0.35)
        + (_score_debt_to_equity(debt_to_equity) * 0.25)
    )

    size_score = 0.50
    if market_cap is not None:
        size_score = _clamp01(market_cap / 100_000_000_000)

    final_score = _clamp01(
        (growth_score * 0.35)
        + (quality_score * 0.30)
        + (valuation_score * 0.20)
        + (size_score * 0.15)
    )

    if market_cap is not None:
        reasons.append(f"Market Cap ประมาณ ${market_cap:,.0f}")
    if revenue_growth is not None:
        reasons.append(f"รายได้{'เติบโตเป็นบวก' if revenue_growth > 0 else 'ยังไม่เติบโต'} ({revenue_growth:.2%})")
    if earnings_growth is not None:
        reasons.append(f"กำไร{'เติบโตเป็นบวก' if earnings_growth > 0 else 'ยังไม่เติบโต'} ({earnings_growth:.2%})")
    if pe_ratio is not None and pe_ratio > 0:
        reasons.append(f"Trailing PE ประมาณ {pe_ratio:.2f}")
    if forward_pe is not None and forward_pe > 0:
        reasons.append(f"Forward PE ประมาณ {forward_pe:.2f}")
    if roe is not None:
        reasons.append(f"ROE ประมาณ {roe:.2%}")
    if debt_to_equity is not None:
        reasons.append(f"Debt/Equity ประมาณ {debt_to_equity:.2f}")
    if profit_margin is not None:
        reasons.append(f"Profit Margin ประมาณ {profit_margin:.2%}")

    if final_score >= 0.70:
        reasons.append("คะแนนพื้นฐานสนับสนุนการคัดเลือก")
    elif final_score < 0.45:
        reasons.append("คะแนนพื้นฐานยังไม่แข็งแรง ควรระวัง")

    return FundamentalScoreResult(
        symbol=symbol,
        score=round(final_score, 4),
        current_price=current_price,
        average_volume=average_volume,
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        sector=sector,
        industry=industry,
        currency=currency,
        exchange=exchange,
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        pe_ratio=pe_ratio,
        forward_pe=forward_pe,
        peg_ratio=peg_ratio,
        price_to_book=price_to_book,
        roe=roe,
        roa=roa,
        debt_to_equity=debt_to_equity,
        profit_margin=profit_margin,
        free_cashflow=free_cashflow,
        beta=beta,
        dividend_yield=dividend_yield,
        fifty_two_week_high=fifty_two_week_high,
        fifty_two_week_low=fifty_two_week_low,
        reason=reasons,
    )


def result_to_metadata(result: FundamentalScoreResult) -> Dict[str, object]:
    return {
        "symbol": result.symbol,
        "score": result.score,
        "current_price": result.current_price,
        "average_volume": result.average_volume,
        "market_cap": result.market_cap,
        "enterprise_value": result.enterprise_value,
        "sector": result.sector,
        "industry": result.industry,
        "currency": result.currency,
        "exchange": result.exchange,
        "revenue_growth": result.revenue_growth,
        "earnings_growth": result.earnings_growth,
        "pe_ratio": result.pe_ratio,
        "forward_pe": result.forward_pe,
        "peg_ratio": result.peg_ratio,
        "price_to_book": result.price_to_book,
        "roe": result.roe,
        "roa": result.roa,
        "debt_to_equity": result.debt_to_equity,
        "profit_margin": result.profit_margin,
        "free_cashflow": result.free_cashflow,
        "beta": result.beta,
        "dividend_yield": result.dividend_yield,
        "fifty_two_week_high": result.fifty_two_week_high,
        "fifty_two_week_low": result.fifty_two_week_low,
        "reason": result.reason,
    }
