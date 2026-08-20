from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


SHADOW_LANE_SCHEMA_VERSION = "scanner-shadow-lane.v1"
PRODUCTION_MIN_OPPORTUNITY_SCORE = 0.70
RESEARCH_MIN_OPPORTUNITY_SCORE = 0.50
_CRITICAL_PRODUCTION_FIELDS = (
    "current_price",
    "estimated_dollar_volume",
    "spread_bps",
    "atr_pct",
)


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


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


def classify_candidate_lane(candidate: Any) -> Dict[str, Any]:
    """Classify a Scanner candidate without granting any execution authority.

    Production eligibility is deliberately strict and only means the candidate may
    continue to Manager's normal gates. Research eligibility is broader but is
    always shadow-only and therefore must never reach Risk/Execution as an order.
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
    try:
        score = float(profile.get("opportunity_score"))
    except (TypeError, ValueError):
        score = -1.0
    execution_context = _to_dict(profile.get("execution_context"))
    missing_production_fields = [
        field
        for field in _CRITICAL_PRODUCTION_FIELDS
        if execution_context.get(field) is None
    ]

    production_eligible = (
        status == "qualified"
        and score >= PRODUCTION_MIN_OPPORTUNITY_SCORE
        and not missing_production_fields
    )
    research_eligible = (
        not production_eligible
        and status in {"qualified", "review"}
        and score >= RESEARCH_MIN_OPPORTUNITY_SCORE
        and execution_context.get("current_price") is not None
        and execution_context.get("estimated_dollar_volume") is not None
    )

    reason_codes: List[str] = []
    if status not in {"qualified", "review"}:
        reason_codes.append(f"opportunity_status_{status or 'missing'}")
    if score < RESEARCH_MIN_OPPORTUNITY_SCORE:
        reason_codes.append("opportunity_score_below_research_threshold")
    if missing_production_fields:
        reason_codes.extend(
            f"production_missing_{field}" for field in missing_production_fields
        )

    lane = "production" if production_eligible else "research" if research_eligible else "blocked"
    return {
        "schema_version": SHADOW_LANE_SCHEMA_VERSION,
        "lane": lane,
        "production_eligible": production_eligible,
        "research_eligible": research_eligible,
        "broker_order_authorized": False,
        "opportunity_score": score if score >= 0 else None,
        "reason_codes": reason_codes,
    }


def partition_candidates_by_lane(
    candidates: Iterable[Any],
) -> Tuple[List[Any], List[Any], Dict[str, Any]]:
    production: List[Any] = []
    research: List[Any] = []
    blocked_count = 0
    reason_counts: Dict[str, int] = {}

    for candidate in candidates:
        decision = classify_candidate_lane(candidate)
        if decision["lane"] == "production":
            production.append(candidate)
        elif decision["lane"] == "research":
            research.append(candidate)
        else:
            blocked_count += 1
        for code in decision.get("reason_codes") or []:
            reason_counts[code] = reason_counts.get(code, 0) + 1

    total = len(production) + len(research) + blocked_count
    return production, research, {
        "schema_version": SHADOW_LANE_SCHEMA_VERSION,
        "original_count": total,
        "production_count": len(production),
        "research_count": len(research),
        "blocked_count": blocked_count,
        "production_min_opportunity_score": PRODUCTION_MIN_OPPORTUNITY_SCORE,
        "research_min_opportunity_score": RESEARCH_MIN_OPPORTUNITY_SCORE,
        "research_execution_mode": "shadow",
        "research_broker_order_authorized": False,
        "reason_counts": reason_counts,
    }
