from fastapi import FastAPI, HTTPException
from typing import List
from app.services.scanner import scan_market
from app.services.long_term_scanner import scan_long_term
from app.models import ScanRequest
from trading_contracts.scan import ScanResult
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

@app.get("/health")
def health_check():
    """
    Healthcheck endpoint for Docker.
    """
    return {"status": "ok"}

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

    status = "success"
    if errors:
        status = "partial_success" if candidates_raw else "failure"

    symbols = []
    if candidates_raw:
        for c in candidates_raw:
            symbol = c.get("symbol") if isinstance(c, dict) else getattr(c, "symbol", None)
            if symbol:
                symbols.append(symbol)

    return StandardResponse(
        status=status,
        data=ScanResult(
            symbols=symbols,
            score=None  # Technical scan doesn't provide a single aggregate score yet
        ) if symbols else None,
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

    status = "success"
    if errors:
        status = "partial_success" if candidates_raw else "failure"

    # Calculate an average fundamental score and collect symbols
    symbols = []
    avg_score = None
    if candidates_raw:
        scores = []
        for c in candidates_raw:
            # Handle both dict and object for robustness, though scan_long_term currently returns dicts
            symbol = c.get("symbol") if isinstance(c, dict) else getattr(c, "symbol", None)
            score = c.get("fundamental_score", 0) if isinstance(c, dict) else getattr(c, "fundamental_score", 0)

            if symbol:
                symbols.append(symbol)
            scores.append(score)

        if scores:
            avg_score = sum(scores) / len(scores) / 100.0  # Normalize to 0-1 range

    return StandardResponse(
        status=status,
        data=ScanResult(
            symbols=symbols,
            score=avg_score
        ) if symbols else None,
        errors=errors if errors else None
    )
