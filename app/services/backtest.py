from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional

import yfinance as yf


@dataclass
class BacktestResult:
    symbol: str
    current_price: Optional[float]
    return_5d: Optional[float]
    return_20d: Optional[float]
    win_rate: Optional[float]
    score: float
    reason: list[str]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _pct_return(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None or start == 0:
        return None
    return (end - start) / start


@lru_cache(maxsize=512)
def get_backtest_result(symbol: str) -> BacktestResult:
    symbol = symbol.upper().strip()
    reasons: list[str] = []

    try:
        history = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=True)
    except Exception as exc:
        return BacktestResult(
            symbol=symbol,
            current_price=None,
            return_5d=None,
            return_20d=None,
            win_rate=None,
            score=0.50,
            reason=[f"ดึงข้อมูลย้อนหลังไม่สำเร็จ: {exc}"],
        )

    if history is None or history.empty or "Close" not in history:
        return BacktestResult(
            symbol=symbol,
            current_price=None,
            return_5d=None,
            return_20d=None,
            win_rate=None,
            score=0.50,
            reason=["ไม่มีข้อมูลราคาย้อนหลังเพียงพอสำหรับ Backtest"],
        )

    closes = history["Close"].dropna()
    if len(closes) < 25:
        return BacktestResult(
            symbol=symbol,
            current_price=float(closes.iloc[-1]) if len(closes) else None,
            return_5d=None,
            return_20d=None,
            win_rate=None,
            score=0.50,
            reason=["ข้อมูลย้อนหลังน้อยเกินไปสำหรับคำนวณ Win Rate"],
        )

    current_price = float(closes.iloc[-1])
    return_5d = _pct_return(float(closes.iloc[-6]), current_price) if len(closes) >= 6 else None
    return_20d = _pct_return(float(closes.iloc[-21]), current_price) if len(closes) >= 21 else None

    forward_returns = []
    for i in range(20, len(closes) - 5):
        ma20 = closes.iloc[i - 20:i].mean()
        if closes.iloc[i] > ma20:
            forward_returns.append(_pct_return(float(closes.iloc[i]), float(closes.iloc[i + 5])))

    clean_forward_returns = [r for r in forward_returns if r is not None]
    win_rate = None
    if clean_forward_returns:
        win_rate = sum(1 for r in clean_forward_returns if r > 0) / len(clean_forward_returns)

    score_parts = []
    if return_5d is not None:
        score_parts.append(_clamp01((return_5d + 0.08) / 0.16))
        if return_5d > 0:
            reasons.append(f"ผลตอบแทน 5 วันล่าสุดเป็นบวก ({return_5d:.2%})")
        else:
            reasons.append(f"ผลตอบแทน 5 วันล่าสุดยังติดลบ ({return_5d:.2%})")

    if return_20d is not None:
        score_parts.append(_clamp01((return_20d + 0.15) / 0.30))
        if return_20d > 0:
            reasons.append(f"ผลตอบแทน 20 วันล่าสุดเป็นบวก ({return_20d:.2%})")
        else:
            reasons.append(f"ผลตอบแทน 20 วันล่าสุดยังติดลบ ({return_20d:.2%})")

    if win_rate is not None:
        score_parts.append(_clamp01(win_rate))
        reasons.append(f"Win Rate ย้อนหลังของสัญญาณเหนือ MA20 ประมาณ {win_rate:.2%}")

    score = sum(score_parts) / len(score_parts) if score_parts else 0.50
    if score >= 0.70:
        reasons.append("Backtest สนับสนุนการจัดอันดับหุ้นตัวนี้")
    elif score < 0.45:
        reasons.append("Backtest ยังไม่สนับสนุนมาก ควรระวัง")

    return BacktestResult(
        symbol=symbol,
        current_price=current_price,
        return_5d=return_5d,
        return_20d=return_20d,
        win_rate=win_rate,
        score=round(_clamp01(score), 4),
        reason=reasons,
    )


def result_to_metadata(result: BacktestResult) -> Dict[str, object]:
    return {
        "symbol": result.symbol,
        "current_price": result.current_price,
        "return_5d": result.return_5d,
        "return_20d": result.return_20d,
        "win_rate": result.win_rate,
        "score": result.score,
        "reason": result.reason,
    }
