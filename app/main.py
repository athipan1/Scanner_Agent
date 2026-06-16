from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from typing import Any, Dict, List, Optional
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
)
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Scanner_Agent",
    description="A market scanner agent for a multi-agent trading system.",
    version="1.0.0"
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _normalize_candidate(candidate: Any, default_recommendation: str = "hold") -> Optional[CandidateResult]:
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
    for key in ("details", "quality", "growth", "valuation", "thesis", "grade"):
        value = _get_value(candidate, key, None)
        if value is not None:
            metadata[key] = value.model_dump() if hasattr(value, "model_dump") else value

    return CandidateResult(
        symbol=str(symbol),
        confidence_score=confidence_score,
        recommendation=str(recommendation),
        metadata=metadata,
    )


def _mock_candidates(symbols: List[str], scan_type: str) -> List[CandidateResult]:
    return [
        CandidateResult(
            symbol=symbol,
            confidence_score=0.5,
            recommendation="hold",
            metadata={"source": "dev_fallback", "scan_type": scan_type},
        )
        for symbol in symbols[:5]
    ]


def _error_dict(errors: Any) -> Optional[Dict[str, str]]:
    if not errors:
        return None
    result: Dict[str, str] = {}
    for error in errors:
        symbol = _get_value(error, "symbol", "unknown")
        message = _get_value(error, "error", str(error))
        result[str(symbol)] = str(message)
    return result or None


@app.get("/health")
def health_check():
    """
    Lightweight healthcheck endpoint for Docker.
    """
    return {
        "status": "success",
        "agent_type": "scanner",
        "version": "1.0.0",
        "timestamp": _utc_timestamp(),
        "data": {"message": "healthy"},
        "error": None,
    }


@app.post("/discover-best-fundamentals", response_model=StandardAgentResponse)
def discover_best_fundamental_stocks(request: BestFundamentalsRequest):
    """
    Searches a broad US market universe, scores fundamentals, and returns
    the top candidates for Manager_Agent to analyze more deeply.
    """
    if request.universe.upper() != "NASDAQ_SP500":
        raise HTTPException(status_code=400, detail="Only NASDAQ_SP500 universe is currently supported.")

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
    return StandardAgentResponse(
        agent_type="scanner",
        status=status,
        data=ScannerContractResult(
            scan_type="best_fundamentals",
            count=len(candidates),
            candidates=candidates,
            metadata=metadata,
            errors=error_dict,
        ),
        error=error_dict if not candidates else None,
    )


@app.post("/scan", response_model=StandardAgentResponse)
def scan_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan. If the list is empty,
    it scans a default list of top Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else settings.DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    try:
        candidates_raw, errors = scan_market(
            symbols=symbols_to_scan,
            screener=request.screener,
            exchange=request.exchange
        )
    except Exception:
        logger.exception("Technical scan failed")
        if not settings.SCANNER_DEV_MODE:
            raise
        candidates_raw, errors = [], []

    candidates = [
        candidate for candidate in (
            _normalize_candidate(c, default_recommendation="hold") for c in (candidates_raw or [])
        )
        if candidate is not None
    ]

    error_dict = _error_dict(errors)
    if not candidates and settings.SCANNER_DEV_MODE:
        candidates = _mock_candidates(symbols_to_scan, scan_type="technical")
        error_dict = error_dict or {"dev_fallback": "Scanner returned no candidates; dev fallback candidates were generated."}

    status = "error" if (not candidates and error_dict) else "success"
    return StandardAgentResponse(
        agent_type="scanner",
        status=status,
        data=ScannerResult(
            scan_type="technical",
            count=len(candidates),
            candidates=candidates
        ),
        error=error_dict
    )


@app.post("/scan/fundamental", response_model=StandardAgentResponse)
def scan_fundamental_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan for long-term investment opportunities.
    If the list is empty, it scans a default list of top Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else settings.DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    try:
        candidates_raw, errors = scan_long_term(
            symbols=symbols_to_scan,
            exchange=request.exchange
        )
    except Exception:
        logger.exception("Fundamental scan failed")
        if not settings.SCANNER_DEV_MODE:
            raise
        candidates_raw, errors = [], []

    candidates = [
        candidate for candidate in (
            _normalize_candidate(c, default_recommendation="hold") for c in (candidates_raw or [])
        )
        if candidate is not None
    ]

    error_dict = _error_dict(errors)
    if not candidates and settings.SCANNER_DEV_MODE:
        candidates = _mock_candidates(symbols_to_scan, scan_type="fundamental")
        error_dict = error_dict or {"dev_fallback": "Scanner returned no candidates; dev fallback candidates were generated."}

    status = "error" if (not candidates and error_dict) else "success"
    return StandardAgentResponse(
        agent_type="scanner",
        status=status,
        data=ScannerResult(
            scan_type="fundamental",
            count=len(candidates),
            candidates=candidates
        ),
        error=error_dict
    )
