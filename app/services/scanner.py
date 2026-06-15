from tradingview_ta import TA_Handler, Interval
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any, Optional

from app.models import Candidate, ErrorDetail
from app.universe import resolve_universe
from app.services.backtest import get_backtest_result, result_to_metadata
from app.services.prefilter import prefilter_symbols
from app.services.fundamental_score import get_fundamental_score, result_to_metadata as fundamental_to_metadata
from app.services.sector_rotation import get_sector_rotation_score, result_to_metadata as sector_to_metadata


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


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_indicator(indicators: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        if name in indicators:
            value = _to_float(indicators.get(name))
            if value is not None:
                return value
    return None


def _technical_score(summary: Dict[str, Any]) -> float:
    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    base = RECOMMENDATION_SCORE.get(recommendation, 0.50)
    buy_count = float(summary.get("BUY", 0) or 0)
    neutral_count = float(summary.get("NEUTRAL", 0) or 0)
    sell_count = float(summary.get("SELL", 0) or 0)
    total = buy_count + neutral_count + sell_count
    vote_score = (buy_count + 0.5 * neutral_count) / total if total else base
    return _clamp01((base * 0.65) + (vote_score * 0.35))


def _indicator_score(indicators: Dict[str, Any]) -> Dict[str, Any]:
    close = _get_indicator(indicators, "close", "Close")
    rsi = _get_indicator(indicators, "RSI", "RSI[1]")
    macd = _get_indicator(indicators, "MACD.macd", "MACD")
    macd_signal = _get_indicator(indicators, "MACD.signal")
    sma50 = _get_indicator(indicators, "SMA50", "SMA50[1]")
    sma200 = _get_indicator(indicators, "SMA200", "SMA200[1]")
    volume = _get_indicator(indicators, "volume", "Volume")
    volume_ma = _get_indicator(indicators, "Volume MA", "volume_ma", "SMA20.volume")
    atr = _get_indicator(indicators, "ATR", "ATR[1]")
    high_52w = _get_indicator(indicators, "High.52W", "52 Week High", "high_52w")
    score_parts = []
    reasons = []
    values = {
        "close": close,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "sma50": sma50,
        "sma200": sma200,
        "volume": volume,
        "volume_ma": volume_ma,
        "atr": atr,
        "high_52w": high_52w,
    }

    if rsi is not None:
        if 45 <= rsi <= 70:
            score_parts.append(0.85)
            reasons.append(f"RSI อยู่ในโซนแข็งแรงแต่ยังไม่ร้อนเกินไป ({rsi:.2f})")
        elif 35 <= rsi < 45:
            score_parts.append(0.60)
            reasons.append(f"RSI เริ่มฟื้นตัว ({rsi:.2f})")
        elif rsi > 70:
            score_parts.append(0.45)
            reasons.append(f"RSI สูงเกิน 70 อาจเริ่มร้อนแรง ({rsi:.2f})")
        else:
            score_parts.append(0.30)
            reasons.append(f"RSI ยังอ่อน ({rsi:.2f})")

    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            score_parts.append(0.85)
            reasons.append("MACD อยู่เหนือเส้น Signal เป็นสัญญาณบวก")
        else:
            score_parts.append(0.35)
            reasons.append("MACD ยังต่ำกว่าเส้น Signal")

    if close is not None and sma50 is not None:
        if close > sma50:
            score_parts.append(0.80)
            reasons.append("ราคาปิดอยู่เหนือ SMA50")
        else:
            score_parts.append(0.35)
            reasons.append("ราคาปิดยังต่ำกว่า SMA50")

    if close is not None and sma200 is not None:
        if close > sma200:
            score_parts.append(0.85)
            reasons.append("ราคาปิดอยู่เหนือ SMA200 แนวโน้มใหญ่ยังเป็นบวก")
        else:
            score_parts.append(0.30)
            reasons.append("ราคาปิดยังต่ำกว่า SMA200")

    if volume is not None and volume_ma is not None and volume_ma > 0:
        volume_ratio = volume / volume_ma
        values["volume_ratio"] = round(volume_ratio, 4)
        if volume_ratio >= 1.5:
            score_parts.append(0.85)
            reasons.append(f"Volume สูงกว่าค่าเฉลี่ยมาก ({volume_ratio:.2f}x)")
        elif volume_ratio >= 1.1:
            score_parts.append(0.65)
            reasons.append(f"Volume สูงกว่าค่าเฉลี่ย ({volume_ratio:.2f}x)")
        else:
            score_parts.append(0.45)
            reasons.append(f"Volume ยังไม่เด่น ({volume_ratio:.2f}x)")

    if close is not None and high_52w is not None and high_52w > 0:
        breakout_ratio = close / high_52w
        values["breakout_ratio"] = round(breakout_ratio, 4)
        if breakout_ratio >= 0.98:
            score_parts.append(0.85)
            reasons.append("ราคาเข้าใกล้หรือกำลังเบรกโซน High 52 สัปดาห์")
        elif breakout_ratio >= 0.90:
            score_parts.append(0.65)
            reasons.append("ราคาอยู่ใกล้โซน High 52 สัปดาห์")
        else:
            score_parts.append(0.45)

    if close is not None and atr is not None and close > 0:
        atr_pct = atr / close
        values["atr_pct"] = round(atr_pct, 4)
        if atr_pct <= 0.06:
            score_parts.append(0.70)
            reasons.append(f"ATR อยู่ในระดับควบคุมได้ ({atr_pct:.2%})")
        else:
            score_parts.append(0.40)
            reasons.append(f"ATR สูง ความผันผวนมาก ({atr_pct:.2%})")

    final = sum(score_parts) / len(score_parts) if score_parts else 0.50
    return {"score": round(_clamp01(final), 4), "values": values, "reasons": reasons}


def _relative_strength_score(indicators: Dict[str, Any]) -> Dict[str, Any]:
    close = _get_indicator(indicators, "close", "Close")
    perf_1m = _get_indicator(indicators, "Perf.W", "Perf.1M", "change_1m")
    perf_3m = _get_indicator(indicators, "Perf.3M", "change_3m")
    perf_6m = _get_indicator(indicators, "Perf.6M", "change_6m")
    values = {"close": close, "perf_1m": perf_1m, "perf_3m": perf_3m, "perf_6m": perf_6m}
    parts = []
    reasons = []
    for label, value in (("1 เดือน", perf_1m), ("3 เดือน", perf_3m), ("6 เดือน", perf_6m)):
        if value is None:
            continue
        normalized = _clamp01((value + 20.0) / 40.0)
        parts.append(normalized)
        if value > 0:
            reasons.append(f"ผลตอบแทนย้อนหลัง {label} เป็นบวก ({value:.2f}%)")
    score = sum(parts) / len(parts) if parts else 0.50
    return {"score": round(score, 4), "values": values, "reasons": reasons}


def _growth_score(indicators: Dict[str, Any]) -> Dict[str, Any]:
    earnings_growth = _get_indicator(indicators, "EPS Diluted Growth TTM YoY", "earnings_growth", "EPS growth")
    revenue_growth = _get_indicator(indicators, "Revenue Growth TTM YoY", "revenue_growth", "Revenue growth")
    values = {"earnings_growth": earnings_growth, "revenue_growth": revenue_growth}
    parts = []
    reasons = []
    if earnings_growth is not None:
        score = _clamp01((earnings_growth + 20.0) / 60.0)
        parts.append(score)
        if earnings_growth > 0:
            reasons.append(f"กำไรเติบโตเป็นบวก ({earnings_growth:.2f}%)")
    if revenue_growth is not None:
        score = _clamp01((revenue_growth + 10.0) / 50.0)
        parts.append(score)
        if revenue_growth > 0:
            reasons.append(f"รายได้เติบโตเป็นบวก ({revenue_growth:.2f}%)")
    score = sum(parts) / len(parts) if parts else 0.50
    return {"score": round(score, 4), "values": values, "reasons": reasons}


def _momentum_score(summary: Dict[str, Any], indicator_score: float, relative_strength: float, sector_score: float) -> float:
    recommendation = str(summary.get("RECOMMENDATION", "HOLD")).upper()
    if recommendation == "STRONG_BUY":
        base = 0.90
    elif recommendation == "BUY":
        base = 0.72
    elif recommendation in {"NEUTRAL", "HOLD"}:
        base = 0.50
    elif recommendation == "SELL":
        base = 0.25
    else:
        base = 0.10
    return _clamp01((base * 0.38) + (indicator_score * 0.32) + (relative_strength * 0.18) + (sector_score * 0.12))


def _risk_score(summary: Dict[str, Any], indicator_values: Dict[str, Any]) -> float:
    sell_count = float(summary.get("SELL", 0) or 0)
    buy_count = float(summary.get("BUY", 0) or 0)
    neutral_count = float(summary.get("NEUTRAL", 0) or 0)
    total = sell_count + buy_count + neutral_count
    sell_pressure = sell_count / total if total else 0.0
    vote_risk = 1.0 - sell_pressure
    atr_pct = indicator_values.get("atr_pct")
    atr_risk = 0.70
    if isinstance(atr_pct, (int, float)):
        atr_risk = 0.80 if atr_pct <= 0.04 else 0.55 if atr_pct <= 0.08 else 0.30
    return _clamp01((vote_risk * 0.70) + (atr_risk * 0.30))


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


def _build_reasons(symbol: str, raw_recommendation: str, scores: Dict[str, float], reason_groups: List[str]) -> List[str]:
    reasons = []
    if raw_recommendation in {"BUY", "STRONG_BUY"}:
        reasons.append(f"{symbol} มีสัญญาณเทคนิคจาก TradingView เป็น {raw_recommendation}")
    if scores["prefilter_score"] >= 0.65:
        reasons.append("ผ่าน Pre-filter ด้านสภาพคล่องและขนาดกิจการ")
    if scores["sector_rotation_score"] >= 0.65:
        reasons.append("Sector Rotation สนับสนุนหุ้นตัวนี้")
    if scores["fundamental_score"] >= 0.65:
        reasons.append("คะแนนพื้นฐานจาก Yahoo Finance สนับสนุนการคัดเลือก")
    if scores["indicator_score"] >= 0.70:
        reasons.append("อินดิเคเตอร์หลักโดยรวมเป็นบวก")
    if scores["relative_strength_score"] >= 0.60:
        reasons.append("Relative Strength ดีกว่าค่าเฉลี่ย")
    if scores["growth_score"] >= 0.60:
        reasons.append("ข้อมูลการเติบโตสนับสนุนการคัดเลือก")
    if scores["backtest_score"] >= 0.65:
        reasons.append("Backtest ย้อนหลังสนับสนุนสัญญาณนี้")
    if scores["risk_score"] >= 0.70:
        reasons.append("ความเสี่ยงเชิงเทคนิคยังอยู่ในระดับควบคุมได้")
    reasons.extend(reason_groups)
    if not reasons:
        reasons.append("ผ่านการคัดกรองเบื้องต้น แต่สัญญาณยังไม่แข็งแรงมาก")
    return reasons[:26]


def _rank_candidate(symbol: str, analysis: Dict[str, Any], indicators: Dict[str, Any], prefilter_data: Optional[Dict[str, Any]] = None) -> Candidate:
    prefilter_data = prefilter_data or {}
    raw_recommendation = str(analysis.get("RECOMMENDATION", "HOLD")).upper()
    vote_score = _technical_score(analysis)
    indicator_result = _indicator_score(indicators)
    relative_result = _relative_strength_score(indicators)
    growth_result = _growth_score(indicators)
    backtest_result = get_backtest_result(symbol)
    backtest_metadata = result_to_metadata(backtest_result)
    fundamental_result = get_fundamental_score(symbol)
    fundamental_metadata = fundamental_to_metadata(fundamental_result)
    sector_result = get_sector_rotation_score(symbol)
    sector_metadata = sector_to_metadata(sector_result)
    prefilter_score = float(prefilter_data.get("prefilter_score", 0.50) or 0.50)

    momentum = _momentum_score(
        analysis,
        indicator_result["score"],
        relative_result["score"],
        sector_result.score,
    )
    risk = _risk_score(analysis, indicator_result["values"])
    final_score = _clamp01(
        (prefilter_score * 0.05)
        + (vote_score * 0.14)
        + (indicator_result["score"] * 0.18)
        + (momentum * 0.11)
        + (relative_result["score"] * 0.07)
        + (sector_result.score * 0.10)
        + (growth_result["score"] * 0.05)
        + (backtest_result.score * 0.12)
        + (fundamental_result.score * 0.13)
        + (risk * 0.05)
    )
    recommendation = _rank_recommendation(final_score)

    scores = {
        "prefilter_score": round(prefilter_score, 4),
        "technical_vote_score": round(vote_score, 4),
        "indicator_score": round(indicator_result["score"], 4),
        "momentum_score": round(momentum, 4),
        "relative_strength_score": round(relative_result["score"], 4),
        "sector_rotation_score": round(sector_result.score, 4),
        "growth_score": round(growth_result["score"], 4),
        "backtest_score": round(backtest_result.score, 4),
        "fundamental_score": round(fundamental_result.score, 4),
        "risk_score": round(risk, 4),
        "final_score": round(final_score, 4),
    }

    details = {
        **analysis,
        **scores,
        "raw_recommendation": raw_recommendation,
        "recommendation": recommendation,
        "scanner_v48": {
            "prefilter": prefilter_data,
            "indicator_values": indicator_result["values"],
            "relative_strength_values": relative_result["values"],
            "sector_rotation": sector_metadata,
            "growth_values": growth_result["values"],
            "backtest": backtest_metadata,
            "fundamental": fundamental_metadata,
        },
        "reason": _build_reasons(
            symbol,
            raw_recommendation,
            {k: float(v) for k, v in scores.items()},
            list(prefilter_data.get("reason", []))
            + sector_result.reason
            + indicator_result["reasons"]
            + relative_result["reasons"]
            + growth_result["reasons"]
            + backtest_result.reason
            + fundamental_result.reason,
        ),
    }
    return Candidate(symbol=symbol, recommendation=recommendation, details=details)


def fetch_analysis(symbol: str, screener: str, exchange: str) -> Dict[str, Any]:
    """Fetches technical analysis and indicators for a single stock symbol."""
    try:
        handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=Interval.INTERVAL_1_DAY)
        analysis_obj = handler.get_analysis()
        return {"symbol": symbol, "analysis": analysis_obj.summary or {}, "indicators": analysis_obj.indicators or {}}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def scan_market(symbols: List[str], screener: str = "america", exchange: str = "NASDAQ") -> Tuple[List[Candidate], List[ErrorDetail]]:
    """
    Scanner V4.8: loads a broad universe, pre-filters by liquidity/market cap/price,
    then ranks candidates using TradingView indicators, relative strength, sector rotation,
    growth, backtest, Yahoo Finance fundamentals, and risk.
    """
    raw_symbols = resolve_universe(symbols, screener=screener, exchange=exchange)
    symbols_to_scan = raw_symbols
    prefilter_metadata: Dict[str, Dict[str, Any]] = {}
    explicit_symbols_provided = bool(symbols)
    is_us_market = screener.lower() == "america" and exchange.upper() != "SET"
    if is_us_market and not explicit_symbols_provided:
        filtered_symbols, prefilter_metadata = prefilter_symbols(raw_symbols)
        symbols_to_scan = filtered_symbols or raw_symbols[:250]

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
                    candidate = _rank_candidate(symbol, result.get("analysis", {}), result.get("indicators", {}), prefilter_metadata.get(symbol, {}))
                    final_score = float(candidate.details.get("final_score", 0.0))
                    if candidate.recommendation in ["BUY", "STRONG_BUY"] and final_score >= 0.62:
                        candidates.append(candidate)
            except Exception as e:
                errors.append(ErrorDetail(symbol=symbol, error=str(e)))
    candidates.sort(key=lambda c: c.details.get("final_score", 0.0), reverse=True)
    return candidates[:10], errors
