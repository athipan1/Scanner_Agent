from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

import yfinance as yf


SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

DEFAULT_BENCHMARK = "SPY"


@dataclass
class SectorRotationResult:
    symbol: str
    sector: Optional[str]
    industry: Optional[str]
    sector_etf: Optional[str]
    sector_return_20d: Optional[float]
    benchmark_return_20d: Optional[float]
    relative_strength_20d: Optional[float]
    score: float
    reason: List[str]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _pct_return(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None or start == 0:
        return None
    return (end - start) / start


@lru_cache(maxsize=512)
def _get_symbol_profile(symbol: str) -> Dict[str, Optional[str]]:
    try:
        info = yf.Ticker(symbol).get_info() or {}
        return {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception:
        return {"sector": None, "industry": None}


@lru_cache(maxsize=128)
def _return_20d(symbol: str) -> Optional[float]:
    try:
        history = yf.download(symbol, period="3mo", interval="1d", progress=False, auto_adjust=True)
        if history is None or history.empty or "Close" not in history:
            return None
        closes = history["Close"].dropna()
        if len(closes) < 21:
            return None
        return _pct_return(float(closes.iloc[-21]), float(closes.iloc[-1]))
    except Exception:
        return None


@lru_cache(maxsize=1024)
def get_sector_rotation_score(symbol: str) -> SectorRotationResult:
    symbol = symbol.upper().strip()
    profile = _get_symbol_profile(symbol)
    sector = profile.get("sector")
    industry = profile.get("industry")
    sector_etf = SECTOR_ETF_MAP.get(sector or "")
    reasons: List[str] = []

    if not sector_etf:
        return SectorRotationResult(
            symbol=symbol,
            sector=sector,
            industry=industry,
            sector_etf=None,
            sector_return_20d=None,
            benchmark_return_20d=None,
            relative_strength_20d=None,
            score=0.50,
            reason=["ยังไม่มีข้อมูล Sector ETF สำหรับเปรียบเทียบกลุ่มอุตสาหกรรม"],
        )

    sector_return = _return_20d(sector_etf)
    benchmark_return = _return_20d(DEFAULT_BENCHMARK)
    relative_strength = None
    if sector_return is not None and benchmark_return is not None:
        relative_strength = sector_return - benchmark_return

    if relative_strength is None:
        return SectorRotationResult(
            symbol=symbol,
            sector=sector,
            industry=industry,
            sector_etf=sector_etf,
            sector_return_20d=sector_return,
            benchmark_return_20d=benchmark_return,
            relative_strength_20d=None,
            score=0.50,
            reason=["ข้อมูล Sector Rotation ยังไม่เพียงพอ"],
        )

    # -10% relative strength maps near 0; +10% maps near 1.
    score = _clamp01((relative_strength + 0.10) / 0.20)

    if sector:
        reasons.append(f"อยู่ในกลุ่ม {sector}")
    if industry:
        reasons.append(f"อุตสาหกรรมย่อย: {industry}")
    reasons.append(f"ผลตอบแทน Sector ETF 20 วัน: {sector_return:.2%}")
    reasons.append(f"ผลตอบแทน SPY 20 วัน: {benchmark_return:.2%}")

    if relative_strength > 0:
        reasons.append(f"Sector แข็งแรงกว่า SPY ประมาณ {relative_strength:.2%}")
    else:
        reasons.append(f"Sector อ่อนกว่า SPY ประมาณ {relative_strength:.2%}")

    if score >= 0.65:
        reasons.append("Sector Rotation สนับสนุนหุ้นตัวนี้")
    elif score < 0.45:
        reasons.append("Sector Rotation ยังไม่สนับสนุน ควรระวัง")

    return SectorRotationResult(
        symbol=symbol,
        sector=sector,
        industry=industry,
        sector_etf=sector_etf,
        sector_return_20d=sector_return,
        benchmark_return_20d=benchmark_return,
        relative_strength_20d=relative_strength,
        score=round(score, 4),
        reason=reasons,
    )


def result_to_metadata(result: SectorRotationResult) -> Dict[str, object]:
    return {
        "symbol": result.symbol,
        "sector": result.sector,
        "industry": result.industry,
        "sector_etf": result.sector_etf,
        "sector_return_20d": result.sector_return_20d,
        "benchmark_return_20d": result.benchmark_return_20d,
        "relative_strength_20d": result.relative_strength_20d,
        "score": result.score,
        "reason": result.reason,
    }
