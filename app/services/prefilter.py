from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple

import yfinance as yf


@dataclass
class PrefilterResult:
    symbol: str
    passed: bool
    score: float
    price: Optional[float]
    avg_volume: Optional[float]
    market_cap: Optional[float]
    reason: List[str]


MIN_PRICE = 5.0
MIN_AVG_VOLUME = 500_000
MIN_MARKET_CAP = 1_000_000_000
MAX_SYMBOLS_AFTER_FILTER = 250


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=2048)
def evaluate_symbol(symbol: str) -> PrefilterResult:
    symbol = symbol.upper().strip()
    reasons: List[str] = []

    try:
        ticker = yf.Ticker(symbol)
        fast_info = getattr(ticker, "fast_info", {}) or {}
        info: Dict = {}
        try:
            info = ticker.get_info() or {}
        except Exception:
            info = {}

        price = _safe_float(
            fast_info.get("last_price")
            or fast_info.get("lastPrice")
            or info.get("currentPrice")
            or info.get("regularMarketPrice")
        )
        avg_volume = _safe_float(
            fast_info.get("ten_day_average_volume")
            or fast_info.get("three_month_average_volume")
            or info.get("averageVolume")
            or info.get("averageDailyVolume10Day")
        )
        market_cap = _safe_float(
            fast_info.get("market_cap")
            or info.get("marketCap")
        )

        quote_type = str(info.get("quoteType") or info.get("typeDisp") or "EQUITY").upper()
        if quote_type and quote_type not in {"EQUITY", "COMMON STOCK", "STOCK"}:
            reasons.append(f"ตัดออกเพราะประเภทสินทรัพย์ไม่ใช่หุ้นสามัญ ({quote_type})")
            return PrefilterResult(symbol, False, 0.0, price, avg_volume, market_cap, reasons)

        passed = True
        if price is not None and price < MIN_PRICE:
            passed = False
            reasons.append(f"ราคาต่ำกว่า ${MIN_PRICE:.0f}")
        elif price is not None:
            reasons.append(f"ราคาผ่านเกณฑ์ (${price:.2f})")

        if avg_volume is not None and avg_volume < MIN_AVG_VOLUME:
            passed = False
            reasons.append(f"Volume เฉลี่ยต่ำกว่า {MIN_AVG_VOLUME:,}")
        elif avg_volume is not None:
            reasons.append(f"Volume เฉลี่ยผ่านเกณฑ์ ({avg_volume:,.0f})")

        if market_cap is not None and market_cap < MIN_MARKET_CAP:
            passed = False
            reasons.append(f"Market Cap ต่ำกว่า ${MIN_MARKET_CAP:,.0f}")
        elif market_cap is not None:
            reasons.append(f"Market Cap ผ่านเกณฑ์ (${market_cap:,.0f})")

        if price is None and avg_volume is None and market_cap is None:
            passed = False
            reasons.append("ไม่มีข้อมูลราคา/Volume/Market Cap เพียงพอสำหรับ Pre-filter")

        price_score = _clamp01((price or 0) / 50.0) if price is not None else 0.50
        volume_score = _clamp01((avg_volume or 0) / 5_000_000.0) if avg_volume is not None else 0.50
        cap_score = _clamp01((market_cap or 0) / 50_000_000_000.0) if market_cap is not None else 0.50
        score = _clamp01((price_score * 0.20) + (volume_score * 0.45) + (cap_score * 0.35))

        return PrefilterResult(
            symbol=symbol,
            passed=passed,
            score=round(score, 4),
            price=price,
            avg_volume=avg_volume,
            market_cap=market_cap,
            reason=reasons,
        )
    except Exception as exc:
        return PrefilterResult(
            symbol=symbol,
            passed=False,
            score=0.0,
            price=None,
            avg_volume=None,
            market_cap=None,
            reason=[f"Pre-filter error: {exc}"],
        )


def prefilter_symbols(symbols: Iterable[str]) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    results = [evaluate_symbol(symbol) for symbol in symbols]
    passed_results = [result for result in results if result.passed]

    # Keep the most liquid/large names first to avoid downstream rate limits.
    passed_results.sort(key=lambda item: item.score, reverse=True)
    selected = passed_results[:MAX_SYMBOLS_AFTER_FILTER]

    metadata = {
        result.symbol: {
            "passed": result.passed,
            "prefilter_score": result.score,
            "price": result.price,
            "avg_volume": result.avg_volume,
            "market_cap": result.market_cap,
            "reason": result.reason,
        }
        for result in results
    }

    return [result.symbol for result in selected], metadata
