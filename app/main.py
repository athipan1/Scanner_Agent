from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from typing import Any, Dict, List, Optional, Tuple
from app.services.scanner import scan_market
from app.services.long_term_scanner import scan_long_term
from app.services.fundamental_discovery import discover_best_fundamentals
from app.models import (
    BestFundamentalsRequest,
    ScanRequest,
    ScannerContractResult,
    ScannerResult,
    CandidateResult,
    StandardAgentResponse,
    SCANNER_AGENT_TYPE,
    SCANNER_AGENT_VERSION,
    SCANNER_SERVICE_VERSION,
    SCHEMA_VERSION,
)
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Scanner_Agent",
    description="A market scanner agent for a multi-agent trading system.",
    version=SCANNER_SERVICE_VERSION,
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trading_mode() -> str:
    return str(settings.TRADING_MODE or "PAPER").upper()


def _dev_fallback_allowed() -> bool:
    return bool(settings.SCANNER_DEV_MODE) and _trading_mode() != "LIVE"


def _scanner_runtime_metadata() -> Dict[str, Any]:
    return {
        "trading_mode": _trading_mode(),
        "scanner_dev_mode": settings.SCANNER_DEV_MODE,
        "dev_fallback_allowed": _dev_fallback_allowed(),
        "bucket_hint_version": "scanner-bucket-hints-v2",
        "bucket_hint_policy_version": "scanner-bucket-hint-policy-v3",
        "generic_tag_bucket_hints": False,
    }


def build_response(
    status: str,
    data=None,
    error=None,
    metadata=None,
    correlation_id: Optional[str] = None,
    confidence_score=None,
):
    return StandardAgentResponse(
        status=status,
        agent_type=SCANNER_AGENT_TYPE,
        version=SCANNER_AGENT_VERSION,
        schema_version=SCHEMA_VERSION,
        correlation_id=correlation_id,
        data=data,
        metadata=metadata or {},
        error=error,
        confidence_score=confidence_score,
    )


def _raise_live_dev_fallback_forbidden(scan_type: str):
    raise HTTPException(
        status_code=503,
        detail=(
            "Scanner dev fallback is forbidden in LIVE mode for "
            f"{scan_type} scans."
        ),
    )


def _normalize_market_inputs(screener: str, exchange: str) -> Tuple[str, str]:
    normalized_exchange = (exchange or "NASDAQ").upper()
    normalized_screener = (screener or "america").lower()
    if normalized_exchange in {"US", "USA", "NASDAQ", "NYSE", "AMEX"}:
        normalized_screener = (
            "america"
            if normalized_screener in {"default", "us", "usa", "stock"}
            else normalized_screener
        )
        normalized_exchange = (
            "NASDAQ"
            if normalized_exchange in {"US", "USA"}
            else normalized_exchange
        )
    return normalized_screener, normalized_exchange


def _get_value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _normalize_candidate(
    candidate: Any,
    default_recommendation: str = "hold",
) -> Optional[CandidateResult]:
    symbol = _get_value(candidate, "symbol")
    if not symbol:
        return None

    confidence_score = _get_value(candidate, "confidence_score", None)
    if confidence_score is None:
        confidence_score = _get_value(candidate, "score", None)
    if confidence_score is None:
        confidence_score = _get_value(candidate, "fundamental_score", None)
    if confidence_score is not None:
        try:
            confidence_score = float(confidence_score)
            if confidence_score > 1.0:
                confidence_score = confidence_score / 100.0
            confidence_score = max(0.0, min(1.0, confidence_score))
        except (TypeError, ValueError):
            confidence_score = None

    recommendation = _get_value(candidate, "recommendation", None)
    if recommendation is None:
        recommendation = _get_value(candidate, "grade", None)
    if recommendation is None:
        recommendation = default_recommendation

    metadata: Dict[str, Any] = {}
    for key in (
        "details",
        "quality",
        "growth",
        "valuation",
        "thesis",
        "grade",
    ):
        value = _get_value(candidate, key, None)
        if value is not None:
            metadata[key] = (
                value.model_dump()
                if hasattr(value, "model_dump")
                else value
            )

    return CandidateResult(
        symbol=str(symbol),
        confidence_score=confidence_score,
        recommendation=str(recommendation),
        metadata=metadata,
    )


def _mock_candidates(
    symbols: List[str],
    scan_type: str,
) -> List[CandidateResult]:
    if not _dev_fallback_allowed():
        _raise_live_dev_fallback_forbidden(scan_type)
    return [
        CandidateResult(
            symbol=symbol,
            confidence_score=0.5,
            recommendation="hold",
            metadata={"source": "dev_fallback", "scan_type": scan_type},
        )
        for symbol in symbols[:5]
    ]


