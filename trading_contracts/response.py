from typing import Any, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class StandardResponse(BaseModel):
    agent_type: str = "scanner"
    status: str
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
