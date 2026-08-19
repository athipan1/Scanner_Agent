from __future__ import annotations

import math
from typing import Any, Dict, Optional


OPPORTUNITY_PROFILE_SCHEMA_VERSION = "scanner-opportunity-profile.v1"


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _finite(value)
        if number is not None:
            return number
    return None


def _liquidity_score(dollar_volume: Optional[float]) -> float:
    if dollar_volume is None or dollar_volume <= 0:
        return 0.0
    if dollar_volume >= 50_000_000:
        return 1.0
    if dollar_volume >= 20_000_000:
        return 0.9
    if dollar_volume >= 10_000_000:
        return 0.8
    if dollar_volume >= 5_000_000:
        return 0.65
    if dollar_volume >= 1_000_000:
        return 0.4
    return 0.2


def _spread_score(spread_bps: Optional[float]) -> float:
    if spread_bps is None or spread_bps < 0:
        return 0.0
    if spread_bps <= 5:
        return 1.0
    if spread_bps <= 10:
        return 0.9
    if spread_bps <= 20:
        return 0.75
    if spread_bps <= 40:
        return 0.5
    if spread_bps <= 75:
        return 0.25
    return 0.05


def _volatility_score(atr_pct: Optional[float]) -> float:
    if atr_pct is None or atr_pct <= 0:
        return 0.0
    if 0.01 <= atr_pct <= 0.04:
        return 1.0
    if 0.005 <= atr_pct <= 0.06:
        return 0.8
    if atr_pct <= 0.08:
        return 0.55
    if atr_pct <= 0.12:
        return 0.25
    return 0.05


def _relative_volume_score(volume_ratio: Optional[float]) -> float:
    if volume_ratio is None or volume_ratio < 0:
        return 0.0
    if volume_ratio >= 1.5:
        return 1.0
    if volume_ratio >= 1.1:
        return 0.8
    if volume_ratio >= 0.8:
        return 0.55
    return 0.25


def _trend_score(value: Optional[float], return_20d: Optional[float], return_60d: Optional[float]) -> float:
    if value is not None:
        # Market ranker already emits a normalized score in current Scanner V5.
        return _clamp01(value)
    observed = [item for item in (return_20d, return_60d) if item is not None]
    if not observed:
        return 0.0
    # Returns may be ratios or percentages depending on provider. Keep this only as
    # a conservative fallback and cap the contribution.
    average = sum(observed) / len(observed)
    if abs(average) > 2:
        average /= 100.0
    return _clamp01(0.5 + average * 2.5)


def _breakout_score(close: Optional[float], high_52w: Optional[float], volume_score: float, trend_score: float) -> float:
    proximity = 0.0
    if close is not None and high_52w is not None and close > 0 and high_52w > 0:
        ratio = close / high_52w
        proximity = _clamp01((ratio - 0.80) / 0.20)
    return _clamp01((proximity * 0.45) + (volume_score * 0.30) + (trend_score * 0.25))


def _mean_reversion_score(rsi: Optional[float], atr_score: float, spread_score: float) -> float:
    if rsi is None:
        rsi_score = 0.0
    elif 25 <= rsi <= 45:
        rsi_score = 1.0
    elif 20 <= rsi <= 55:
        rsi_score = 0.65
    else:
        rsi_score = 0.2
    return _clamp01((rsi_score * 0.55) + (atr_score * 0.25) + (spread_score * 0.20))


