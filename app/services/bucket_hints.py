from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


CONTROLLED_BUCKETS = ("core_dividend", "value_rebound", "news_momentum")
BUCKET_HINT_VERSION = "scanner-bucket-hints-v2"
BUCKET_HINT_POLICY_VERSION = "scanner-bucket-hint-policy-v3"
PRIMARY_HINT_THRESHOLD = 0.65
REVIEW_HINT_THRESHOLD = 0.50
CONFLICT_SCORE_THRESHOLD = PRIMARY_HINT_THRESHOLD
CONFLICT_MARGIN = 0.10
HARD_CONFLICT_MARGIN = 0.05


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
    """Normalize growth inputs that may arrive as decimal or percentage points.

    Scanner's broad-universe data commonly emits values such as ``1.1711`` for
    1.1711%, while evidence contracts use ``0.011711``. Treat magnitudes above
    one as percentage points so small reported growth is not mistaken for 117%.
    """
    number = _num(value, 0.0) or 0.0
    if abs(number) > 1.0:
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
    defining_evidence: Dict[str, List[str]],
    dominance_bucket: Optional[str],
) -> Tuple[str, Optional[str], float, float]:
    ordered = sorted(
        CONTROLLED_BUCKETS,
        key=lambda bucket: (-bucket_scores[bucket], bucket),
    )
    primary = ordered[0]
    top_score = bucket_scores[primary]
    second = ordered[1]
    second_score = bucket_scores[second]
    margin = round(top_score - second_score, 4)

    if (
        dominance_bucket == primary
        and top_score >= PRIMARY_HINT_THRESHOLD
    ):
        return "suggested", primary, top_score, margin

    top_is_defining = bool(defining_evidence[primary])
    second_is_defining = bool(defining_evidence[second])

    if (
        top_score >= CONFLICT_SCORE_THRESHOLD
        and second_score >= CONFLICT_SCORE_THRESHOLD
        and margin < HARD_CONFLICT_MARGIN
        and top_is_defining
        and second_is_defining
    ):
        return "conflict", None, top_score, margin

    if top_score >= PRIMARY_HINT_THRESHOLD:
        if margin >= CONFLICT_MARGIN:
            return "suggested", primary, top_score, margin
        if top_is_defining and not second_is_defining:
            return "suggested", primary, top_score, margin
        return "review", None, top_score, margin

    if top_score >= REVIEW_HINT_THRESHOLD:
        return "review", None, top_score, margin
    return "insufficient_evidence", None, top_score, margin


