from fastapi import FastAPI, HTTPException
from app.services.scanner import scan_market
from app.models import ScanRequest, ScanResponse, ScanData

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


@app.post("/scan", response_model=ScanResponse)
def scan_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan. If the list is empty,
    it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(
            status_code=400, detail="Symbol list cannot be empty if provided."
        )

    candidates, errors = scan_market(symbols=symbols_to_scan)

    status = "success"
    if errors:
        status = "partial_success" if candidates else "failure"

    return ScanResponse(
        status=status,
        data=ScanData(candidates=candidates) if candidates else None,
        errors=errors if errors else None
    )
