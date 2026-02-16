from fastapi import FastAPI, HTTPException
from typing import List
from app.services.scanner import scan_market
from app.services.long_term_scanner import scan_long_term
from app.models import ScanRequest
from app.config import settings
from trading_contracts.scan import ScannerResult, CandidateResult
from trading_contracts.response import StandardAgentResponse
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Scanner_Agent",
    description="A market scanner agent for a multi-agent trading system.",
    version="1.0.0"
)

@app.get("/health", response_model=StandardAgentResponse)
def health_check():
    """
    Healthcheck endpoint for Docker.
    """
    return StandardAgentResponse(
        agent_type="scanner",
        status="success",
        data={"message": "healthy"}
    )

@app.post("/scan", response_model=StandardAgentResponse)
def scan_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan. If the list is empty,
    it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else settings.DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    candidates_raw, errors = scan_market(
        symbols=symbols_to_scan,
        screener=request.screener,
        exchange=request.exchange
    )

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        candidates = [c.symbol if hasattr(c, "symbol") else c.get("symbol") for c in candidates_raw]
        candidates = [c for c in candidates if c]

    error_dict = {e.symbol: e.error for e in errors} if errors else None
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
    If the list is empty, it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else settings.DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    candidates_raw, errors = scan_long_term(
        symbols=symbols_to_scan,
        exchange=request.exchange
    )

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        candidates = [c.symbol for c in candidates_raw if hasattr(c, "symbol")]

    error_dict = {e.symbol: e.error for e in errors} if errors else None
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
