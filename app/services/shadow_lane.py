from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple


SHADOW_LANE_SCHEMA_VERSION = "scanner-shadow-lane.v2"
PRODUCTION_MIN_OPPORTUNITY_SCORE = 0.70
RESEARCH_MIN_OPPORTUNITY_SCORE = 0.50
RESEARCH_MAX_CANDIDATES = 20
_CRITICAL_PRODUCTION_FIELDS = (
    "current_price",
    "estimated_dollar_volume",
    "spread_bps",
    "atr_pct",
)
_RESEARCH_COMPONENT_WEIGHTS = {
    "trend": 0.30,
    "liquidity": 0.25,
    "relative_volume": 0.20,
    "volatility": 0.15,
    "data_quality": 0.10,
}


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidate_profile(candidate: Any) -> Dict[str, Any]:
    payload = _to_dict(candidate)
    metadata = _to_dict(payload.get("metadata"))
    details = _to_dict(metadata.get("details"))
    data_bundle = _to_dict(details.get("data_bundle"))
    profile = _to_dict(data_bundle.get("opportunity_profile"))
    if profile:
        return profile

    # Scanner contract candidates may carry the data bundle directly in metadata.
    data_bundle = _to_dict(metadata.get("data_bundle"))
    return _to_dict(data_bundle.get("opportunity_profile"))


def _research_opportunity_score(profile: Dict[str, Any]) -> float:
    """Score Shadow research without depending on live quote/spread availability.

    Production keeps the execution-aware opportunity score. Shadow research instead
    uses historical/slow-moving components and intentionally excludes live spread.
    Missing ATR or relative-volume evidence contributes zero rather than blocking the
    lane, so off-session discovery can still accumulate observations safely.
    """

    components = _to_dict(profile.get("component_scores"))
    if components:
        score = 0.0
        for name, weight in _RESEARCH_COMPONENT_WEIGHTS.items():
            value = _finite(components.get(name))
            if value is not None:
                score += max(0.0, min(1.0, value)) * weight
        return max(0.0, min(1.0, score))

    fallback = _finite(profile.get("opportunity_score"))
    if fallback is None:
        return -1.0
    return max(0.0, min(1.0, fallback))


def classify_candidate_lane(candidate: Any) -> Dict[str, Any]:
    """Classify a Scanner candidate without granting any execution authority.

    Production eligibility is deliberately strict and only means the candidate may
    continue to Manager's normal gates. Research eligibility is broader, uses
    historical evidence that is valid outside regular market hours, and is always
    shadow-only. Research candidates must never reach Risk/Execution as orders.
    """

    profile = _candidate_profile(candidate)
    if not profile:
        return {
            "schema_version": SHADOW_LANE_SCHEMA_VERSION,
            "lane": "blocked",
            "production_eligible": False,
            "research_eligible": False,
            "broker_order_authorized": False,
            "reason_codes": ["missing_opportunity_profile"],
        }

    status = str(profile.get("status") or "").strip().lower()
    production_score = _finite(profile.get("opportunity_score"))
    if production_score is None:
        production_score = -1.0
    research_score = _research_opportunity_score(profile)
    execution_context = _to_dict(profile.get("execution_context"))
    missing_production_fields = [
        field
        for field in _CRITICAL_PRODUCTION_FIELDS
        if execution_context.get(field) is None
    ]
    current_price = _finite(execution_context.get("current_price"))
    dollar_volume = _finite(execution_context.get("estimated_dollar_volume"))
    fail_closed = profile.get("fail_closed") is True

    production_eligible = (
        not fail_closed
        and status == "qualified"
        and production_score >= PRODUCTION_MIN_OPPORTUNITY_SCORE
        and not missing_production_fields
    )
    research_eligible = (
        not production_eligible
        and not fail_closed
        and research_score >= RESEARCH_MIN_OPPORTUNITY_SCORE
        and current_price is not None
        and current_price > 0
        and dollar_volume is not None
        and dollar_volume > 0
    )

    reason_codes: List[str] = []
    if fail_closed:
        reason_codes.append("opportunity_profile_fail_closed")
    if status not in {"qualified", "review"}:
        reason_codes.append(f"opportunity_status_{status or 'missing'}")
    if research_score < RESEARCH_MIN_OPPORTUNITY_SCORE:
        reason_codes.append("research_score_below_threshold")
    if current_price is None or current_price <= 0:
        reason_codes.append("research_missing_current_price")
    if dollar_volume is None or dollar_volume <= 0:
        reason_codes.append("research_missing_dollar_volume")
    if missing_production_fields:
        reason_codes.extend(
            f"production_missing_{field}" for field in missing_production_fields
        )
    if research_eligible and status == "avoid":
        reason_codes.append("research_historical_evidence_override")

    lane = (
        "production"
        if production_eligible
        else "research"
        if research_eligible
        else "blocked"
    )
    return {
        "schema_version": SHADOW_LANE_SCHEMA_VERSION,
        "lane": lane,
        "production_eligible": production_eligible,
        "research_eligible": research_eligible,
        "broker_order_authorized": False,
        "opportunity_score": production_score if production_score >= 0 else None,
        "research_opportunity_score": (
            round(research_score, 4) if research_score >= 0 else None
        ),
        "research_score_source": "historical_components",
        "reason_codes": reason_codes,
    }


def partition_candidates_by_lane(
    candidates: Iterable[Any],
) -> Tuple[List[Any], List[Any], Dict[str, Any]]:
    production: List[Any] = []
    research_ranked: List[tuple[int, float, Any]] = []
    blocked_count = 0
    reason_counts: Dict[str, int] = {}

    for index, candidate in enumerate(candidates):
        decision = classify_candidate_lane(candidate)
        if decision["lane"] == "production":
            production.append(candidate)
        elif decision["lane"] == "research":
            research_ranked.append(
                (
                    index,
                    float(decision.get("research_opportunity_score") or 0.0),
                    candidate,
                )
            )
        else:
            blocked_count += 1
        for code in decision.get("reason_codes") or []:
            reason_counts[code] = reason_counts.get(code, 0) + 1

    research_ranked.sort(key=lambda row: (-row[1], row[0]))
    research = [row[2] for row in research_ranked[:RESEARCH_MAX_CANDIDATES]]
    overflow_count = max(0, len(research_ranked) - len(research))
    if overflow_count:
        blocked_count += overflow_count
        reason_counts["research_top_k_overflow"] = overflow_count

    total = len(production) + len(research) + blocked_count
    return production, research, {
        "schema_version": SHADOW_LANE_SCHEMA_VERSION,
        "original_count": total,
        "production_count": len(production),
        "research_eligible_count_before_cap": len(research_ranked),
        "research_count": len(research),
        "research_overflow_count": overflow_count,
        "blocked_count": blocked_count,
        "production_min_opportunity_score": PRODUCTION_MIN_OPPORTUNITY_SCORE,
        "research_min_opportunity_score": RESEARCH_MIN_OPPORTUNITY_SCORE,
        "research_max_candidates": RESEARCH_MAX_CANDIDATES,
        "research_score_source": "historical_components",
        "research_execution_mode": "shadow",
        "research_broker_order_authorized": False,
        "reason_counts": reason_counts,
    }
