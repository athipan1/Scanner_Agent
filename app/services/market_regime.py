from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

import yfinance as yf


BENCHMARKS = ("SPY", "QQQ")


@dataclass
class MarketRegimeResult:
    regime: str
    confidence: float
    score: float
    benchmark_details: Dict[str, Dict[str, Optional[float]]]
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


def _score_benchmark(symbol: str) -> Dict[str, Optional[float]]:
    history = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True)
    if history is None or history.empty or "Close" not in history:
        return {
            "close": None,
            "ma50": None,
            "ma200": None,
            "return_20d": None,
            "return_60d": None,
            "trend_score": 0.50,
        }

    close_series = history["Close"].dropna()
    if len(close_series) < 60:
        return {
            "close": _safe_float(close_series.iloc[-1]) if len(close_series) else None,
            "ma50": None,
            "ma200": None,
            "return_20d": None,
            "return_60d": None,
            "trend_score": 0.50,
        }

    close = _safe_float(close_series.iloc[-1])
    ma50 = _safe_float(close_series.tail(50).mean())
    ma200 = _safe_float(close_series.tail(200).mean()) if len(close_series) >= 200 else None
    ret_20d = _pct_return(_safe_float(close_series.iloc[-21]) if len(close_series) >= 21 else None, close)
    ret_60d = _pct_return(_safe_float(close_series.iloc[-61]) if len(close_series) >= 61 else None, close)

    parts = []
    if close is not None and ma50 is not None:
        parts.append(1.0 if close > ma50 else 0.25)
    if close is not None and ma200 is not None:
        parts.append(1.0 if close > ma200 else 0.20)
    if ma50 is not None and ma200 is not None:
        parts.append(1.0 if ma50 > ma200 else 0.25)
    if ret_20d is not None:
        parts.append(_clamp01((ret_20d + 0.08) / 0.16))
    if ret_60d is not None:
        parts.append(_clamp01((ret_60d + 0.12) / 0.24))

    trend_score = sum(parts) / len(parts) if parts else 0.50
    return {
        "close": close,
        "ma50": ma50,
        "ma200": ma200,
        "return_20d": ret_20d,
        "return_60d": ret_60d,
        "trend_score": round(_clamp01(trend_score), 4),
    }


@lru_cache(maxsize=1)
def detect_market_regime() -> MarketRegimeResult:
    details: Dict[str, Dict[str, Optional[float]]] = {}
    reasons: List[str] = []

    for benchmark in BENCHMARKS:
        try:
            details[benchmark] = _score_benchmark(benchmark)
        except Exception as exc:
            details[benchmark] = {
                "close": None,
                "ma50": None,
                "ma200": None,
                "return_20d": None,
                "return_60d": None,
                "trend_score": 0.50,
            }
            reasons.append(f"อ่านข้อมูล {benchmark} ไม่สำเร็จ: {exc}")

    scores = [float(item.get("trend_score") or 0.50) for item in details.values()]
    market_score = sum(scores) / len(scores) if scores else 0.50

    if market_score >= 0.68:
        regime = "BULL"
        confidence = _clamp01((market_score - 0.50) / 0.35)
        reasons.append("ตลาดเป็นขาขึ้น: benchmark หลักอยู่ในแนวโน้มบวก")
    elif market_score <= 0.38:
        regime = "BEAR"
        confidence = _clamp01((0.50 - market_score) / 0.35)
        reasons.append("ตลาดเป็นขาลง: benchmark หลักอ่อนแรง")
    else:
        regime = "SIDEWAY"
        confidence = _clamp01(1.0 - abs(market_score - 0.50) / 0.25)
        reasons.append("ตลาดแกว่งตัว: สัญญาณ trend ยังไม่ชัด")

    for benchmark, item in details.items():
        close = item.get("close")
        ma50 = item.get("ma50")
        ma200 = item.get("ma200")
        if close is not None and ma50 is not None:
            reasons.append(f"{benchmark}: ราคา {'เหนือ' if close > ma50 else 'ต่ำกว่า'} MA50")
        if close is not None and ma200 is not None:
            reasons.append(f"{benchmark}: ราคา {'เหนือ' if close > ma200 else 'ต่ำกว่า'} MA200")

    return MarketRegimeResult(
        regime=regime,
        confidence=round(confidence, 4),
        score=round(_clamp01(market_score), 4),
        benchmark_details=details,
        reason=reasons,
    )


def result_to_metadata(result: MarketRegimeResult) -> Dict[str, object]:
    return {
        "regime": result.regime,
        "confidence": result.confidence,
        "score": result.score,
        "benchmark_details": result.benchmark_details,
        "reason": result.reason,
    }
