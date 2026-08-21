from __future__ import annotations

import math
from typing import Any, Dict, Optional


OPPORTUNITY_PROFILE_SCHEMA_VERSION = "scanner-opportunity-profile.v1"
LIQUID_DOLLAR_VOLUME_THRESHOLD = 10_000_000.0
LIQUID_SPREAD_SANITY_MAX_BPS = 50.0
HARD_SPREAD_SANITY_MAX_BPS = 500.0


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


def _trend_score(
    value: Optional[float],
    return_20d: Optional[float],
    return_60d: Optional[float],
) -> float:
    if value is not None:
        return _clamp01(value)
    observed = [item for item in (return_20d, return_60d) if item is not None]
    if not observed:
        return 0.0
    average = sum(observed) / len(observed)
    if abs(average) > 2:
        average /= 100.0
    return _clamp01(0.5 + average * 2.5)


def _breakout_score(
    close: Optional[float],
    high_52w: Optional[float],
    volume_score: float,
    trend_score: float,
) -> float:
    proximity = 0.0
    if close is not None and high_52w is not None and close > 0 and high_52w > 0:
        ratio = close / high_52w
        proximity = _clamp01((ratio - 0.80) / 0.20)
    return _clamp01(
        (proximity * 0.45) + (volume_score * 0.30) + (trend_score * 0.25)
    )


def _mean_reversion_score(
    rsi: Optional[float],
    atr_score: float,
    spread_score: float,
) -> float:
    if rsi is None:
        rsi_score = 0.0
    elif 25 <= rsi <= 45:
        rsi_score = 1.0
    elif 20 <= rsi <= 55:
        rsi_score = 0.65
    else:
        rsi_score = 0.2
    return _clamp01(
        (rsi_score * 0.55) + (atr_score * 0.25) + (spread_score * 0.20)
    )


def _relative_volume(
    *,
    indicators: Dict[str, Any],
    market_rank: Dict[str, Any],
    market: Dict[str, Any],
    average_volume: Optional[float],
) -> Optional[float]:
    direct = _first_number(
        indicators.get("volume_ratio"),
        market_rank.get("volume_ratio"),
    )
    if direct is not None:
        return direct
    current_volume = _first_number(
        indicators.get("volume"),
        market.get("regularMarketVolume"),
    )
    if current_volume is not None and average_volume is not None and average_volume > 0:
        return current_volume / average_volume
    return None


def _spread_sanity(
    *,
    dollar_volume: Optional[float],
    spread_bps: Optional[float],
    bid: Optional[float],
    ask: Optional[float],
) -> tuple[bool, bool, list[str]]:
    reasons: list[str] = []
    structural_valid = True
    liquid_bound_valid = True

    if spread_bps is not None and (spread_bps < 0 or spread_bps > HARD_SPREAD_SANITY_MAX_BPS):
        structural_valid = False
        reasons.append("spread_structurally_invalid")
    if bid is not None and bid <= 0:
        structural_valid = False
        reasons.append("bid_invalid")
    if ask is not None and ask <= 0:
        structural_valid = False
        reasons.append("ask_invalid")
    if bid is not None and ask is not None and ask < bid:
        structural_valid = False
        reasons.append("crossed_quote_invalid")

    if (
        structural_valid
        and dollar_volume is not None
        and dollar_volume >= LIQUID_DOLLAR_VOLUME_THRESHOLD
        and spread_bps is not None
        and spread_bps > LIQUID_SPREAD_SANITY_MAX_BPS
    ):
        liquid_bound_valid = False
        reasons.append("liquid_spread_out_of_bounds")

    return structural_valid, liquid_bound_valid, reasons


