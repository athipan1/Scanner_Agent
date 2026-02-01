from typing import List, Optional
from pydantic import BaseModel

class CandidateResult(BaseModel):
    symbol: str
    confidence_score: Optional[float] = None
    recommendation: Optional[str] = None

class ScanResult(BaseModel):
    candidates: List[CandidateResult]
