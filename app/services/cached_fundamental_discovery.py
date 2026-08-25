from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.models import ErrorDetail, ScannerCandidateContract
from app.services import fundamental_discovery as base
from app.services.fundamental_candidate_cache import (
    annotate_fresh_candidate,
    cache_status,
    load_candidate,
    store_candidate,
)

_DEFAULT_BATCH_SIZE = 40
_DEFAULT_COOLDOWN_SECONDS = 2.0
_MAX_COOLDOWN_SECONDS = 8.0
_RATE_LIMIT_RATIO_TO_THROTTLE = 0.20
_RATE_LIMIT_COUNT_TO_THROTTLE = 3


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


def _analyze_and_cache(symbol: str, exchange: str) -> ScannerCandidateContract:
    candidate = base.analyze_fundamental_candidate(symbol, exchange)
    candidate = annotate_fresh_candidate(candidate)
    store_candidate(candidate, exchange)
    return candidate


def _sort_candidates(candidates: list[ScannerCandidateContract]) -> None:
    candidates.sort(
        key=lambda candidate: (
            candidate.candidate_score or 0.0,
            candidate.raw_scores.get("evidence_coverage") or 0.0,
            candidate.raw_scores.get("quality_score") or 0.0,
            candidate.raw_scores.get("growth_score") or 0.0,
            candidate.raw_scores.get("revenue_3y_cagr") or 0.0,
            candidate.raw_scores.get("fcf_growth") or 0.0,
            candidate.raw_scores.get("valuation_score") or 0.0,
        ),
        reverse=True,
    )


def _top_diagnostics(
    top_candidates: list[ScannerCandidateContract],
) -> list[dict[str, Any]]:
    return [
        {
            "symbol": candidate.symbol,
            "yf_symbol": candidate.metadata.get("yf_symbol"),
            "primary_strategy_bucket_hint": candidate.metadata.get(
                "primary_strategy_bucket_hint"
            ),
            "bucket_hint_scores": candidate.metadata.get("bucket_hint_scores"),
            "has_annual_income_statement": candidate.metadata.get(
                "has_annual_income_statement"
            ),
            "has_annual_cash_flow": candidate.metadata.get(
                "has_annual_cash_flow"
            ),
            "valuation_metric_count": candidate.metadata.get(
                "valuation_metric_count"
            ),
            "evidence_coverage": candidate.raw_scores.get("evidence_coverage"),
            "revenue_3y_cagr": candidate.raw_scores.get("revenue_3y_cagr"),
            "eps_growth": candidate.raw_scores.get("eps_growth"),
            "fcf_growth": candidate.raw_scores.get("fcf_growth"),
            "fundamental_cache_hit": bool(
                (candidate.metadata.get("fundamental_cache") or {}).get("hit")
            ),
        }
        for candidate in top_candidates
    ]