def build_opportunity_profile(data_bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Build non-binding execution-aware opportunity evidence from an existing bundle.

    This function never fetches data and never changes Scanner ranking. It turns
    already-collected market, technical and quality evidence into an auditable
    profile that Manager_Agent can use for strategy routing and abstention.
    """

    market = data_bundle.get("market_snapshot") or {}
    technical = data_bundle.get("technical") or {}
    indicators = technical.get("indicator_values") or {}
    market_rank = data_bundle.get("market_rank") or {}
    quality = data_bundle.get("data_quality") or {}

    current_price = _first_number(
        market.get("currentPrice"),
        market_rank.get("price"),
        indicators.get("close"),
    )
    average_volume = _first_number(
        market.get("averageVolume"),
        market.get("averageVolume10days"),
    )
    dollar_volume = (
        current_price * average_volume
        if current_price is not None and average_volume is not None
        else None
    )
    spread_bps = _finite(market.get("alpacaSpreadBps"))
    atr_pct = _first_number(
        indicators.get("atr_pct"),
        market_rank.get("atr_pct"),
    )
    if atr_pct is None:
        atr = _finite(indicators.get("atr"))
        if atr is not None and current_price is not None and current_price > 0:
            atr_pct = atr / current_price
    volume_ratio = _first_number(
        indicators.get("volume_ratio"),
        market_rank.get("volume_ratio"),
    )
    return_20d = _finite(market_rank.get("return_20d"))
    return_60d = _finite(market_rank.get("return_60d"))
    normalized_trend = _trend_score(
        _finite(market_rank.get("trend_score")),
        return_20d,
        return_60d,
    )
    liquidity = _liquidity_score(dollar_volume)
    spread = _spread_score(spread_bps)
    volatility = _volatility_score(atr_pct)
    relative_volume = _relative_volume_score(volume_ratio)
    quality_score = _clamp01(float(quality.get("coverage_ratio") or 0.0))

    score = _clamp01(
        (normalized_trend * 0.25)
        + (liquidity * 0.20)
        + (spread * 0.15)
        + (relative_volume * 0.15)
        + (volatility * 0.15)
        + (quality_score * 0.10)
    )
    critical = current_price is not None and dollar_volume is not None
    if score >= 0.70 and critical:
        status = "qualified"
    elif score >= 0.50 and critical:
        status = "review"
    else:
        status = "avoid"

    high_52w = _first_number(
        market.get("fiftyTwoWeekHigh"),
        indicators.get("high_52w"),
    )
    rsi = _finite(indicators.get("rsi"))
    trend_affinity = _clamp01(
        (normalized_trend * 0.55) + (relative_volume * 0.20) + (volatility * 0.15) + (spread * 0.10)
    )
    breakout_affinity = _breakout_score(
        current_price,
        high_52w,
        relative_volume,
        normalized_trend,
    )
    mean_reversion_affinity = _mean_reversion_score(rsi, volatility, spread)
    affinities = {
        "trend_following": round(trend_affinity, 4),
        "breakout": round(breakout_affinity, 4),
        "mean_reversion": round(mean_reversion_affinity, 4),
    }
    preferred_strategy = max(affinities, key=affinities.get) if critical else None

    reasons = []
    if dollar_volume is None:
        reasons.append("missing_dollar_volume")
    elif dollar_volume < 5_000_000:
        reasons.append("low_dollar_volume")
    if spread_bps is None:
        reasons.append("missing_live_spread")
    elif spread_bps > 40:
        reasons.append("wide_spread")
    if atr_pct is None:
        reasons.append("missing_atr")
    elif atr_pct > 0.08:
        reasons.append("high_volatility")
    if quality_score < 0.60:
        reasons.append("low_data_coverage")
    if normalized_trend >= 0.70:
        reasons.append("strong_trend")
    if relative_volume >= 0.80:
        reasons.append("strong_relative_volume")

    return {
        "schema_version": OPPORTUNITY_PROFILE_SCHEMA_VERSION,
        "status": status,
        "opportunity_score": round(score, 4),
        "is_binding": False,
        "manager_decision_required": True,
        "preferred_strategy_hint": preferred_strategy,
        "strategy_affinity": affinities,
        "execution_context": {
            "current_price": current_price,
            "average_volume": average_volume,
            "estimated_dollar_volume": round(dollar_volume, 2) if dollar_volume is not None else None,
            "spread_bps": spread_bps,
            "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
            "relative_volume": volume_ratio,
        },
        "component_scores": {
            "trend": round(normalized_trend, 4),
            "liquidity": round(liquidity, 4),
            "spread": round(spread, 4),
            "relative_volume": round(relative_volume, 4),
            "volatility": round(volatility, 4),
            "data_quality": round(quality_score, 4),
        },
        "reasons": reasons,
    }
