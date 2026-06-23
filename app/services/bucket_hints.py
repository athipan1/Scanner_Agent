from __future__ import annotations

from typing import Any, Dict, List


BUCKETS = ("core_dividend", "value_rebound", "news_momentum")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _cap01(value: float) -> float:
    return max(0.0, min(1.0, value))


def build_strategy_bucket_hints(raw_scores: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build non-binding strategy bucket hints for Manager_Agent.

    Scanner does not make final portfolio allocation decisions. These hints only
    provide richer candidate context for Manager_Agent's existing bucket logic.
    """
    metadata = metadata or {}
    quality = _num(raw_scores.get("quality_score")) / 100.0
    valuation = _num(raw_scores.get("valuation_score")) / 100.0
    growth = _num(raw_scores.get("growth_score")) / 100.0
    fcf_growth = _num(raw_scores.get("fcf_growth"))
    revenue_growth = _num(raw_scores.get("revenue_3y_cagr"))
    pe = _num(raw_scores.get("pe_ratio"), default=999.0)
    pb = _num(raw_scores.get("pb_ratio"), default=999.0)
    debt_to_equity = _num(raw_scores.get("debt_to_equity"), default=999.0)
    free_cash_flow = _num(raw_scores.get("free_cash_flow"))
    sector = str(metadata.get("sector") or "").lower()

    defensive_sector_bonus = 0.10 if any(key in sector for key in ["consumer defensive", "utilities", "healthcare", "staples"]) else 0.0
    low_debt_bonus = 0.10 if debt_to_equity and debt_to_equity <= 1.0 else 0.0
    positive_fcf_bonus = 0.10 if free_cash_flow > 0 else 0.0
    cheap_pe_bonus = 0.12 if pe and pe <= 18 else 0.0
    cheap_pb_bonus = 0.08 if pb and pb <= 2.5 else 0.0
    growth_bonus = _cap01(max(fcf_growth, revenue_growth, 0.0)) * 0.20

    bucket_scores = {
        "core_dividend": round(_cap01((quality * 0.55) + positive_fcf_bonus + low_debt_bonus + defensive_sector_bonus), 4),
        "value_rebound": round(_cap01((valuation * 0.55) + cheap_pe_bonus + cheap_pb_bonus + (quality * 0.15)), 4),
        "news_momentum": round(_cap01((growth * 0.50) + growth_bonus + (quality * 0.10)), 4),
    }
    ordered = sorted(BUCKETS, key=lambda bucket: bucket_scores[bucket], reverse=True)

    tags: List[str] = [f"bucket-hint:{ordered[0]}"]
    if bucket_scores["core_dividend"] >= 0.55:
        tags.extend(["core-candidate", "quality-cashflow"])
    if bucket_scores["value_rebound"] >= 0.55:
        tags.extend(["value-candidate", "valuation-support"])
    if bucket_scores["news_momentum"] >= 0.55:
        tags.extend(["momentum-candidate", "growth-support"])

    return {
        "primary_strategy_bucket_hint": ordered[0],
        "strategy_bucket_hints": ordered,
        "bucket_hint_scores": bucket_scores,
        "bucket_hint_tags": tags,
    }
