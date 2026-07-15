import math
from typing import Any, Dict, Optional

from app.config import settings


def _as_finite_float(value: Any) -> Optional[float]:
    """Convert provider values to finite floats without inventing data."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_quality_score(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate quality using only metrics that normalize to real numbers."""

    score = 0.0
    max_score = 0

    roe = _as_finite_float(metrics.get("roe"))
    if roe is not None:
        max_score += 1
        if roe > 15:
            score += 1.0
        elif roe > 10:
            score += 0.7
        elif roe > 5:
            score += 0.3

    roa = _as_finite_float(metrics.get("roa"))
    if roa is not None:
        max_score += 1
        if roa > 10:
            score += 1.0
        elif roa > 7:
            score += 0.7
        elif roa > 4:
            score += 0.3

    debt_to_equity = _as_finite_float(metrics.get("debt_to_equity"))
    if debt_to_equity is not None:
        max_score += 1
        if debt_to_equity < 0.5:
            score += 1.0
        elif debt_to_equity < 1.0:
            score += 0.7
        elif debt_to_equity < 1.5:
            score += 0.3

    free_cash_flow = _as_finite_float(metrics.get("free_cash_flow"))
    if free_cash_flow is not None:
        max_score += 1
        if free_cash_flow > 0:
            score += 1.0

    profit_margins = _as_finite_float(metrics.get("profit_margins"))
    if profit_margins is not None:
        max_score += 1
        if profit_margins > 10:
            score += 1.0
        elif profit_margins > 7:
            score += 0.7
        elif profit_margins > 4:
            score += 0.3

    if max_score == 0:
        return None
    return (score / max_score) * 100


def calculate_growth_score(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate growth using only metrics that normalize to real numbers."""

    score = 0.0
    max_score = 0

    revenue_cagr = _as_finite_float(metrics.get("revenue_cagr"))
    if revenue_cagr is not None:
        max_score += 1
        if revenue_cagr > 10:
            score += 1.0
        elif revenue_cagr > 7:
            score += 0.7
        elif revenue_cagr > 4:
            score += 0.3

    eps_growth = _as_finite_float(metrics.get("eps_growth"))
    if eps_growth is not None:
        max_score += 1
        if eps_growth > 10:
            score += 1.0
        elif eps_growth > 7:
            score += 0.7
        elif eps_growth > 4:
            score += 0.3

    if max_score == 0:
        return None
    return (score / max_score) * 100


def calculate_valuation_score(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate valuation without comparing provider strings to numbers."""

    score = 0.0
    max_score = 0

    pe_ratio = _as_finite_float(metrics.get("pe_ratio"))
    if pe_ratio is not None:
        max_score += 1
        if pe_ratio < 20:
            score += 1.0
        elif pe_ratio < 30:
            score += 0.7
        elif pe_ratio < 40:
            score += 0.3

    peg_ratio = _as_finite_float(metrics.get("peg_ratio"))
    if peg_ratio is not None:
        max_score += 1
        if peg_ratio < 1.0:
            score += 1.0
        elif peg_ratio < 1.5:
            score += 0.7
        elif peg_ratio < 2.0:
            score += 0.3

    pb_ratio = _as_finite_float(metrics.get("pb_ratio"))
    if pb_ratio is not None:
        max_score += 1
        if pb_ratio < 3.0:
            score += 1.0
        elif pb_ratio < 4.5:
            score += 0.7
        elif pb_ratio < 6.0:
            score += 0.3

    if max_score == 0:
        return None
    return (score / max_score) * 100


def calculate_fundamental_score(scores: Dict[str, Any]) -> Optional[float]:
    """Combine available component scores after numeric normalization."""

    total_score = 0.0
    total_weight = 0.0
    weighted_components = (
        ("quality_score", settings.QUALITY_SCORE_WEIGHT),
        ("growth_score", settings.GROWTH_SCORE_WEIGHT),
        ("valuation_score", settings.VALUATION_SCORE_WEIGHT),
    )
    for key, weight in weighted_components:
        score = _as_finite_float(scores.get(key))
        if score is None:
            continue
        total_score += score * weight
        total_weight += weight

    if total_weight == 0:
        return None
    return total_score / total_weight


def get_grade(score: float) -> str:
    """Assign a grade to a validated numeric score."""

    normalized = _as_finite_float(score)
    if normalized is None:
        raise ValueError("grade requires a finite numeric score")
    if normalized >= 80:
        return "A"
    if normalized >= 65:
        return "B"
    return "C"
