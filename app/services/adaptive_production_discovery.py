from __future__ import annotations

import os
import time
from typing import Any, Iterable, Mapping

from app.services import production_enrichment as _production_enrichment
from app.services.cached_fundamental_discovery import (
    discover_best_fundamentals as _base_discover_best_fundamentals,
)
from app.services.opportunity_profile import (
    build_opportunity_profile as _base_build_opportunity_profile,
)
from app.services.shadow_lane import partition_candidates_by_lane

_BASE_ENRICH = _production_enrichment.enrich_fundamental_candidates_for_production
_BASE_MARKET_SNAPSHOT = _production_enrichment.get_market_snapshot

_DEFAULT_POOL_MULTIPLIER = 5
_MAX_POOL_SIZE = 50
_DEFAULT_STALE_QUOTE_RETRY_ATTEMPTS = 1
_DEFAULT_STALE_QUOTE_RETRY_DELAY_SECONDS = 0.25
_DEFAULT_STRATEGY_AWARE_SCORE_FLOOR = 0.55
_DEFAULT_STRATEGY_AWARE_AFFINITY_THRESHOLD = 0.72
_STALE_QUOTE_STATUSES = {"stale_quote", "missing_quote_timestamp"}


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _candidate_metadata(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "metadata"):
        return dict(getattr(candidate, "metadata") or {})
    if isinstance(candidate, dict):
        return dict(candidate.get("metadata") or {})
    return {}


def _set_candidate_metadata(candidate: Any, metadata: dict[str, Any]) -> None:
    if hasattr(candidate, "metadata"):
        candidate.metadata = metadata
    elif isinstance(candidate, dict):
        candidate["metadata"] = metadata


def _candidate_symbol(candidate: Any) -> str:
    if hasattr(candidate, "symbol"):
        return str(getattr(candidate, "symbol") or "").upper()
    if isinstance(candidate, Mapping):
        return str(candidate.get("symbol") or "").upper()
    return ""


