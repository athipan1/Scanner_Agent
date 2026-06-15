from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple

import yfinance as yf


MAX_SYMBOLS_AFTER_RANKING = 75
MIN_RANKED_SYMBOLS = 30


@dataclass
class MarketRankResult:
    symbol: str
    score: float
    price: Optional[float]
    return_5d: Optional[float]
    return_20d: Optional[float]
    return_60d: Optional[float]
    volume_ratio: Optional[float]
    trend_score: Optional[float]
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


def _pct_return(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None or start == 0:
        return None
    return (end - start) / start


def _score_return(value: Optional[float], low: float = -0.10, high: float = 0.20) -> float:
    if value is None:
        return 0.45
    return _clamp01((value - low) / (high - low))


def _score_volume_ratio(value: Optional[float]) -> float:
    if value is None:
        return 0.45
    return _clamp01(value / 3.0)


@lru_cache(maxsize=10000)
def rank_symbol(symbol: str) -> MarketRankResult:
    symbol = symbol.upper().strip()
    reasons: List[str] = []

    try:
        history = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if history is None or history.empty or "Close" not in history:
            return MarketRankResult(symbol, 0.0, None, None, None, None, None, None, ["ไม่มีข้อมูลราคาเพียงพอสำหรับ Market Ranking"])

        close_series = history["Close"].dropna()
        volume_series = history["Volume"].dropna() if "Volume" in history else None
        if len(close_series) < 30:
            return MarketRankResult(symbol, 0.0, None, None, None, None, None, None, ["ข้อมูลราคาน้อยเกินไปสำหรับ Market Ranking"])

        last_price = _safe_float(close_series.iloc[-1])
        ret_5d = _pct_return(_safe_float(close_series.iloc[-6]) if len(close_series) >= 6 else None, last_price)
        ret_20d = _pct_return(_safe_float(close_series.iloc[-21]) if len(close_series) >= 21 else None, last_price)
        ret_60d = _pct_return(_safe_float(close_series.iloc[-61]) if len(close_series) >= 61 else None, last_price)

        ma20 = _safe_float(close_series.tail(20).mean()) if len(close_series) >= 20 else None
        ma50 = _safe_float(close_series.tail(50).mean()) if len(close_series) >= 50 else None
        trend_parts = []
        if last_price is not None and ma20 is not None:
            trend_parts.append(1.0 if last_price > ma20 else 0.35)
            if last_price > ma20:
                reasons.append("ราคาอยู่เหนือ MA20")
        if ma20 is not None and ma50 is not None:
            trend_parts.append(1.0 if ma20 > ma50 else 0.35)
            if ma20 > ma50:
                reasons.append("MA20 อยู่เหนือ MA50 แนวโน้มระยะสั้นแข็งแรง")
        trend_score = sum(trend_parts) / len(trend_parts) if trend_parts else 0.45

        volume_ratio = None
        if volume_series is not None and len(volume_series) >= 21:
            recent_volume = _safe_float(volume_series.iloc[-1])
            avg_volume_20 = _safe_float(volume_series.tail(20).mean())
            if recent_volume is not None and avg_volume_20 and avg_volume_20 > 0:
                volume_ratio = recent_volume / avg_volume_20
                if volume_ratio >= 1.3:
                    reasons.append(f"Volume ล่าสุดสูงกว่าค่าเฉลี่ย ({volume_ratio:.2f}x)")

        score = _clamp01(
            (_score_return(ret_5d, -0.06, 0.12) * 0.15)
            + (_score_return(ret_20d, -0.10, 0.20) * 0.30)
            + (_score_return(ret_60d, -0.15, 0.35) * 0.25)
            + (_score_volume_ratio(volume_ratio) * 0.15)
            + (trend_score * 0.15)
        )

        if ret_20d is not None and ret_20d > 0:
            reasons.append(f"ผลตอบแทน 20 วันเป็นบวก ({ret_20d:.2%})")
        if ret_60d is not None and ret_60d > 0:
            reasons.append(f"ผลตอบแทน 60 วันเป็นบวก ({ret_60d:.2%})")
        if score >= 0.65:
            reasons.append("Market Ranking สนับสนุนให้ส่งเข้า TradingView")

        return MarketRankResult(
            symbol=symbol,
            score=round(score, 4),
            price=last_price,
            return_5d=ret_5d,
            return_20d=ret_20d,
            return_60d=ret_60d,
            volume_ratio=volume_ratio,
            trend_score=round(trend_score, 4),
            reason=reasons,
        )
    except Exception as exc:
        return MarketRankResult(symbol, 0.0, None, None, None, None, None, None, [f"Market Ranking error: {exc}"])


def rank_market_symbols(symbols: Iterable[str]) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    results = [rank_symbol(symbol) for symbol in symbols]
    ranked = sorted(results, key=lambda item: item.score, reverse=True)

    if len(ranked) < MIN_RANKED_SYMBOLS:
        selected = ranked
    else:
        selected = ranked[:MAX_SYMBOLS_AFTER_RANKING]

    metadata = {
        result.symbol: {
            "market_rank_score": result.score,
            "price": result.price,
            "return_5d": result.return_5d,
            "return_20d": result.return_20d,
            "return_60d": result.return_60d,
            "volume_ratio": result.volume_ratio,
            "trend_score": result.trend_score,
            "reason": result.reason,
        }
        for result in results
    }
    return [result.symbol for result in selected], metadata