def _market_watchlist_candidates(
    symbols: List[str],
    scan_type: str,
    exchange: str,
) -> List[CandidateResult]:
    """Builds a non-dev fallback watchlist from live yfinance metadata."""
    candidates: List[CandidateResult] = []
    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning(
            "yfinance unavailable for market watchlist fallback: %s",
            exc,
        )
        return []

    for symbol in symbols[:10]:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("previousClose")
            )
            market_cap = info.get("marketCap")
            if price is None and market_cap is None:
                continue
            score = 0.50
            if isinstance(market_cap, (int, float)) and market_cap > 0:
                score = 0.55
            candidates.append(
                CandidateResult(
                    symbol=symbol,
                    confidence_score=score,
                    recommendation="WATCHLIST",
                    metadata={
                        "source": "yfinance_market_data",
                        "scan_type": scan_type,
                        "selection_mode": "watchlist_no_buy_signal",
                        "exchange": exchange,
                        "current_price": price,
                        "market_cap": market_cap,
                        "sector": info.get("sector"),
                        "industry": info.get("industry"),
                    },
                )
            )
        except Exception as exc:
            logger.debug(
                "market watchlist fallback failed for %s: %s",
                symbol,
                exc,
            )
            continue
    return candidates


def _error_dict(errors: Any) -> Optional[Dict[str, str]]:
    if not errors:
        return None
    result: Dict[str, str] = {}
    for error in errors:
        symbol = _get_value(error, "symbol", "unknown")
        message = _get_value(error, "error", str(error))
        result[str(symbol)] = str(message)
    return result or None


@app.get("/version", response_model=StandardAgentResponse[dict])
def version_check():
    return build_response(
        status="success",
        data={
            "agent_type": SCANNER_AGENT_TYPE,
            "version": SCANNER_AGENT_VERSION,
            "service_version": SCANNER_SERVICE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "api_contract": "multi-agent-trading-api-contract",
            "bucket_hint_version": "scanner-bucket-hints-v2",
            "bucket_hint_policy_version": "scanner-bucket-hint-policy-v3",
        },
        metadata={
            "required_operational_endpoints": [
                "/health",
                "/ready",
                "/version",
            ],
            "bucket_hint_is_binding": False,
            "manager_decision_required": True,
            "generic_tag_bucket_hints": False,
        },
    )


@app.get("/ready", response_model=StandardAgentResponse[dict])
def readiness_check():
    live_dev_fallback_violation = (
        settings.SCANNER_DEV_MODE and _trading_mode() == "LIVE"
    )
    ready = not live_dev_fallback_violation
    return build_response(
        status="success" if ready else "error",
        data={
            "ready": ready,
            "trading_mode": _trading_mode(),
            "scanner_dev_mode": settings.SCANNER_DEV_MODE,
            "dev_fallback_allowed": _dev_fallback_allowed(),
            "live_dev_fallback_violation": live_dev_fallback_violation,
            "technical_scan_endpoint": "/scan",
            "fundamental_scan_endpoint": "/scan/fundamental",
            "best_fundamentals_endpoint": "/discover-best-fundamentals",
            "bucket_hint_version": "scanner-bucket-hints-v2",
            "bucket_hint_policy_version": "scanner-bucket-hint-policy-v3",
            "generic_tag_bucket_hints": False,
        },
        metadata={"contract_source": "scanner-agent-runtime-contract"},
        error=(
            None
            if ready
            else {
                "code": "SCANNER_AGENT_NOT_READY",
                "message": "Scanner dev fallback is forbidden in LIVE mode.",
                "retryable": False,
            }
        ),
        confidence_score=1.0 if ready else 0.0,
    )


@app.get("/health", response_model=StandardAgentResponse[dict])
def health_check():
    return build_response(
        status="success",
        data={"message": "healthy"},
        metadata=_scanner_runtime_metadata(),
    )


