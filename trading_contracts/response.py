from typing import Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

class StandardResponse(BaseModel):
    agent: str = "Scanner_Agent"
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[Any] = None
    errors: Optional[List[Any]] = None
