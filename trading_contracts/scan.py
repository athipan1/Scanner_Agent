from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class CandidateResult(BaseModel):
    symbol: str
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    recommendation: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ScannerResult(BaseModel):
    scan_type: str
    count: int
    candidates: List[CandidateResult] = Field(default_factory=list)