def discover_best_fundamentals(
    max_universe: int = 1000,
    top_n: int = 10,
    exchange: str = "NASDAQ",
    max_workers: int = 10,
):
    """Discover broad-market fundamentals with persistent cache and adaptive pacing.

    Cached evidence is used only for the slow-moving broad fundamental stage.
    Scanner's final production enrichment still refreshes live quote, Technical,
    ATR, relative-volume and opportunity evidence, so cache hits never authorize
    a broker order or bypass Manager/Risk/Execution.
    """

    universe_info = base.build_us_fundamental_universe(max_universe=max_universe)
    symbols = [
        symbol
        for symbol in universe_info["symbols"]
        if base._is_discoverable_stock_symbol(symbol)
    ]
    universe_sources = universe_info.get("sources") or {}
    provider_worker_cap = (
        base._DEGRADED_PROVIDER_WORKERS
        if universe_sources.get("universe_degraded")
        else base._MAX_PROVIDER_WORKERS
    )
    requested_workers = max(1, int(max_workers))
    initial_workers = max(1, min(requested_workers, provider_worker_cap))
    current_workers = initial_workers

    candidates: list[ScannerCandidateContract] = []
    errors: list[ErrorDetail] = []
    misses: list[str] = []
    cache_hits = 0

    for symbol in symbols:
        cached = load_candidate(symbol, exchange)
        if cached is None:
            misses.append(symbol)
            continue
        cache_hits += 1
        candidates.append(cached)

    batch_size = _int_env(
        "SCANNER_FUNDAMENTAL_PROVIDER_BATCH_SIZE",
        _DEFAULT_BATCH_SIZE,
        5,
        200,
    )
    base_cooldown = _float_env(
        "SCANNER_FUNDAMENTAL_RATE_LIMIT_COOLDOWN_SECONDS",
        _DEFAULT_COOLDOWN_SECONDS,
        0.0,
        _MAX_COOLDOWN_SECONDS,
    )
    max_cooldown = _float_env(
        "SCANNER_FUNDAMENTAL_RATE_LIMIT_MAX_COOLDOWN_SECONDS",
        _MAX_COOLDOWN_SECONDS,
        base_cooldown,
        30.0,
    )
    cooldown = base_cooldown
    throttle_events = 0
    rate_limit_events = 0
    processed_provider_symbols = 0
    provider_batches = 0
    minimum_workers_seen = current_workers

    for start in range(0, len(misses), batch_size):
        batch = misses[start : start + batch_size]
        provider_batches += 1
        batch_errors: list[ErrorDetail] = []

        with ThreadPoolExecutor(max_workers=current_workers) as executor:
            future_to_symbol = {
                executor.submit(_analyze_and_cache, symbol, exchange): symbol
                for symbol in batch
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                processed_provider_symbols += 1
                try:
                    candidate = future.result()
                    if base._is_discoverable_stock_symbol(candidate.symbol):
                        candidates.append(candidate)
                except Exception as exc:
                    detail = ErrorDetail(symbol=symbol, error=str(exc))
                    errors.append(detail)
                    batch_errors.append(detail)

        batch_rate_limits = sum(
            1
            for error in batch_errors
            if base._classify_discovery_error(error.error) == "provider_rate_limited"
        )
        rate_limit_events += batch_rate_limits
        rate_limit_ratio = batch_rate_limits / len(batch) if batch else 0.0
        should_throttle = (
            batch_rate_limits >= _RATE_LIMIT_COUNT_TO_THROTTLE
            or rate_limit_ratio >= _RATE_LIMIT_RATIO_TO_THROTTLE
        )
        if should_throttle:
            throttle_events += 1
            current_workers = 1
            minimum_workers_seen = 1
            if cooldown > 0 and start + batch_size < len(misses):
                time.sleep(cooldown)
            cooldown = min(max_cooldown, max(base_cooldown, cooldown * 2 or base_cooldown))
        elif batch_rate_limits == 0:
            cooldown = base_cooldown
            if current_workers < initial_workers:
                current_workers = min(initial_workers, current_workers + 1)

    _sort_candidates(candidates)
    top_candidates = candidates[:top_n]
    for rank, candidate in enumerate(top_candidates, start=1):
        candidate.discovery_rank = rank

    attempted_count = len(symbols)
    error_diagnostics = base._error_diagnostics(errors)
    cache_info = cache_status()
    cache_info.update(
        {
            "hit_count": cache_hits,
            "miss_count": len(misses),
            "hit_rate": round(cache_hits / attempted_count, 4)
            if attempted_count
            else 0.0,
        }
    )
    adaptive_provider = {
        "schema_version": "scanner-provider-throttle.v1",
        "batch_size": batch_size,
        "provider_batches": provider_batches,
        "processed_provider_symbols": processed_provider_symbols,
        "initial_workers": initial_workers,
        "minimum_workers_seen": minimum_workers_seen,
        "final_workers": current_workers,
        "rate_limit_events": rate_limit_events,
        "throttle_events": throttle_events,
        "base_cooldown_seconds": base_cooldown,
        "max_cooldown_seconds": max_cooldown,
        "threshold_rate_limit_ratio": _RATE_LIMIT_RATIO_TO_THROTTLE,
        "threshold_rate_limit_count": _RATE_LIMIT_COUNT_TO_THROTTLE,
        "trading_thresholds_relaxed": False,
    }

    metadata = {
        **universe_sources,
        "attempted_count": attempted_count,
        "analyzed_count": len(candidates),
        "error_count": len(errors),
        "success_rate": round(len(candidates) / attempted_count, 4)
        if attempted_count
        else 0.0,
        "requested_max_workers": max_workers,
        "effective_max_workers": initial_workers,
        "provider_worker_cap": provider_worker_cap,
        **error_diagnostics,
        "fundamental_cache": cache_info,
        "adaptive_provider_control": adaptive_provider,
        "top_n": top_n,
        "exchange": exchange,
        "excluded_non_tradable_symbols": sorted(base._NON_TRADABLE_DISCOVERY_SYMBOLS),
        "bucket_hints_enabled": True,
        "growth_v2_fields": [
            "revenue_3y_cagr",
            "eps_growth",
            "fcf_growth",
            "fcf_3y_cagr",
            "qoq_revenue_growth",
            "qoq_eps_growth",
            "qoq_fcf_growth",
        ],
        "diagnostics": _top_diagnostics(top_candidates),
    }
    return top_candidates, errors, metadata
