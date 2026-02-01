from fastapi import FastAPI, HTTPException
from typing import List
from app.services.scanner import scan_market
from app.services.long_term_scanner import scan_long_term
from app.models import ScanRequest
from trading_contracts.scan import ScanResult, CandidateResult
from trading_contracts.response import StandardResponse
import logging

logging.basicConfig(level=logging.INFO)

# A default list of US tech stocks for testing purposes
DEFAULT_SYMBOLS = [
    "AAPL", "GOOG", "MSFT", "AMZN", "NVDA", "META", "TSLA"
]

app = FastAPI(
    title="Scanner_Agent",
    description="A market scanner agent for a multi-agent trading system.",
    version="1.0.0"
)

# A default list of top 20 Thai stocks for testing purposes
DEFAULT_SYMBOLS = [
    "PTT", "AOT", "DELTA", "CPALL", "BBL", "SCB", "KBANK", "GULF",
    "ADVANC", "SCC", "BDMS", "PTTEP", "EA", "CPN", "TRUE", "HMPRO",
    "INTUCH", "MINT", "CRC", "OR"
]

@app.get("/health", response_model=StandardResponse)
def health_check():
    """
    Healthcheck endpoint for Docker.
    """
    return StandardResponse(
        agent_type="scanner",
        status="success",
        data={"message": "healthy"}
    )

@app.post("/scan", response_model=StandardResponse)
def scan_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan. If the list is empty,
    it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    candidates_raw, errors = scan_market(symbols=symbols_to_scan)

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        for c in candidates_raw:
            symbol = c.symbol if hasattr(c, "symbol") else c.get("symbol")
            recommendation = c.recommendation if hasattr(c, "recommendation") else c.get("recommendation")
            if symbol:
                candidates.append(CandidateResult(
                    symbol=symbol,
                    confidence_score=None,
                    recommendation=recommendation
                ))

    return StandardResponse(
        status=status,
        data=ScanResult(candidates=candidates) if candidates else None,
        errors=errors if errors else None
    )

@app.post("/scan/fundamental", response_model=StandardResponse)
def scan_fundamental_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan for long-term investment opportunities.
    If the list is empty, it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    candidates_raw, errors = scan_long_term(symbols=symbols_to_scan)

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        for c in candidates_raw:
            symbol = c.get("symbol")
            # fundamental_score is 0-100, normalize to 0-1
            score = c.get("fundamental_score", 0) / 100.0
            if symbol:
                candidates.append(CandidateResult(
                    symbol=symbol,
                    confidence_score=score,
                    recommendation=c.get("grade")
                ))

    return StandardResponse(
        status=status,
        data=ScanResult(candidates=candidates) if candidates else None,
        errors=errors if errors else None
    )
