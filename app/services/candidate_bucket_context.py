from __future__ import annotations

from typing import Any, Dict, Mapping

from app.services.bucket_hints import build_strategy_bucket_hints


_SCORE_KEYS = (
    "quality_score",
    "valuation_score",
    "growth_score",
    "fundamental_score",
    "momentum_score",
    "relative_strength_score",
    "indicator_score",
    "technical_vote_score",
    "sector_rotation_score",
    "risk_score",
    "final_score",
    "pe_ratio",
    "pb_ratio",
    "forward_pe",
    "debt_to_equity",
    "free_cash_flow",
    "profit_margin",
    "profit_margins",
    "roe",
    "dividend_yield",
    "fcf_growth",
    "fcf_3y_cagr",
    "revenue_growth",
    "revenue_3y_cagr",
    "earnings_growth",
    "eps_growth",
    "volume_ratio",
    "breakout_ratio",
)


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _copy_known_scores(target: Dict[str, Any], source: Mapping[str, Any]) -> None:
    for key in _SCORE_KEYS:
        value = source.get(key)
        if value is not None and value != "" and key not in target:
            target[key] = value


def extract_bucket_hint_inputs(candidate: Any, metadata: Dict[str, Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Flatten technical/fundamental candidate evidence into hint inputs."""
    candidate_data = _mapping(candidate)
    metadata = dict(metadata or {})
    details = _mapping(metadata.get("details") or candidate_data.get("details"))

    raw_scores: Dict[str, Any] = {}
    _copy_known_scores(raw_scores, candidate_data)
    _copy_known_scores(raw_scores, details)

    quality = _mapping(metadata.get("quality") or candidate_data.get("quality"))
    growth = _mapping(metadata.get("growth") or candidate_data.get("growth"))
    valuation = _mapping(metadata.get("valuation") or candidate_data.get("valuation"))

    if quality:
        if quality.get("score") is not None:
            raw_scores.setdefault("quality_score", quality.get("score"))
        _copy_known_scores(raw_scores, quality)
    if growth:
        if growth.get("score") is not None:
            raw_scores.setdefault("growth_score", growth.get("score"))
        _copy_known_scores(raw_scores, growth)
    if valuation:
        if valuation.get("score") is not None:
            raw_scores.setdefault("valuation_score", valuation.get("score"))
        _copy_known_scores(raw_scores, valuation)

    scanner_v50 = _mapping(details.get("scanner_v50"))
    fundamental = _mapping(scanner_v50.get("fundamental"))
    indicator_values = _mapping(scanner_v50.get("indicator_values"))
    growth_values = _mapping(scanner_v50.get("growth_values"))
    _copy_known_scores(raw_scores, fundamental)
    _copy_known_scores(raw_scores, indicator_values)
    _copy_known_scores(raw_scores, growth_values)

    if candidate_data.get("fundamental_score") is not None:
        raw_scores.setdefault("fundamental_score", candidate_data.get("fundamental_score"))

    context = dict(metadata)
    if not context.get("sector"):
        context["sector"] = candidate_data.get("sector") or fundamental.get("sector")
    if not context.get("source"):
        context["source"] = candidate_data.get("source") or details.get("source")
    context["bucket_hint_input_fields"] = sorted(raw_scores.keys())
    return raw_scores, context


def enrich_candidate_metadata_with_bucket_hints(
    candidate: Any,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    raw_scores, context = extract_bucket_hint_inputs(candidate, metadata)
    hints = build_strategy_bucket_hints(raw_scores, context)
    return {**context, **hints}