def _candidate_rank(candidate: Any) -> int:
    value = getattr(candidate, "discovery_rank", None)
    if value is None and isinstance(candidate, Mapping):
        value = candidate.get("discovery_rank")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def _int_env(name: str, default: int, lower: int, upper: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def _float_env(name: str, default: float, lower: float, upper: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def _quote_status(snapshot: Mapping[str, Any]) -> str:
    quote_quality = _mapping(snapshot.get("quote_quality"))
    return str(
        snapshot.get("quoteQualityStatus")
        or quote_quality.get("status")
        or "unverified"
    ).strip().lower()


def _market_session(snapshot: Mapping[str, Any]) -> str:
    quote_quality = _mapping(snapshot.get("quote_quality"))
    return str(
        snapshot.get("usMarketSession")
        or quote_quality.get("market_session")
        or "unverified"
    ).strip().lower()


def _quote_age(snapshot: Mapping[str, Any]) -> float:
    quote_quality = _mapping(snapshot.get("quote_quality"))
    value = snapshot.get("alpacaQuoteAgeSeconds")
    if value is None:
        value = quote_quality.get("quote_age_seconds")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def adaptive_get_market_snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Refresh stale executable quotes without weakening quote safety.

    Only stale or timestamp-missing quotes during the regular session are retried.
    Wide spreads, crossed quotes, illiquidity and any other execution evidence are
    never retried into a pass state by this helper.
    """

    snapshot = dict(_BASE_MARKET_SNAPSHOT(*args, **kwargs) or {})
    initial_status = _quote_status(snapshot)
    attempts = 0
    recovered = False
    retry_attempts = _int_env(
        "SCANNER_PRODUCTION_STALE_QUOTE_RETRY_ATTEMPTS",
        _DEFAULT_STALE_QUOTE_RETRY_ATTEMPTS,
        0,
        2,
    )
    retry_delay = _float_env(
        "SCANNER_PRODUCTION_STALE_QUOTE_RETRY_DELAY_SECONDS",
        _DEFAULT_STALE_QUOTE_RETRY_DELAY_SECONDS,
        0.0,
        2.0,
    )

    if initial_status in _STALE_QUOTE_STATUSES and _market_session(snapshot) == "regular":
        best = snapshot
        for _ in range(retry_attempts):
            attempts += 1
            if retry_delay > 0:
                time.sleep(retry_delay)
            refreshed = dict(_BASE_MARKET_SNAPSHOT(*args, **kwargs) or {})
            refreshed_status = _quote_status(refreshed)
            if refreshed_status not in _STALE_QUOTE_STATUSES:
                best = refreshed
                recovered = True
                break
            if _quote_age(refreshed) < _quote_age(best):
                best = refreshed
        snapshot = best

    snapshot["adaptive_quote_refresh"] = {
        "schema_version": "scanner-stale-quote-refresh.v1",
        "initial_status": initial_status,
        "final_status": _quote_status(snapshot),
        "attempts": attempts,
        "recovered": recovered,
        "hard_execution_thresholds_relaxed": False,
    }
    return snapshot


def _strategy_affinity(profile: Mapping[str, Any], bucket: str) -> tuple[str | None, float]:
    affinities = _mapping(profile.get("strategy_affinity"))
    trend = float(affinities.get("trend_following") or 0.0)
    breakout = float(affinities.get("breakout") or 0.0)
    mean_reversion = float(affinities.get("mean_reversion") or 0.0)
    if bucket == "value_rebound":
        return "mean_reversion", mean_reversion
    if bucket == "news_momentum":
        if breakout >= trend:
            return "breakout", breakout
        return "trend_following", trend
    return None, 0.0


def adaptive_build_opportunity_profile(data_bundle: dict[str, Any]) -> dict[str, Any]:
    """Add strategy-aware qualification while preserving hard execution gates."""

    profile = dict(_base_build_opportunity_profile(data_bundle) or {})
    strategy_context = _mapping(data_bundle.get("strategy_context"))
    bucket = str(strategy_context.get("primary_strategy_bucket_hint") or "").strip().lower()
    strategy_name, affinity = _strategy_affinity(profile, bucket)
    score = float(profile.get("opportunity_score") or 0.0)
    evidence_quality = _mapping(profile.get("evidence_quality"))
    execution_context = _mapping(profile.get("execution_context"))
    quote_status = str(execution_context.get("quote_status") or "unverified").lower()
    market_session = str(execution_context.get("market_session") or "unverified").lower()

    score_floor = _float_env(
        "SCANNER_STRATEGY_AWARE_SCORE_FLOOR",
        _DEFAULT_STRATEGY_AWARE_SCORE_FLOOR,
        0.50,
        0.70,
    )
    affinity_threshold = _float_env(
        "SCANNER_STRATEGY_AWARE_AFFINITY_THRESHOLD",
        _DEFAULT_STRATEGY_AWARE_AFFINITY_THRESHOLD,
        0.65,
        0.90,
    )

    hard_safe = (
        profile.get("fail_closed") is not True
        and quote_status not in {"market_closed", "stale_quote", "missing_quote_timestamp"}
        and market_session == "regular"
        and evidence_quality.get("spread_structurally_valid") is True
        and evidence_quality.get("liquid_spread_sane") is True
        and float(evidence_quality.get("coverage_ratio") or 0.0) >= 1.0
    )
    strategy_ready = (
        hard_safe
        and strategy_name is not None
        and score >= score_floor
        and affinity >= affinity_threshold
    )

    if profile.get("status") == "qualified":
        qualification_mode = "generic"
    elif strategy_ready:
        profile["status"] = "qualified"
        profile["workflow_status"] = "strategy_ready"
        qualification_mode = "strategy_aware"
    else:
        qualification_mode = "none"

    profile["qualification_policy"] = {
        "schema_version": "scanner-opportunity-qualification.v2",
        "mode": qualification_mode,
        "strategy_bucket": bucket or None,
        "strategy_name": strategy_name,
        "strategy_affinity": round(affinity, 4),
        "generic_score": round(score, 4),
        "generic_threshold": 0.70,
        "strategy_score_floor": score_floor,
        "strategy_affinity_threshold": affinity_threshold,
        "hard_execution_safe": hard_safe,
        "hard_execution_thresholds_relaxed": False,
        "manager_decision_required": True,
    }
    return profile


def _attach_strategy_context(candidate: Any) -> None:
    metadata = _candidate_metadata(candidate)
    bundle = _mapping(metadata.get("data_bundle"))
    if not bundle:
        return
    bundle["strategy_context"] = {
        "primary_strategy_bucket_hint": metadata.get("primary_strategy_bucket_hint"),
        "strategy_bucket_confidence": metadata.get("strategy_bucket_confidence"),
        "bucket_hint_scores": metadata.get("bucket_hint_scores") or {},
        "is_binding": False,
        "manager_decision_required": True,
    }
    metadata["data_bundle"] = bundle
    _set_candidate_metadata(candidate, metadata)


def _mark_pre_enriched(candidate: Any, backfill: Mapping[str, Any]) -> None:
    metadata = _candidate_metadata(candidate)
    metadata["adaptive_production_pre_enriched"] = True
    metadata["adaptive_production_backfill"] = dict(backfill)
    _set_candidate_metadata(candidate, metadata)


def discover_best_fundamentals(
    max_universe: int = 1000,
    top_n: int = 10,
    exchange: str = "NASDAQ",
    max_workers: int = 10,
):
    """Discover a wider pool, enrich it, and backfill production-safe candidates."""

    normalized_top_n = max(1, int(top_n))
    multiplier = _int_env(
        "SCANNER_PRODUCTION_ENRICHMENT_POOL_MULTIPLIER",
        _DEFAULT_POOL_MULTIPLIER,
        1,
        10,
    )
    pool_size = min(_MAX_POOL_SIZE, max(normalized_top_n, normalized_top_n * multiplier))
    pool, errors, metadata = _base_discover_best_fundamentals(
        max_universe=max_universe,
        top_n=pool_size,
        exchange=exchange,
        max_workers=max_workers,
    )

    for candidate in pool:
        _attach_strategy_context(candidate)

    enriched_pool, enrichment_summary = _BASE_ENRICH(pool, default_exchange=exchange)
    production, research, lane_summary = partition_candidates_by_lane(enriched_pool)
    production = sorted(production, key=_candidate_rank)
    research = sorted(research, key=_candidate_rank)
    ranked_pool = sorted(enriched_pool, key=_candidate_rank)

    selected: list[Any] = list(production[:normalized_top_n])
    selected_symbols = {_candidate_symbol(candidate) for candidate in selected}
    for candidate in ranked_pool:
        if len(selected) >= normalized_top_n:
            break
        symbol = _candidate_symbol(candidate)
        if symbol in selected_symbols:
            continue
        selected.append(candidate)
        selected_symbols.add(symbol)

    backfilled_symbols = [
        _candidate_symbol(candidate)
        for candidate in selected
        if candidate in production and _candidate_rank(candidate) > normalized_top_n
    ]
    backfill_summary = {
        "schema_version": "scanner-production-backfill.v1",
        "requested_top_n": normalized_top_n,
        "enrichment_pool_size": len(enriched_pool),
        "configured_pool_size": pool_size,
        "production_qualified_count": len(production),
        "research_candidate_count": len(research),
        "returned_candidate_count": len(selected),
        "backfilled_production_count": len(backfilled_symbols),
        "backfilled_symbols": backfilled_symbols,
        "production_first_selection": True,
        "trading_thresholds_relaxed": False,
        "broker_order_authorized": False,
    }
    for candidate in selected:
        _mark_pre_enriched(candidate, backfill_summary)

    metadata = dict(metadata or {})
    metadata["top_n"] = normalized_top_n
    metadata["production_enrichment"] = enrichment_summary
    metadata["lane_summary_preselection"] = lane_summary
    metadata["adaptive_production_backfill"] = backfill_summary
    return selected, errors, metadata


def reuse_pre_enriched_candidates(
    candidates: Iterable[Any],
    *,
    default_exchange: str = "NASDAQ",
):
    """Avoid immediately repeating production enrichment in the response validator."""

    rows = list(candidates)
    if not rows or not all(
        _candidate_metadata(candidate).get("adaptive_production_pre_enriched") is True
        for candidate in rows
    ):
        return _BASE_ENRICH(rows, default_exchange=default_exchange)

    completed = 0
    qualified = 0
    stale_retry_attempts = 0
    stale_retry_recovered = 0
    for candidate in rows:
        metadata = _candidate_metadata(candidate)
        enrichment = _mapping(metadata.get("production_enrichment"))
        if enrichment.get("status") == "complete":
            completed += 1
        if enrichment.get("opportunity_status") == "qualified":
            qualified += 1
        bundle = _mapping(metadata.get("data_bundle"))
        market = _mapping(bundle.get("market_snapshot"))
        refresh = _mapping(market.get("adaptive_quote_refresh"))
        stale_retry_attempts += int(refresh.get("attempts") or 0)
        stale_retry_recovered += int(bool(refresh.get("recovered")))

    return rows, {
        "schema_version": "scanner-production-enrichment.v1",
        "requested_count": len(rows),
        "enriched_count": completed,
        "failed_count": len(rows) - completed,
        "production_qualified_count": qualified,
        "stale_quote_retry_attempts": stale_retry_attempts,
        "stale_quote_retry_recovered_count": stale_retry_recovered,
        "reused_same_cycle_pre_enrichment": True,
        "production_execution_evidence_reused_across_cycles": False,
        "broker_order_authorized": False,
        "manager_decision_required": True,
    }
