from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

CANDIDATE_SCORE_INPUTS_VERSION = "candidate-score-inputs.v1"


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite(value: Any) -> Optional[float]:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_candidate_score_inputs(data_bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """Project Scanner evidence consumed by Manager's candidate-score.v1.

    This contract is advisory only. It exposes already-collected evidence and
    never grants Risk, Execution, or broker authority. Relative-strength evidence
    is considered scoreable only when the symbol has explicit benchmark returns.
    """

    bundle = _mapping(data_bundle)
    technical = _mapping(bundle.get("technical"))
    indicators = _mapping(technical.get("indicator_values"))
    market_rank = _mapping(bundle.get("market_rank"))
    profile = _mapping(bundle.get("opportunity_profile"))
    execution_context = _mapping(profile.get("execution_context"))
    quality = _mapping(bundle.get("data_quality"))
    analysis_quality = _mapping(quality.get("analysis"))

    close = _finite(indicators.get("close"))
    sma50 = _finite(indicators.get("sma50"))
    sma200 = _finite(indicators.get("sma200"))
    volume_ratio = _finite(
        execution_context.get("relative_volume")
        if execution_context.get("relative_volume") is not None
        else market_rank.get("volume_ratio")
    )
    market_rank_score = _finite(market_rank.get("market_rank_score"))
    if market_rank_score is None:
        market_rank_score = _finite(market_rank.get("score"))

    return_20d = _finite(market_rank.get("return_20d"))
    return_60d = _finite(market_rank.get("return_60d"))
    trend_score = _finite(market_rank.get("trend_score"))
    benchmark_return_20d = _finite(market_rank.get("benchmark_return_20d"))
    benchmark_return_60d = _finite(market_rank.get("benchmark_return_60d"))
    relative_return_20d = _finite(market_rank.get("relative_return_20d"))
    relative_return_60d = _finite(market_rank.get("relative_return_60d"))
    outperforming_benchmark = market_rank.get("outperforming_benchmark")
    if not isinstance(outperforming_benchmark, bool):
        outperforming_benchmark = None
    benchmark_symbol = str(market_rank.get("benchmark_symbol") or "").strip() or None

    technical_coverage = [close, sma50, sma200]
    market_strength_coverage = [
        return_20d,
        return_60d,
        benchmark_return_20d,
        benchmark_return_60d,
        relative_return_20d,
        relative_return_60d,
    ]

    universe_proxy = (
        market_rank_score >= 0.65
        and (return_20d or 0) > 0
        and (return_60d or 0) > 0
        if market_rank_score is not None
        and return_20d is not None
        and return_60d is not None
        else None
    )

    return {
        "schema_version": CANDIDATE_SCORE_INPUTS_VERSION,
        "symbol": bundle.get("symbol"),
        "technical": {
            "close": close,
            "sma50": sma50,
            "sma200": sma200,
            "relative_volume": volume_ratio,
            "price_above_sma200": (
                close > sma200 if close is not None and sma200 is not None else None
            ),
            "sma50_above_sma200": (
                sma50 > sma200 if sma50 is not None and sma200 is not None else None
            ),
        },
        "market_strength": {
            "market_rank_score": market_rank_score,
            "return_20d": return_20d,
            "return_60d": return_60d,
            "trend_score": trend_score,
            "benchmark_symbol": benchmark_symbol,
            "benchmark_return_20d": benchmark_return_20d,
            "benchmark_return_60d": benchmark_return_60d,
            "relative_return_20d": relative_return_20d,
            "relative_return_60d": relative_return_60d,
            "outperforming_benchmark": outperforming_benchmark,
            "stronger_than_universe_proxy": universe_proxy,
            "method": (
                "benchmark_relative_returns"
                if outperforming_benchmark is not None
                and relative_return_20d is not None
                and relative_return_60d is not None
                and benchmark_symbol is not None
                else "unavailable"
            ),
        },
        "opportunity": {
            "schema_version": profile.get("schema_version"),
            "status": profile.get("status"),
            "workflow_status": profile.get("workflow_status"),
            "opportunity_score": _finite(profile.get("opportunity_score")),
            "fail_closed": bool(profile.get("fail_closed")),
            "execution_context": execution_context,
        },
        "data_quality": {
            "analysis_coverage_ratio": _finite(
                analysis_quality.get("coverage_ratio")
            ),
            "analysis_status": analysis_quality.get("status"),
            "technical_input_coverage": round(
                sum(value is not None for value in technical_coverage)
                / len(technical_coverage),
                4,
            ),
            "market_strength_coverage": round(
                sum(value is not None for value in market_strength_coverage)
                / len(market_strength_coverage),
                4,
            ),
        },
        "authority": {
            "is_binding": False,
            "manager_decision_required": True,
            "broker_order_authorized": False,
            "risk_approval_allowed": False,
            "execution_agent_allowed": False,
        },
    }
