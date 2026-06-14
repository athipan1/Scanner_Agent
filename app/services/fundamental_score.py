from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

import yfinance as yf


@dataclass
class FundamentalScoreResult:
    symbol: str
    score: float
    market_cap: Optional[float]
    revenue_growth: Optional[float]
    earnings_growth: Optional[float]
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    roe: Optional[float]
    debt_to_equity: Optional[float]
    profit_margin: Optional[float]
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
    # yfinance often returns growth as decimal, e.g. 0.18 = 18%.
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
    # Yahoo commonly reports debt/equity as percentage-like value, e.g. 120 = 120%.
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


@lru_cache(maxsize=1024)
def get_fundamental_score(symbol: str) -> FundamentalScoreResult:
    symbol = symbol.upper().strip()
    reasons: List[str] = []

    try:
        info: Dict = yf.Ticker(symbol).get_info() or {}
    except Exception as exc:
        return FundamentalScoreResult(
            symbol=symbol,
            score=0.50,
            market_cap=None,
            revenue_growth=None,
            earnings_growth=None,
            pe_ratio=None,
            forward_pe=None,
            roe=None,
            debt_to_equity=None,
            profit_margin=None,
            reason=[f"ดึงข้อมูลพื้นฐานไม่สำเร็จ: {exc}"],
        )

    market_cap = _safe_float(info.get("marketCap"))
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    earnings_growth = _safe_float(info.get("earningsGrowth"))
    pe_ratio = _safe_float(info.get("trailingPE"))
    forward_pe = _safe_float(info.get("forwardPE"))
    roe = _safe_float(info.get("returnOnEquity"))
    debt_to_equity = _safe_float(info.get("debtToEquity"))
    profit_margin = _safe_float(info.get("profitMargins"))

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
        if revenue_growth > 0:
            reasons.append(f"รายได้เติบโตเป็นบวก ({revenue_growth:.2%})")
        else:
            reasons.append(f"รายได้ยังไม่เติบโต ({revenue_growth:.2%})")
    if earnings_growth is not None:
        if earnings_growth > 0:
            reasons.append(f"กำไรเติบโตเป็นบวก ({earnings_growth:.2%})")
        else:
            reasons.append(f"กำไรยังไม่เติบโต ({earnings_growth:.2%})")
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
        market_cap=market_cap,
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        pe_ratio=pe_ratio,
        forward_pe=forward_pe,
        roe=roe,
        debt_to_equity=debt_to_equity,
        profit_margin=profit_margin,
        reason=reasons,
    )


def result_to_metadata(result: FundamentalScoreResult) -> Dict[str, object]:
    return {
        "symbol": result.symbol,
        "score": result.score,
        "market_cap": result.market_cap,
        "revenue_growth": result.revenue_growth,
        "earnings_growth": result.earnings_growth,
        "pe_ratio": result.pe_ratio,
        "forward_pe": result.forward_pe,
        "roe": result.roe,
        "debt_to_equity": result.debt_to_equity,
        "profit_margin": result.profit_margin,
        "reason": result.reason,
    }
