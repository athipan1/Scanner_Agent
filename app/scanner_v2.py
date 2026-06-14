from __future__ import annotations

from typing import Any, Dict, Iterable, List

US_GROWTH_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "AMD", "NFLX", "CRM", "ADBE", "ORCL", "NOW", "INTC",
    "QCOM", "TXN", "AMAT", "MU", "PANW", "CRWD", "SNOW", "SHOP",
    "UBER", "ABNB", "PYPL", "SQ", "COIN", "PLTR", "SMCI", "ARM",
    "JPM", "BAC", "V", "MA", "UNH", "LLY", "JNJ", "XOM", "COST", "WMT",
]

THAI_BLUE_CHIP_UNIVERSE = [
    "PTT", "AOT", "DELTA", "CPALL", "BBL", "SCB", "KBANK", "GULF",
    "ADVANC", "SCC", "BDMS", "PTTEP", "EA", "CPN", "TRUE", "HMPRO",
    "INTUCH", "MINT", "CRC", "OR",
]

DEFAULT_UNIVERSE_BY_MARKET = {
    "US": US_GROWTH_UNIVERSE,
    "TH": THAI_BLUE_CHIP_UNIVERSE,
    "SET": THAI_BLUE_CHIP_UNIVERSE,
}

RECOMMENDATION_SCORE = {
    "STRONG_BUY": 1.0,
    "BUY": 0.78,
    "NEUTRAL": 0.50,
    "HOLD": 0.50,
    "SELL": 0.25,
    "STRONG_SELL": 0.05,
}


def resolve_universe(symbols: Iterable[str] | None, screener: str = "america", exchange: str = "NASDAQ") -> List[str]:
    explicit = [str(s).upper().strip() for s in (symbols or []) if str(s).strip()]
    if explicit:
        return explicit

    market_key = "US"
    if screener.lower() in {"thailand", "thai", "set"} or exchange.upper() == "SET":
        market_key = "TH"

    return list(DEFAULT_UNIVERSE_BY_MARKET[market_key])


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def technical_score(summary: Dict[str, Any]) -> float:
    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    base = RECOMMENDATION_SCORE.get(recommendation, 0.50)

    buy_count = float(summary.get("BUY", 0) or 0)
    neutral_count = float(summary.get("NEUTRAL", 0) or 0)
    sell_count = float(summary.get("SELL", 0) or 0)
    total = buy_count + neutral_count + sell_count
    vote_score = (buy_count + 0.5 * neutral_count) / total if total else base

    return clamp01((base * 0.65) + (vote_score * 0.35))


def momentum_score(summary: Dict[str, Any]) -> float:
    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    if recommendation == "STRONG_BUY":
        return 0.90
    if recommendation == "BUY":
        return 0.72
    if recommendation in {"NEUTRAL", "HOLD"}:
        return 0.50
    if recommendation == "SELL":
        return 0.25
    return 0.10


def risk_score(summary: Dict[str, Any]) -> float:
    sell_count = float(summary.get("SELL", 0) or 0)
    buy_count = float(summary.get("BUY", 0) or 0)
    total = sell_count + buy_count + float(summary.get("NEUTRAL", 0) or 0)
    sell_pressure = sell_count / total if total else 0.0
    return clamp01(1.0 - sell_pressure)


def rank_technical_candidate(symbol: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    tech = technical_score(summary)
    momentum = momentum_score(summary)
    risk = risk_score(summary)
    final = clamp01((tech * 0.65) + (momentum * 0.20) + (risk * 0.15))

    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    reasons = []
    if recommendation in {"BUY", "STRONG_BUY"}:
        reasons.append(f"สัญญาณ TradingView เป็น {recommendation}")
    if tech >= 0.75:
        reasons.append("คะแนนเทคนิคสูง")
    if momentum >= 0.70:
        reasons.append("โมเมนตัมเป็นบวก")
    if risk >= 0.70:
        reasons.append("แรงขายในภาพรวมไม่สูง")
    if not reasons:
        reasons.append("ผ่านการคัดกรองเบื้องต้นแต่สัญญาณยังไม่ชัดมาก")

    if final >= 0.82:
        ranked_recommendation = "STRONG_BUY"
    elif final >= 0.62:
        ranked_recommendation = "BUY"
    else:
        ranked_recommendation = "HOLD"

    return {
        "symbol": symbol,
        "recommendation": ranked_recommendation,
        "confidence_score": round(final, 4),
        "details": summary,
        "technical_score": round(tech, 4),
        "momentum_score": round(momentum, 4),
        "risk_score": round(risk, 4),
        "reason": reasons,
    }


def fundamental_to_recommendation(score: float) -> str:
    if score >= 80:
        return "STRONG_BUY"
    if score >= 65:
        return "BUY"
    if score >= 45:
        return "HOLD"
    if score >= 30:
        return "SELL"
    return "STRONG_SELL"