def build_strategy_bucket_hints(
    raw_scores: Dict[str, Any],
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build versioned, non-binding strategy-bucket evidence for Manager_Agent.

    Bucket-defining evidence is kept separate from broad supporting evidence.
    Scanner_Agent never assigns the final bucket and abstains when identity is
    weak. Generic quality, positive cash flow, or low debt alone cannot create
    a core/dividend identity.
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

    pe = _num(
        _first_value(
            raw_scores,
            ("pe_ratio", "trailing_pe", "forward_pe"),
        ),
        None,
    )
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
    defining: Dict[str, List[str]] = {
        bucket: [] for bucket in CONTROLLED_BUCKETS
    }
    supporting: Dict[str, List[str]] = {
        bucket: [] for bucket in CONTROLLED_BUCKETS
    }

    defensive_sector = any(
        key in sector
        for key in (
            "consumer defensive",
            "consumer staples",
            "staples",
            "utilities",
            "healthcare",
        )
    )
    defensive_sector_bonus = 0.12 if defensive_sector else 0.0
    if defensive_sector:
        _append(
            defining,
            "core_dividend",
            f"defensive_or_income_sector:{sector}",
        )

    positive_fcf = free_cash_flow is not None and free_cash_flow > 0
    positive_fcf_bonus = 0.06 if positive_fcf else 0.0
    if positive_fcf:
        _append(supporting, "core_dividend", "positive_free_cash_flow")
        _append(supporting, "value_rebound", "positive_free_cash_flow")

    low_debt = debt_to_equity is not None and debt_to_equity <= 1.0
    low_debt_bonus = 0.05 if low_debt else 0.0
    if low_debt:
        _append(
            supporting,
            "core_dividend",
            f"debt_to_equity:{debt_to_equity:.4f}",
        )

    dividend_bonus = (
        min(0.24, dividend_yield * 6.0)
        if dividend_yield > 0
        else 0.0
    )
    if dividend_yield > 0:
        _append(
            defining,
            "core_dividend",
            f"dividend_yield:{dividend_yield:.4f}",
        )

    cheap_pe_bonus = 0.0
    if pe is not None and pe > 0:
        if pe <= 15:
            cheap_pe_bonus = 0.20
        elif pe <= 20:
            cheap_pe_bonus = 0.12
        elif pe <= 25:
            cheap_pe_bonus = 0.06
        if cheap_pe_bonus:
            _append(defining, "value_rebound", f"pe_ratio:{pe:.4f}")

    cheap_pb_bonus = 0.0
    if pb is not None and pb > 0:
        if pb <= 1.5:
            cheap_pb_bonus = 0.12
        elif pb <= 2.5:
            cheap_pb_bonus = 0.08
        if cheap_pb_bonus:
            _append(defining, "value_rebound", f"pb_ratio:{pb:.4f}")

    if valuation >= 0.60:
        _append(
            defining,
            "value_rebound",
            f"valuation_score:{valuation:.4f}",
        )
    elif valuation > 0:
        _append(
            supporting,
            "value_rebound",
            f"valuation_support:{valuation:.4f}",
        )

    actual_growth_bonus = min(0.12, strongest_growth * 0.20)
    if strongest_growth >= 0.20:
        _append(
            defining,
            "news_momentum",
            f"strongest_growth_metric:{strongest_growth:.4f}",
        )
    elif strongest_growth > 0:
        _append(
            supporting,
            "news_momentum",
            f"growth_metric_support:{strongest_growth:.4f}",
        )

    if growth >= 0.65:
        _append(
            defining,
            "news_momentum",
            f"growth_score:{growth:.4f}",
        )
    elif growth > 0:
        _append(
            supporting,
            "news_momentum",
            f"growth_support:{growth:.4f}",
        )

    if momentum >= 0.65:
        _append(
            defining,
            "news_momentum",
            f"momentum_score:{momentum:.4f}",
        )
    elif momentum > 0:
        _append(
            supporting,
            "news_momentum",
            f"momentum_support:{momentum:.4f}",
        )

    volume_bonus = 0.0
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            volume_bonus = 0.06
            _append(
                defining,
                "news_momentum",
                f"volume_ratio:{volume_ratio:.4f}",
            )
        elif volume_ratio >= 1.1:
            volume_bonus = 0.03
            _append(
                supporting,
                "news_momentum",
                f"volume_ratio_support:{volume_ratio:.4f}",
            )

    breakout_bonus = 0.0
    if breakout_ratio is not None:
        if breakout_ratio >= 0.98:
            breakout_bonus = 0.05
            _append(
                defining,
                "news_momentum",
                f"breakout_ratio:{breakout_ratio:.4f}",
            )
        elif breakout_ratio >= 0.90:
            breakout_bonus = 0.02
            _append(
                supporting,
                "news_momentum",
                f"breakout_ratio_support:{breakout_ratio:.4f}",
            )

    if quality > 0:
        _append(
            supporting,
            "core_dividend",
            f"quality_score:{quality:.4f}",
        )
        _append(
            supporting,
            "value_rebound",
            f"quality_support:{quality:.4f}",
        )
    if relative_strength > 0:
        _append(
            supporting,
            "news_momentum",
            f"relative_strength_score:{relative_strength:.4f}",
        )

    core_score = _cap01(
        (quality * 0.30)
        + (fundamental * 0.10)
        + positive_fcf_bonus
        + low_debt_bonus
        + defensive_sector_bonus
        + dividend_bonus
    )
    if not defining["core_dividend"]:
        core_score = min(core_score, 0.59)

    value_score = _cap01(
        (valuation * 0.48)
        + (quality * 0.08)
        + (fundamental * 0.04)
        + cheap_pe_bonus
        + cheap_pb_bonus
        + (positive_fcf_bonus * 0.67)
    )
    if not defining["value_rebound"]:
        value_score = min(value_score, 0.49)

    momentum_score = _cap01(
        (growth * 0.42)
        + (momentum * 0.18)
        + (relative_strength * 0.08)
        + (indicator * 0.05)
        + (technical_vote * 0.05)
        + (sector_rotation * 0.04)
        + actual_growth_bonus
        + volume_bonus
        + breakout_bonus
    )
    if not defining["news_momentum"]:
        momentum_score = min(momentum_score, 0.49)

    bucket_scores = {
        "core_dividend": round(core_score, 4),
        "value_rebound": round(value_score, 4),
        "news_momentum": round(momentum_score, 4),
    }

    dominance_bucket: Optional[str] = None
    dominance_rule: Optional[str] = None
    if (
        pe is not None
        and 0 < pe <= 15
        and valuation >= 0.60
        and dividend_yield < 0.02
        and bucket_scores["value_rebound"] >= PRIMARY_HINT_THRESHOLD
    ):
        dominance_bucket = "value_rebound"
        dominance_rule = "deep_value_without_income_dominance"
    elif (
        dividend_yield >= 0.025
        and quality >= 0.65
        and bucket_scores["core_dividend"] >= PRIMARY_HINT_THRESHOLD
    ):
        dominance_bucket = "core_dividend"
        dominance_rule = "quality_income_dominance"
    elif (
        growth >= 0.75
        and strongest_growth >= 0.20
        and momentum >= 0.60
        and bucket_scores["news_momentum"] >= PRIMARY_HINT_THRESHOLD
    ):
        dominance_bucket = "news_momentum"
        dominance_rule = "growth_momentum_dominance"

    status, primary_hint, top_score, margin = _status_and_primary(
        bucket_scores,
        defining,
        dominance_bucket,
    )
    ordered = sorted(
        CONTROLLED_BUCKETS,
        key=lambda bucket: (-bucket_scores[bucket], bucket),
    )
    credible_hints = [
        bucket
        for bucket in ordered
        if bucket_scores[bucket] >= REVIEW_HINT_THRESHOLD
    ]
    if status == "suggested" and primary_hint:
        emitted_hints = [primary_hint]
    else:
        emitted_hints = credible_hints

    combined_evidence = {
        bucket: [*defining[bucket], *supporting[bucket]]
        for bucket in CONTROLLED_BUCKETS
    }

    reasons: List[str] = []
    if dominance_rule and primary_hint:
        reasons.append(
            f"dominance_rule_applied:{dominance_rule}:{primary_hint}"
        )
    if status == "conflict":
        reasons.append("multiple_bucket_identities_are_too_close")
    elif status == "review":
        reasons.append("top_bucket_score_requires_manager_review")
    elif status == "insufficient_evidence":
        reasons.append("insufficient_bucket_evidence")
    elif primary_hint:
        reasons.append(f"primary_hint_supported:{primary_hint}")
    for bucket in ordered[:2]:
        reasons.extend(
            f"{bucket}:defining:{reason}"
            for reason in defining[bucket][:3]
        )
        reasons.extend(
            f"{bucket}:supporting:{reason}"
            for reason in supporting[bucket][:2]
        )

    tags: List[str] = [f"bucket-hint-status:{status}"]
    if primary_hint:
        tags.append(f"bucket-hint:{primary_hint}")

    return {
        "bucket_hint_version": BUCKET_HINT_VERSION,
        "bucket_hint_policy_version": BUCKET_HINT_POLICY_VERSION,
        "bucket_hint_status": status,
        "primary_strategy_bucket_hint": primary_hint,
        "primary_strategy_bucket_confidence": (
            round(top_score, 4) if primary_hint else None
        ),
        "strategy_bucket_confidence": round(top_score, 4),
        "strategy_bucket_hints": emitted_hints,
        "bucket_hint_scores": bucket_scores,
        "bucket_hint_margin": margin,
        "bucket_hint_evidence": combined_evidence,
        "bucket_hint_defining_evidence": defining,
        "bucket_hint_supporting_evidence": supporting,
        "bucket_hint_dominance_rule": dominance_rule,
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
            "hard_conflict_margin": HARD_CONFLICT_MARGIN,
        },
    }