@app.post("/discover-best-fundamentals", response_model=StandardAgentResponse)
def discover_best_fundamental_stocks(
    request: BestFundamentalsRequest,
    req: Request,
):
    correlation_id = req.headers.get("X-Correlation-ID")
    if request.universe.upper() != "NASDAQ_SP500":
        raise HTTPException(
            status_code=400,
            detail="Only NASDAQ_SP500 universe is currently supported.",
        )

    try:
        candidates, errors, metadata = discover_best_fundamentals(
            max_universe=request.max_universe,
            top_n=request.top_n,
            exchange=request.exchange,
            max_workers=request.max_workers,
        )
    except Exception as exc:
        logger.exception("Best fundamentals discovery failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    error_dict = _error_dict(errors) or {}
    status = "success" if candidates else "error"
    return build_response(
        status=status,
        data=ScannerContractResult(
            scan_type="best_fundamentals",
            count=len(candidates),
            candidates=candidates,
            metadata=metadata,
            errors=error_dict,
        ),
        error=error_dict if not candidates else None,
        metadata=_scanner_runtime_metadata(),
        correlation_id=correlation_id,
    )


@app.post("/scan", response_model=StandardAgentResponse)
def scan_stocks(request: ScanRequest, req: Request):
    correlation_id = req.headers.get("X-Correlation-ID")
    symbols_to_scan = (
        request.symbols if request.symbols else settings.DEFAULT_SYMBOLS
    )
    screener, exchange = _normalize_market_inputs(
        request.screener,
        request.exchange,
    )

    if not symbols_to_scan:
        raise HTTPException(
            status_code=400,
            detail="Symbol list cannot be empty if provided.",
        )

    try:
        candidates_raw, errors = scan_market(
            symbols=symbols_to_scan,
            screener=screener,
            exchange=exchange,
        )
    except Exception:
        logger.exception("Technical scan failed")
        if settings.SCANNER_DEV_MODE and _trading_mode() == "LIVE":
            _raise_live_dev_fallback_forbidden("technical")
        if not _dev_fallback_allowed():
            raise
        candidates_raw, errors = [], []

    candidates = [
        candidate
        for candidate in (
            _normalize_candidate(c, default_recommendation="hold")
            for c in (candidates_raw or [])
        )
        if candidate is not None
    ]

    error_dict = _error_dict(errors)
    if not candidates and settings.SCANNER_DEV_MODE:
        if _trading_mode() == "LIVE":
            _raise_live_dev_fallback_forbidden("technical")
        candidates = _mock_candidates(
            symbols_to_scan,
            scan_type="technical",
        )
        error_dict = error_dict or {
            "dev_fallback": (
                "Scanner returned no candidates; dev fallback candidates "
                "were generated."
            )
        }

    if not candidates and not settings.SCANNER_DEV_MODE:
        candidates = _market_watchlist_candidates(
            symbols_to_scan,
            "technical",
            exchange,
        )
        if candidates:
            error_dict = error_dict or {}
            error_dict["watchlist_fallback"] = (
                "No BUY candidates passed strict scanner thresholds; "
                "returned real market watchlist candidates."
            )

    status = "success" if candidates else "error" if error_dict else "success"
    return build_response(
        status=status,
        data=ScannerResult(
            scan_type="technical",
            count=len(candidates),
            candidates=candidates,
        ),
        error=error_dict,
        metadata=_scanner_runtime_metadata(),
        correlation_id=correlation_id,
    )


@app.post("/scan/fundamental", response_model=StandardAgentResponse)
def scan_fundamental_stocks(request: ScanRequest, req: Request):
    correlation_id = req.headers.get("X-Correlation-ID")
    symbols_to_scan = (
        request.symbols if request.symbols else settings.DEFAULT_SYMBOLS
    )
    _, exchange = _normalize_market_inputs(
        request.screener,
        request.exchange,
    )

    if not symbols_to_scan:
        raise HTTPException(
            status_code=400,
            detail="Symbol list cannot be empty if provided.",
        )

    try:
        candidates_raw, errors = scan_long_term(
            symbols=symbols_to_scan,
            exchange=exchange,
        )
    except Exception:
        logger.exception("Fundamental scan failed")
        if settings.SCANNER_DEV_MODE and _trading_mode() == "LIVE":
            _raise_live_dev_fallback_forbidden("fundamental")
        if not _dev_fallback_allowed():
            raise
        candidates_raw, errors = [], []

    candidates = [
        candidate
        for candidate in (
            _normalize_candidate(c, default_recommendation="hold")
            for c in (candidates_raw or [])
        )
        if candidate is not None
    ]

    error_dict = _error_dict(errors)
    if not candidates and settings.SCANNER_DEV_MODE:
        if _trading_mode() == "LIVE":
            _raise_live_dev_fallback_forbidden("fundamental")
        candidates = _mock_candidates(
            symbols_to_scan,
            scan_type="fundamental",
        )
        error_dict = error_dict or {
            "dev_fallback": (
                "Scanner returned no candidates; dev fallback candidates "
                "were generated."
            )
        }

    if not candidates and not settings.SCANNER_DEV_MODE:
        candidates = _market_watchlist_candidates(
            symbols_to_scan,
            "fundamental",
            exchange,
        )
        if candidates:
            error_dict = error_dict or {}
            error_dict["watchlist_fallback"] = (
                "No fundamental candidates passed strict scanner "
                "requirements; returned real market watchlist candidates."
            )

    status = "success" if candidates else "error" if error_dict else "success"
    return build_response(
        status=status,
        data=ScannerResult(
            scan_type="fundamental",
            count=len(candidates),
            candidates=candidates,
        ),
        error=error_dict,
        metadata=_scanner_runtime_metadata(),
        correlation_id=correlation_id,
    )
