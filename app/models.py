from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="A list of stock symbols to scan. Defaults to a predefined list if empty.")

class Candidate(BaseModel):
    symbol: str
    recommendation: str
    details: Dict[str, Any]

class ScanData(BaseModel):
    candidates: List[Candidate]

class ErrorDetail(BaseModel):
    symbol: str
    error: str

class ScanResponse(BaseModel):
    agent: str = "Scanner_Agent"
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[ScanData] = None
    errors: Optional[List[ErrorDetail]] = None
