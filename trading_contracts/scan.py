from typing import List, Optional
from pydantic import BaseModel

class ScanResult(BaseModel):
    symbols: List[str]
    score: Optional[float] = None
