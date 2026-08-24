from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from app.data_sources.market_data import get_market_snapshot
from app.services.candidate_score_inputs import build_candidate_score_inputs
from app.services.market_ranker import rank_market_symbols
from app.services.opportunity_profile import build_opportunity_profile
from app.services.scanner import fetch_analysis

PRODUCTION_ENRICHMENT_VERSION = "scanner-production-enrichment.v1"
_REQUIRED_TECHNICAL_FIELDS = (
    "close",
    "rsi",
    "macd",
    "sma50",
    "sma200",
    "atr",
)


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _finite(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_number(values: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        number = _finite(values.get(name))
        if number is not None:
            return number
    return None


def _technical_values(indicators: Mapping[str, Any]) -> Dict[str, Any]:
    """Project TradingView fields into Scanner's stable technical contract."""

    values = {
        "close": _first_number(indicators, "close", "Close"),
        "rsi": _first_number(indicators, "RSI", "RSI[1]"),
        "macd": _first_number(indicators, "MACD.macd", "MACD"),
        "macd_signal": _first_number(indicators, "MACD.signal"),
        "sma50": _first_number(indicators, "SMA50", "SMA50[1]"),
        "sma200": _first_number(indicators, "SMA200", "SMA200[1]"),
        "volume": _first_number(indicators, "volume", "Volume"),
        "volume_ma": _first_number(
            indicators,
            "Volume MA",
            "volume_ma",
            "SMA20.volume",
        ),
        "atr": _first_number(indicators, "ATR", "ATR[1]"),
        "high_52w": _first_number(
            indicators,
            "High.52W",
            "52 Week High",
            "high_52w",
        ),
    }
    close = _finite(values.get("close"))
    atr = _finite(values.get("atr"))
    if close is not None and close > 0 and atr is not None:
        values["atr_pct"] = round(atr / close, 8)

    volume = _finite(values.get("volume"))
    volume_ma = _finite(values.get("volume_ma"))
    if volume is not None and volume_ma is not None and volume_ma > 0:
        values["volume_ratio"] = round(volume / volume_ma, 8)
    return values


def _analysis_quality(values: Mapping[str, Any]) -> Dict[str, Any]:
    available = [
        field for field in _REQUIRED_TECHNICAL_FIELDS if values.get(field) is not None
    ]
    missing = [
        field for field in _REQUIRED_TECHNICAL_FIELDS if values.get(field) is None
    ]
    ratio = round(len(available) / len(_REQUIRED_TECHNICAL_FIELDS), 4)
    return {
        "status": "complete" if not missing else "partial" if available else "missing",
        "coverage_ratio": ratio,
        "coverage_scope": "analysis_ready",
        "purpose": "pre_downstream_technical_fundamental_handoff",
        "required_components": ["technical"],
        "complete_components": ["technical"] if not missing else [],
        "partial_components": ["technical"] if available and missing else [],
        "missing_components": ["technical"] if not available else [],
        "required_fields": list(_REQUIRED_TECHNICAL_FIELDS),
        "available_fields": available,
        "missing_fields": missing,
    }


def _fundamental_bundle(candidate: Any) -> Dict[str, Any]:
    payload = _mapping(candidate)
    metadata = _mapping(payload.get("metadata"))
    return _mapping(metadata.get("data_bundle"))


def _is_fundamental_discovery_candidate(candidate: Any) -> bool:
    payload = _mapping(candidate)
    metadata = _mapping(payload.get("metadata"))
    return metadata.get("source") == "real_market_fundamental_discovery"


def _set_candidate_metadata(candidate: Any, metadata: Dict[str, Any]) -> None:
    if hasattr(candidate, "metadata"):
        candidate.metadata = metadata
    elif isinstance(candidate, dict):
        candidate["metadata"] = metadata


def _mark_enrichment(
    candidate: Any,
    *,
    status: str,
    reason: str | None = None,
    exchange: str | None = None,
) -> None:
    payload = _mapping(candidate)
    metadata = _mapping(payload.get("metadata"))
    metadata["production_enrichment"] = {
        "schema_version": PRODUCTION_ENRICHMENT_VERSION,
        "status": status,
        "reason": reason,
        "exchange": exchange,
        "broker_order_authorized": False,
        "manager_decision_required": True,
    }
    _set_candidate_metadata(candidate, metadata)


def enrich_fundamental_candidates_for_production(
    candidates: Iterable[Any],
    *,
    default_exchange: str = "NASDAQ",
) -> Tuple[List[Any], Dict[str, Any]]:
    """Hydrate final fundamental candidates with Scanner evidence needed by Manager.

    Broad fundamental discovery intentionally avoids TradingView/history fan-out across
    hundreds of symbols. This second phase runs only on the already-selected final
    candidates. It adds daily technical evidence, SPY-relative market strength, a
    fresh execution snapshot and candidate-score inputs. Safety gates are unchanged:
    stale/crossed/wide quotes still fail closed and Scanner never authorizes orders.
    """

    rows = list(candidates)
    targets = [row for row in rows if _is_fundamental_discovery_candidate(row)]
    if not targets:
        return rows, {
            "schema_version": PRODUCTION_ENRICHMENT_VERSION,
            "requested_count": 0,
            "enriched_count": 0,
            "failed_count": 0,
            "production_qualified_count": 0,
            "broker_order_authorized": False,
        }

    symbols = [str(_mapping(row).get("symbol") or "").upper() for row in targets]
    try:
        _, market_rank_metadata = rank_market_symbols(symbols)
    except Exception:
        market_rank_metadata = {}

    enriched_count = 0
    failed_count = 0
    production_qualified_count = 0
    failures: Dict[str, str] = {}

    for candidate in targets:
        payload = _mapping(candidate)
        symbol = str(payload.get("symbol") or "").upper()
        candidate_exchange = str(
            payload.get("exchange") or default_exchange or "NASDAQ"
        ).upper()
        try:
            technical_result = fetch_analysis(symbol, "america", candidate_exchange)
            if technical_result.get("error"):
                raise RuntimeError(str(technical_result.get("error")))

            resolved_exchange = str(
                technical_result.get("exchange") or candidate_exchange
            ).upper()
            technical_values = _technical_values(
                _mapping(technical_result.get("indicators"))
            )
            analysis_quality = _analysis_quality(technical_values)

            bundle = _fundamental_bundle(candidate)
            if not bundle:
                raise RuntimeError("fundamental candidate has no scanner-data-bundle.v1")

            existing_market = _mapping(bundle.get("market_snapshot"))
            fresh_market = get_market_snapshot(
                symbol,
                exchange=resolved_exchange,
                yfinance_info=existing_market or None,
                include_execution_history=True,
            )

            enriched_bundle = dict(bundle)
            enriched_bundle["market_snapshot"] = fresh_market
            enriched_bundle["technical"] = {
                "provider": "tradingview",
                "resolved_exchange": resolved_exchange,
                "recommendation": _mapping(technical_result.get("analysis")).get(
                    "RECOMMENDATION"
                ),
                "indicator_values": technical_values,
            }
            enriched_bundle["market_rank"] = _mapping(
                market_rank_metadata.get(symbol)
            )

            quality = _mapping(enriched_bundle.get("data_quality"))
            quality["analysis"] = analysis_quality
            # Fundamental discovery did not previously publish a top-level coverage
            # ratio. For this bundle type the production-enrichment scope is the
            # first well-defined pre-analysis ratio and is what opportunity scoring
            # should consume.
            quality["coverage_ratio"] = analysis_quality["coverage_ratio"]
            quality["coverage_scope"] = "production_enrichment"
            quality["market_provider_status"] = _mapping(
                fresh_market.get("provider_status")
            )
            quality["market_provider_errors"] = list(
                fresh_market.get("provider_errors") or []
            )
            enriched_bundle["data_quality"] = quality

            profile = build_opportunity_profile(enriched_bundle)
            enriched_bundle["opportunity_profile"] = profile
            enriched_bundle["candidate_score_inputs"] = build_candidate_score_inputs(
                enriched_bundle
            )

            metadata = _mapping(payload.get("metadata"))
            metadata["data_bundle"] = enriched_bundle
            metadata["production_enrichment"] = {
                "schema_version": PRODUCTION_ENRICHMENT_VERSION,
                "status": "complete",
                "exchange": resolved_exchange,
                "analysis_coverage_ratio": analysis_quality["coverage_ratio"],
                "opportunity_status": profile.get("status"),
                "opportunity_score": profile.get("opportunity_score"),
                "fail_closed": profile.get("fail_closed"),
                "broker_order_authorized": False,
                "manager_decision_required": True,
            }
            _set_candidate_metadata(candidate, metadata)
            enriched_count += 1
            if profile.get("status") == "qualified" and profile.get("fail_closed") is not True:
                production_qualified_count += 1
        except Exception as exc:
            failed_count += 1
            reason = f"{type(exc).__name__}: {exc}"[:300]
            failures[symbol] = reason
            _mark_enrichment(
                candidate,
                status="review",
                reason=reason,
                exchange=candidate_exchange,
            )

    return rows, {
        "schema_version": PRODUCTION_ENRICHMENT_VERSION,
        "requested_count": len(targets),
        "enriched_count": enriched_count,
        "failed_count": failed_count,
        "production_qualified_count": production_qualified_count,
        "failures": failures,
        "broker_order_authorized": False,
        "manager_decision_required": True,
    }
