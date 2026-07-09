from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


CONTROLLED_BUCKETS = ("core_dividend", "value_rebound", "news_momentum")
BUCKET_HINT_VERSION = "scanner-bucket-hints-v2"
PRIMARY_HINT_THRESHOLD = 0.65
REVIEW_HINT_THRESHOLD = 0.50
CONFLICT_SCORE_THRESHOLD = 0.60
CONFLICT_MARGIN = 0.10


def _num(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _cap01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _score01(value: Any) -> float:
    number = _num(value, 0.0) or 0.0
    if abs(number) > 1.0:
        number = number / 100.0
    return _cap01(number)


def _growth_decimal(value: Any) -> float:
    number = _num(value, 0.0) or 0.0
    if abs(number) > 2.0:
        number = number / 100.0
    return max(-1.0, min(2.0, number))


def _yield_decimal(value: Any) -> float:
    number = _num(value, 0.0) or 0.0
    if abs(number) > 1.0:
        number = number / 100.0
    return max(0.0, min(0.25, number))


def _debt_ratio(value: Any) -> Optional[float]:
    number = _num(value, None)
    if number is None:
        return None
    if number > 10.0:
        number = number / 100.0
    return max(0.0, number)


def _append(evidence: Dict[str, List[str]], bucket: str, reason: str) -> None:
    if reason not in evidence[bucket]:
        evidence[bucket].append(reason)


def _first_value(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _status_and_primary(
    bucket_scores: Dict[str, float],
) -> Tuple[str, Optional[str], float, float]:
    ordered = sorted(CONTROLLED_BUCKETS, key=lambda bucket: (-bucket_scores[bucket], bucket))
    primary = ordered[0]
    top_score = bucket_scores[primary]
    second_score = bucket_scores[ordered[1]]
    margin = round(top_score - second_score, 4)

    if (
        top_score >= CONFLICT_SCORE_THRESHOLD
        and second_score >= CONFLICT_SCORE_THRESHOLD
        and margin < CONFLICT_MARGIN
    ):
        return "conflict", None, top_score, margin
    if top_score >= PRIMARY_HINT_THRESHOLD and margin >= CONFLICT_MARGIN:
        return "suggested", primary, top_score, margin
    if top_score >= REVIEW_HINT_THRESHOLD:
        return "review", None, top_score, margin
    return "insufficient_evidence", None, top_score, margin


def build_strategy_bucket_hints(
    raw_scores: Dict[str, Any],
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build versioned, non-binding strategy-bucket evidence for Manager_Agent.

    Scanner_Agent never assigns the final portfolio bucket. It emits only
    controlled-vocabulary hints, scores, and auditable evidence. Ambiguous or
    weak evidence abstains from emitting a primary hint.
    """
    raw_scores = dict(raw_scores or {})
    metadata = dict(metadata or {})

    quality = _score01(raw_scores.get("quality_score"))
    valuation = _score01(raw_scores.get("valuation_score"))
    growth = _score01(raw_scores.get("growth_score"))
    fundamental = _score01(raw_scores.get("fundamental_score"))
    momentum = _score01(raw_scores.get("momentum_score"))
    relative_strength = _score01(raw_scores.get("relative_strength_score"))
    indicator = _score01(raw_scores.get("indicator_score"))
    technical_vote = _score01(raw_scores.get("technical_vote_score"))
    sector_rotation = _score01(raw_scores.get("sector_rotation_score"))

    pe = _num(_first_value(raw_scores, ("pe_ratio", "trailing_pe", "forward_pe")), None)
    pb = _num(raw_scores.get("pb_ratio"), None)
    debt_to_equity = _debt_ratio(raw_scores.get("debt_to_equity"))
    free_cash_flow = _num(raw_scores.get("free_cash_flow"), None)
    dividend_yield = _yield_decimal(raw_scores.get("dividend_yield"))
    volume_ratio = _num(raw_scores.get("volume_ratio"), None)
    breakout_ratio = _num(raw_scores.get("breakout_ratio"), None)

    growth_values = [
        _growth_decimal(raw_scores.get("fcf_growth")),
        _growth_decimal(raw_scores.get("fcf_3y_cagr")),
        _growth_decimal(raw_scores.get("revenue_growth")),
        _growth_decimal(raw_scores.get("revenue_3y_cagr")),
        _growth_decimal(raw_scores.get("earnings_growth")),
        _growth_decimal(raw_scores.get("eps_growth")),
    ]
    strongest_growth = max([0.0, *growth_values])

    sector = str(metadata.get("sector") or "").strip().lower()
    evidence: Dict[str, List[str]] = {bucket: [] for bucket in CONTROLLED_BUCKETS}

    defensive_sector = any(
        key in sector
        for key in (
            "consumer defensive",
            "consumer staples",
            "staples",
            "utilities",
            "healthcare",
            "financial services",
        )
    )
    defensive_sector_bonus = 0.10 if defensive_sector else 0.0
    if defensive_sector:
        _append(evidence, "core_dividend", f"defensive_or_income_sector:{sector}")

    positive_fcf_bonus = 0.10 if free_cash_flow is not None and free_cash_flow > 0 else 0.0
    if positive_fcf_bonus:
        _append(evidence, "core_dividend", "positive_free_cash_flow")
        _append(evidence, "value_rebound", "positive_free_cash_flow")

    low_debt_bonus = 0.08 if debt_to_equity is not None and debt_to_equity <= 1.0 else 0.0
    if low_debt_bonus:
        _append(evidence, "core_dividend", f"debt_to_equity:{debt_to_equity:.4f}")

    dividend_bonus = min(0.14, dividend_yield * 4.0) if dividend_yield > 0 else 0.0
    if dividend_bonus:
        _append(evidence, "core_dividend", f"dividend_yield:{dividend_yield:.4f}")

    cheap_pe_bonus = 0.0
    if pe is not None and pe > 0:
        if pe <= 15:
            cheap_pe_bonus = 0.16
        elif pe <= 20:
            cheap_pe_bonus = 0.10
        elif pe <= 25:
            cheap_pe_bonus = 0.05
        if cheap_pe_bonus:
            _append(evidence, "value_rebound", f"pe_ratio:{pe:.4f}")

    cheap_pb_bonus = 0.0
    if pb is not None and pb > 0:
        if pb <= 1.5:
            cheap_pb_bonus = 0.12
        elif pb <= 2.5:
            cheap_pb_bonus = 0.08
        if cheap_pb_bonus:
            _append(evidence, "value_rebound", f"pb_ratio:{pb:.4f}")

    growth_bonus = min(0.18, strongest_growth * 0.22)
    if strongest_growth > 0:
        _append(evidence, "news_momentum", f"strongest_growth_metric:{strongest_growth:.4f}")

    volume_bonus = 0.0
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            volume_bonus = 0.08
        elif volume_ratio >= 1.1:
            volume_bonus = 0.04
        if volume_bonus:
            _append(evidence, "news_momentum", f"volume_ratio:{volume_ratio:.4f}")

    breakout_bonus = 0.0
    if breakout_ratio is not None:
        if breakout_ratio >= 0.98:
            breakout_bonus = 0.07
        elif breakout_ratio >= 0.90:
            breakout_bonus = 0.03
        if breakout_bonus:
            _append(evidence, "news_momentum", f"breakout_ratio:{breakout_ratio:.4f}")

    if quality > 0:
        _append(evidence, "core_dividend", f"quality_score:{quality:.4f}")
        _append(evidence, "value_rebound", f"quality_support:{quality:.4f}")
    if valuation > 0:
        _append(evidence, "value_rebound", f"valuation_score:{valuation:.4f}")
    if growth > 0:
        _append(evidence, "news_momentum", f"growth_score:{growth:.4f}")
    if momentum > 0:
        _append(evidence, "news_momentum", f"momentum_score:{momentum:.4f}")
    if relative_strength > 0:
        _append(evidence, "news_momentum", f"relative_strength_score:{relative_strength:.4f}")

    bucket_scores = {
        "core_dividend": round(
            _cap01(
                (quality * 0.45)
                + (fundamental * 0.12)
                + positive_fcf_bonus
                + low_debt_bonus
                + defensive_sector_bonus
                + dividend_bonus
            ),
            4,
        ),
        "value_rebound": round(
            _cap01(
                (valuation * 0.50)
                + (quality * 0.10)
                + (fundamental * 0.05)
                + cheap_pe_bonus
                + cheap_pb_bonus
                + (positive_fcf_bonus * 0.5)
            ),
            4,
        ),
        "news_momentum": round(
            _cap01(
                (growth * 0.55)
                + (momentum * 0.15)
                + (relative_strength * 0.08)
                + (indicator * 0.05)
                + (technical_vote * 0.05)
                + (sector_rotation * 0.04)
                + growth_bonus
                + volume_bonus
                + breakout_bonus
            ),
            4,
        ),
    }

    status, primary_hint, top_score, margin = _status_and_primary(bucket_scores)
    ordered = sorted(CONTROLLED_BUCKETS, key=lambda bucket: (-bucket_scores[bucket], bucket))
    credible_hints = [bucket for bucket in ordered if bucket_scores[bucket] >= REVIEW_HINT_THRESHOLD]

    reasons: List[str] = []
    if status == "conflict":
        reasons.append("top_bucket_scores_are_too_close")
    elif status == "review":
        reasons.append("top_bucket_score_requires_manager_review")
    elif status == "insufficient_evidence":
        reasons.append("insufficient_bucket_evidence")
    elif primary_hint:
        reasons.append(f"primary_hint_supported:{primary_hint}")
    for bucket in ordered[:2]:
        reasons.extend(f"{bucket}:{reason}" for reason in evidence[bucket][:4])

    tags: List[str] = [f"bucket-hint-status:{status}"]
    if primary_hint:
        tags.append(f"bucket-hint:{primary_hint}")
    for bucket in credible_hints:
        tags.append(f"bucket-candidate:{bucket}")

    return {
        "bucket_hint_version": BUCKET_HINT_VERSION,
        "bucket_hint_status": status,
        "primary_strategy_bucket_hint": primary_hint,
        "primary_strategy_bucket_confidence": round(top_score, 4) if primary_hint else None,
        "strategy_bucket_confidence": round(top_score, 4),
        "strategy_bucket_hints": credible_hints,
        "bucket_hint_scores": bucket_scores,
        "bucket_hint_margin": margin,
        "bucket_hint_evidence": evidence,
        "bucket_hint_reasons": reasons,
        "bucket_hint_tags": tags,
        "bucket_hint_is_binding": False,
        "manager_decision_required": True,
        "controlled_strategy_buckets": list(CONTROLLED_BUCKETS),
        "bucket_hint_thresholds": {
            "primary": PRIMARY_HINT_THRESHOLD,
            "review": REVIEW_HINT_THRESHOLD,
            "conflict_score": CONFLICT_SCORE_THRESHOLD,
            "conflict_margin": CONFLICT_MARGIN,
        },
    }