def build_opportunity_profile(data_bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Build non-binding execution-aware opportunity evidence from an existing bundle.

    Quote freshness and the US regular session are evidence states rather than
    workflow errors. Closed/stale evidence is routed to review. Structurally invalid
    or critically incomplete evidence fails closed.
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
    bid = _finite(market.get("alpacaBidPrice"))
    ask = _finite(market.get("alpacaAskPrice"))

    atr_pct = _first_number(
        indicators.get("atr_pct"),
        market_rank.get("atr_pct"),
    )
    if atr_pct is None:
        atr = _finite(indicators.get("atr"))
        if atr is not None and current_price is not None and current_price > 0:
            atr_pct = atr / current_price

    volume_ratio = _relative_volume(
        indicators=indicators,
        market_rank=market_rank,
        market=market,
        average_volume=average_volume,
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

    quote_quality = market.get("quote_quality") or {}
    quote_status = str(
        market.get("quoteQualityStatus")
        or quote_quality.get("status")
        or "unverified"
    ).strip().lower()
    market_session = str(
        market.get("usMarketSession")
        or quote_quality.get("market_session")
        or "unverified"
    ).strip().lower()
    quote_timestamp = market.get("alpacaQuoteTimestamp")
    quote_age_seconds = _finite(
        market.get("alpacaQuoteAgeSeconds")
        if market.get("alpacaQuoteAgeSeconds") is not None
        else quote_quality.get("quote_age_seconds")
    )

    structural_spread_valid, liquid_spread_valid, spread_reasons = _spread_sanity(
        dollar_volume=dollar_volume,
        spread_bps=spread_bps,
        bid=bid,
        ask=ask,
    )

    critical = current_price is not None and dollar_volume is not None
    evidence_complete = atr_pct is not None and volume_ratio is not None
    quote_blocks_qualification = quote_status in {
        "market_closed",
        "stale_quote",
        "missing_quote_timestamp",
    }
    fail_closed = not critical or not structural_spread_valid

    if fail_closed:
        status = "avoid"
        workflow_status = "fail_closed"
    elif quote_status == "market_closed":
        status = "review"
        workflow_status = "market_closed"
    elif quote_status in {"stale_quote", "missing_quote_timestamp"}:
        status = "review"
        workflow_status = "stale_quote"
    elif not evidence_complete or not liquid_spread_valid:
        status = "review"
        workflow_status = "evidence_review"
    elif score >= 0.70:
        status = "qualified"
        workflow_status = "ready"
    elif score >= 0.50:
        status = "review"
        workflow_status = "evidence_review"
    else:
        status = "avoid"
        workflow_status = "weak_opportunity"

    high_52w = _first_number(
        market.get("fiftyTwoWeekHigh"),
        indicators.get("high_52w"),
    )
    rsi = _finite(indicators.get("rsi"))
    trend_affinity = _clamp01(
        (normalized_trend * 0.55)
        + (relative_volume * 0.20)
        + (volatility * 0.15)
        + (spread * 0.10)
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

    reasons = list(spread_reasons)
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
    if volume_ratio is None:
        reasons.append("missing_relative_volume")
    if quality_score < 0.60:
        reasons.append("low_data_coverage")
    if normalized_trend >= 0.70:
        reasons.append("strong_trend")
    if relative_volume >= 0.80:
        reasons.append("strong_relative_volume")
    if quote_status == "market_closed":
        reasons.append("market_closed")
    elif quote_status == "stale_quote":
        reasons.append("stale_quote")
    elif quote_status == "missing_quote_timestamp":
        reasons.append("missing_quote_timestamp")

    evidence_flags = {
        "atr_available": atr_pct is not None,
        "relative_volume_available": volume_ratio is not None,
        "spread_available": spread_bps is not None,
        "quote_timestamp_available": quote_timestamp is not None,
        "liquid_spread_sane": liquid_spread_valid,
        "spread_structurally_valid": structural_spread_valid,
    }
    evidence_values = [
        evidence_flags["atr_available"],
        evidence_flags["relative_volume_available"],
        evidence_flags["spread_available"],
        evidence_flags["quote_timestamp_available"],
    ]

    return {
        "schema_version": OPPORTUNITY_PROFILE_SCHEMA_VERSION,
        "status": status,
        "workflow_status": workflow_status,
        "opportunity_score": round(score, 4),
        "is_binding": False,
        "manager_decision_required": True,
        "fail_closed": fail_closed,
        "preferred_strategy_hint": preferred_strategy,
        "strategy_affinity": affinities,
        "execution_context": {
            "current_price": current_price,
            "average_volume": average_volume,
            "estimated_dollar_volume": (
                round(dollar_volume, 2) if dollar_volume is not None else None
            ),
            "bid": bid,
            "ask": ask,
            "spread_bps": spread_bps,
            "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
            "relative_volume": volume_ratio,
            "quote_timestamp": quote_timestamp,
            "quote_age_seconds": quote_age_seconds,
            "quote_status": quote_status,
            "market_session": market_session,
            "market_open": quote_quality.get("market_open", market.get("usMarketOpen")),
            "liquid_spread_sanity_max_bps": LIQUID_SPREAD_SANITY_MAX_BPS,
        },
        "evidence_quality": {
            **evidence_flags,
            "coverage_ratio": round(sum(evidence_values) / len(evidence_values), 4),
            "quote_blocks_qualification": quote_blocks_qualification,
        },
        "component_scores": {
            "trend": round(normalized_trend, 4),
            "liquidity": round(liquidity, 4),
            "spread": round(spread, 4),
            "relative_volume": round(relative_volume, 4),
            "volatility": round(volatility, 4),
            "data_quality": round(quality_score, 4),
        },
        "reasons": sorted(set(reasons)),
    }
