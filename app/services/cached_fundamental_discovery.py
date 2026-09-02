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
_MIN_BATCH_SIZE = 5
_RATE_LIMIT_RATIO_TO_THROTTLE = 0.20
_RATE_LIMIT_COUNT_TO_THROTTLE = 3
_DEFAULT_RATE_LIMIT_RETRY_ATTEMPTS = 1
_DEFAULT_CIRCUIT_BREAKER_BATCHES = 3
_DEFAULT_CANDIDATE_BUFFER_MULTIPLIER = 3


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


def _run_provider_batch(
    symbols: list[str],
    exchange: str,
    *,
    max_workers: int,
) -> tuple[list[ScannerCandidateContract], list[ErrorDetail]]:
    candidates: list[ScannerCandidateContract] = []
    errors: list[ErrorDetail] = []
    if not symbols:
        return candidates, errors

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(_analyze_and_cache, symbol, exchange): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                candidate = future.result()
                if base._is_discoverable_stock_symbol(candidate.symbol):
                    candidates.append(candidate)
            except Exception as exc:
                errors.append(ErrorDetail(symbol=symbol, error=str(exc)))
    return candidates, errors


def _rate_limited(errors: list[ErrorDetail]) -> list[ErrorDetail]:
    return [
        error
        for error in errors
        if base._classify_discovery_error(error.error) == "provider_rate_limited"
    ]


