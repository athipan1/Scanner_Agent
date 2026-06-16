from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from app.models import Candidate
from app.services.market_regime import detect_market_regime, result_to_metadata as regime_to_metadata


@dataclass
class PortfolioAllocation:
    symbol: str
    final_score: float
    recommendation: str
    target_weight: float
    risk_bucket: str
    reason: List[str]


@dataclass
class PortfolioPlan:
    regime: Dict[str, object]
    cash_weight: float
    max_positions: int
    allocations: List[PortfolioAllocation]
    reason: List[str]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _candidate_score(candidate: Candidate) -> float:
    try:
        return float((candidate.details or {}).get("final_score", 0.0) or 0.0)
    except Exception:
        return 0.0


def _risk_bucket(candidate: Candidate) -> str:
    details = candidate.details or {}
    risk_score = float(details.get("risk_score", 0.5) or 0.5)
    if risk_score >= 0.75:
        return "LOW_RISK"
    if risk_score >= 0.55:
        return "MEDIUM_RISK"
    return "HIGH_RISK"


def _cash_weight_for_regime(regime: str) -> float:
    if regime == "BULL":
        return 0.10
    if regime == "BEAR":
        return 0.45
    return 0.25


def _max_positions_for_regime(regime: str) -> int:
    if regime == "BULL":
        return 8
    if regime == "BEAR":
        return 4
    return 6


def build_portfolio_plan(candidates: Iterable[Candidate]) -> PortfolioPlan:
    regime_result = detect_market_regime()
    regime_meta = regime_to_metadata(regime_result)
    regime = regime_result.regime
    cash_weight = _cash_weight_for_regime(regime)
    max_positions = _max_positions_for_regime(regime)

    ranked = sorted(list(candidates), key=_candidate_score, reverse=True)[:max_positions]
    investable_weight = 1.0 - cash_weight
    score_sum = sum(max(_candidate_score(candidate), 0.01) for candidate in ranked) or 1.0

    allocations: List[PortfolioAllocation] = []
    for candidate in ranked:
        details = candidate.details or {}
        score = _candidate_score(candidate)
        raw_weight = investable_weight * (max(score, 0.01) / score_sum)
        if regime == "BEAR" and _risk_bucket(candidate) == "HIGH_RISK":
            raw_weight *= 0.50
        target_weight = round(_clamp(raw_weight, 0.02, 0.25), 4)
        reasons = [
            f"Final Score {score:.4f}",
            f"Market Regime {regime}",
            f"Risk Bucket {_risk_bucket(candidate)}",
        ]
        candidate_reasons = details.get("reason") or []
        reasons.extend(candidate_reasons[:5])
        allocations.append(
            PortfolioAllocation(
                symbol=candidate.symbol,
                final_score=round(score, 4),
                recommendation=candidate.recommendation,
                target_weight=target_weight,
                risk_bucket=_risk_bucket(candidate),
                reason=reasons,
            )
        )

    total_allocated = sum(item.target_weight for item in allocations)
    if total_allocated > investable_weight and total_allocated > 0:
        scale = investable_weight / total_allocated
        allocations = [
            PortfolioAllocation(
                symbol=item.symbol,
                final_score=item.final_score,
                recommendation=item.recommendation,
                target_weight=round(item.target_weight * scale, 4),
                risk_bucket=item.risk_bucket,
                reason=item.reason,
            )
            for item in allocations
        ]

    plan_reasons = [
        f"Regime {regime} confidence {regime_result.confidence:.2%}",
        f"Cash weight {cash_weight:.2%}",
        f"Max positions {max_positions}",
    ]
    plan_reasons.extend(regime_result.reason[:6])

    return PortfolioPlan(
        regime=regime_meta,
        cash_weight=round(cash_weight, 4),
        max_positions=max_positions,
        allocations=allocations,
        reason=plan_reasons,
    )


def portfolio_plan_to_dict(plan: PortfolioPlan) -> Dict[str, object]:
    return {
        "regime": plan.regime,
        "cash_weight": plan.cash_weight,
        "max_positions": plan.max_positions,
        "allocations": [allocation.__dict__ for allocation in plan.allocations],
        "reason": plan.reason,
    }
