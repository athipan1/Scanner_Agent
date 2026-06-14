from tradingview_ta import TA_Handler, Interval
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any

from app.models import Candidate, ErrorDetail
from app.universe import resolve_universe


RECOMMENDATION_SCORE = {
    "STRONG_BUY": 1.0,
    "BUY": 0.78,
    "NEUTRAL": 0.50,
    "HOLD": 0.50,
    "SELL": 0.25,
    "STRONG_SELL": 0.05,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _technical_score(summary: Dict[str, Any]) -> float:
    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    base = RECOMMENDATION_SCORE.get(recommendation, 0.50)

    buy_count = float(summary.get("BUY", 0) or 0)
    neutral_count = float(summary.get("NEUTRAL", 0) or 0)
    sell_count = float(summary.get("SELL", 0) or 0)
    total = buy_count + neutral_count + sell_count
    vote_score = (buy_count + 0.5 * neutral_count) / total if total else base

    return _clamp01((base * 0.65) + (vote_score * 0.35))


def _momentum_score(summary: Dict[str, Any]) -> float:
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


def _risk_score(summary: Dict[str, Any]) -> float:
    sell_count = float(summary.get("SELL", 0) or 0)
    buy_count = float(summary.get("BUY", 0) or 0)
    neutral_count = float(summary.get("NEUTRAL", 0) or 0)
    total = sell_count + buy_count + neutral_count
    sell_pressure = sell_count / total if total else 0.0
    return _clamp01(1.0 - sell_pressure)


def _rank_recommendation(score: float) -> str:
    if score >= 0.82:
        return "STRONG_BUY"
    if score >= 0.62:
        return "BUY"
    if score >= 0.45:
        return "HOLD"
    if score >= 0.25:
        return "SELL"
    return "STRONG_SELL"


def _build_reasons(symbol: str, raw_recommendation: str, tech: float, momentum: float, risk: float) -> List[str]:
    reasons = []
    if raw_recommendation in {"BUY", "STRONG_BUY"}:
        reasons.append(f"{symbol} มีสัญญาณเทคนิคจาก TradingView เป็น {raw_recommendation}")
    if tech >= 0.75:
        reasons.append("คะแนนเทคนิคสูงกว่าระดับคัดเลือก")
    elif tech >= 0.60:
        reasons.append("คะแนนเทคนิคอยู่ในเกณฑ์บวก")
    if momentum >= 0.70:
        reasons.append("โมเมนตัมราคาเป็นบวก")
    if risk >= 0.70:
        reasons.append("แรงขายโดยรวมไม่สูงเมื่อเทียบกับแรงซื้อ")
    if not reasons:
        reasons.append("ผ่านการคัดกรองเบื้องต้น แต่สัญญาณยังไม่แข็งแรงมาก")
    return reasons


def _rank_candidate(symbol: str, analysis: Dict[str, Any]) -> Candidate:
    raw_recommendation = str(analysis.get("RECOMMENDATION", "HOLD")).upper()
    tech = _technical_score(analysis)
    momentum = _momentum_score(analysis)
    risk = _risk_score(analysis)
    final_score = _clamp01((tech * 0.65) + (momentum * 0.20) + (risk * 0.15))
    recommendation = _rank_recommendation(final_score)

    details = {
        **analysis,
        "technical_score": round(tech, 4),
        "momentum_score": round(momentum, 4),
        "risk_score": round(risk, 4),
        "final_score": round(final_score, 4),
        "raw_recommendation": raw_recommendation,
        "recommendation": recommendation,
        "reason": _build_reasons(symbol, raw_recommendation, tech, momentum, risk),
    }

    return Candidate(
        symbol=symbol,
        recommendation=recommendation,
        details=details,
    )


def fetch_analysis(symbol: str, screener: str, exchange: str) -> Dict[str, Any]:
    """
    Fetches technical analysis for a single stock symbol.
    """
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange,
            interval=Interval.INTERVAL_1_DAY
        )
        analysis = handler.get_analysis().summary
        return {"symbol": symbol, "analysis": analysis}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def scan_market(symbols: List[str], screener: str = "america", exchange: str = "NASDAQ") -> Tuple[List[Candidate], List[ErrorDetail]]:
    """
    Scans a stock universe in parallel, ranks candidates with technical, momentum,
    and risk scores, then returns the best actionable candidates.
    """
    symbols_to_scan = resolve_universe(symbols, screener=screener, exchange=exchange)
    candidates = []
    errors = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_symbol = {executor.submit(fetch_analysis, symbol, screener, exchange): symbol for symbol in symbols_to_scan}

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                result = future.result()
                if "error" in result:
                    error_message = result.get("error", "Unknown error")
                    errors.append(ErrorDetail(symbol=symbol, error=error_message))
                else:
                    analysis = result.get("analysis", {})
                    candidate = _rank_candidate(symbol, analysis)
                    final_score = float(candidate.details.get("final_score", 0.0))
                    if candidate.recommendation in ["BUY", "STRONG_BUY"] and final_score >= 0.62:
                        candidates.append(candidate)
            except Exception as e:
                errors.append(ErrorDetail(symbol=symbol, error=str(e)))

    candidates.sort(key=lambda c: c.details.get("final_score", 0.0), reverse=True)
    return candidates[:10], errors