def _without_rate_limited(errors: list[ErrorDetail]) -> list[ErrorDetail]:
    return [
        error
        for error in errors
        if base._classify_discovery_error(error.error) != "provider_rate_limited"
    ]


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
    """Discover broad-market fundamentals with cache and pressure recovery.

    Cached evidence is limited to slow-moving broad fundamental discovery.
    Production enrichment still refreshes live quote, Technical, ATR, volume and
    opportunity evidence. Provider-pressure controls never authorize an order or
    relax Scanner, Manager, Risk or Execution thresholds.
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

    configured_batch_size = _int_env(
        "SCANNER_FUNDAMENTAL_PROVIDER_BATCH_SIZE",
        _DEFAULT_BATCH_SIZE,
        _MIN_BATCH_SIZE,
        200,
    )
    current_batch_size = configured_batch_size
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
    retry_attempts = _int_env(
        "SCANNER_FUNDAMENTAL_RATE_LIMIT_RETRY_ATTEMPTS",
        _DEFAULT_RATE_LIMIT_RETRY_ATTEMPTS,
        0,
        3,
    )
    circuit_breaker_batches = _int_env(
        "SCANNER_FUNDAMENTAL_PROVIDER_CIRCUIT_BREAKER_BATCHES",
        _DEFAULT_CIRCUIT_BREAKER_BATCHES,
        1,
        20,
    )
    candidate_buffer_multiplier = _int_env(
        "SCANNER_FUNDAMENTAL_PROVIDER_CANDIDATE_BUFFER_MULTIPLIER",
        _DEFAULT_CANDIDATE_BUFFER_MULTIPLIER,
        1,
        10,
    )
    normalized_top_n = max(1, int(top_n))
    candidate_buffer_required = max(
        normalized_top_n,
        normalized_top_n * candidate_buffer_multiplier,
    )

    cooldown = base_cooldown
    throttle_events = 0
    rate_limit_events = 0
    retry_symbol_attempts = 0
    recovered_rate_limit_events = 0
    processed_provider_symbols = 0
    provider_batches = 0
    minimum_workers_seen = current_workers
    minimum_batch_size_seen = current_batch_size
    consecutive_throttle_batches = 0
    provider_circuit_opened = False
    provider_request_avoided_count = 0
    cursor = 0

    while cursor < len(misses):
        batch = misses[cursor : cursor + current_batch_size]
        cursor += len(batch)
        provider_batches += 1
        processed_provider_symbols += len(batch)

        batch_candidates, batch_errors = _run_provider_batch(
            batch,
            exchange,
            max_workers=current_workers,
        )
        candidates.extend(batch_candidates)

        initial_rate_limit_errors = _rate_limited(batch_errors)
        non_rate_limit_errors = _without_rate_limited(batch_errors)
        batch_rate_limits = len(initial_rate_limit_errors)
        rate_limit_events += batch_rate_limits
        rate_limit_ratio = batch_rate_limits / len(batch) if batch else 0.0
        should_throttle = (
            batch_rate_limits >= _RATE_LIMIT_COUNT_TO_THROTTLE
            or rate_limit_ratio >= _RATE_LIMIT_RATIO_TO_THROTTLE
        )

        unresolved_rate_limit_errors = initial_rate_limit_errors
        if initial_rate_limit_errors and retry_attempts > 0:
            retry_symbols = [error.symbol for error in initial_rate_limit_errors]
            for _ in range(retry_attempts):
                if not retry_symbols:
                    break
                if cooldown > 0:
                    time.sleep(cooldown)

                retry_symbol_attempts += len(retry_symbols)
                retry_candidates, retry_errors = _run_provider_batch(
                    retry_symbols,
                    exchange,
                    max_workers=1,
                )
                candidates.extend(retry_candidates)
                recovered_rate_limit_events += len(retry_symbols) - len(retry_errors)

                changed_category_errors = _without_rate_limited(retry_errors)
                non_rate_limit_errors.extend(changed_category_errors)
                unresolved_rate_limit_errors = _rate_limited(retry_errors)
                retry_symbols = [error.symbol for error in unresolved_rate_limit_errors]

        errors.extend(non_rate_limit_errors)
        errors.extend(unresolved_rate_limit_errors)

        if should_throttle:
            throttle_events += 1
            consecutive_throttle_batches += 1
            current_workers = 1
            minimum_workers_seen = 1
            current_batch_size = max(_MIN_BATCH_SIZE, current_batch_size // 2)
            minimum_batch_size_seen = min(
                minimum_batch_size_seen,
                current_batch_size,
            )
            cooldown = min(
                max_cooldown,
                max(base_cooldown, cooldown * 2 or base_cooldown),
            )
        else:
            consecutive_throttle_batches = 0
            if batch_rate_limits == 0:
                cooldown = base_cooldown
                if current_workers < initial_workers:
                    current_workers = min(initial_workers, current_workers + 1)
                if current_batch_size < configured_batch_size:
                    current_batch_size = min(
                        configured_batch_size,
                        current_batch_size + _MIN_BATCH_SIZE,
                    )

        if (
            consecutive_throttle_batches >= circuit_breaker_batches
            and len(candidates) >= candidate_buffer_required
            and cursor < len(misses)
        ):
            provider_circuit_opened = True
            provider_request_avoided_count = len(misses) - cursor
            break

    _sort_candidates(candidates)
    top_candidates = candidates[:top_n]
    for rank, candidate in enumerate(top_candidates, start=1):
        candidate.discovery_rank = rank

    selected_universe_count = len(symbols)
    actual_attempted_count = cache_hits + processed_provider_symbols
    error_diagnostics = base._error_diagnostics(errors)
    unresolved_rate_limit_count = int(
        (error_diagnostics.get("error_categories") or {}).get(
            "provider_rate_limited",
            0,
        )
    )
    cache_info = cache_status()
    cache_info.update(
        {
            "hit_count": cache_hits,
            "miss_count": len(misses),
            "hit_rate": round(cache_hits / selected_universe_count, 4)
            if selected_universe_count
            else 0.0,
        }
    )
    adaptive_provider = {
        "schema_version": "scanner-provider-throttle.v2",
        "configured_batch_size": configured_batch_size,
        "minimum_batch_size_seen": minimum_batch_size_seen,
        "provider_batches": provider_batches,
        "processed_provider_symbols": processed_provider_symbols,
        "provider_request_attempts": processed_provider_symbols + retry_symbol_attempts,
        "initial_workers": initial_workers,
        "minimum_workers_seen": minimum_workers_seen,
        "final_workers": current_workers,
        "rate_limit_events": rate_limit_events,
        "rate_limit_retry_attempts": retry_attempts,
        "retry_symbol_attempts": retry_symbol_attempts,
        "recovered_rate_limit_events": recovered_rate_limit_events,
        "unresolved_rate_limit_events": unresolved_rate_limit_count,
        "throttle_events": throttle_events,
        "base_cooldown_seconds": base_cooldown,
        "max_cooldown_seconds": max_cooldown,
        "threshold_rate_limit_ratio": _RATE_LIMIT_RATIO_TO_THROTTLE,
        "threshold_rate_limit_count": _RATE_LIMIT_COUNT_TO_THROTTLE,
        "circuit_breaker_batches": circuit_breaker_batches,
        "candidate_buffer_required": candidate_buffer_required,
        "provider_circuit_opened": provider_circuit_opened,
        "provider_request_avoided_count": provider_request_avoided_count,
        "trading_thresholds_relaxed": False,
        "production_execution_evidence_reused": False,
    }

    metadata = {
        **universe_sources,
        "requested_universe_count": selected_universe_count,
        "attempted_count": actual_attempted_count,
        "analyzed_count": len(candidates),
        "error_count": len(errors),
        "deferred_provider_count": provider_request_avoided_count,
        "success_rate": round(len(candidates) / actual_attempted_count, 4)
        if actual_attempted_count
        else 0.0,
        "requested_max_workers": max_workers,
        "effective_max_workers": initial_workers,
        "provider_worker_cap": provider_worker_cap,
        **error_diagnostics,
        "fundamental_cache": cache_info,
        "adaptive_provider_control": adaptive_provider,
        "top_n": top_n,
        "exchange": exchange,
        "excluded_non_tradable_symbols": sorted(
            base._NON_TRADABLE_DISCOVERY_SYMBOLS
        ),
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
