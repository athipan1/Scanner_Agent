from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Generic, TypeVar
from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

T = TypeVar("T")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="A list of stock symbols to scan. Defaults to a predefined list if empty.")
    screener: str = Field(default="thailand", description="The TradingView screener to use (e.g., 'thailand', 'america').")
    exchange: str = Field(default="SET", description="The stock exchange to use (e.g., 'SET', 'NASDAQ', 'NYSE').")


class Candidate(BaseModel):
    symbol: str
    recommendation: str
    details: Dict[str, Any]


class ErrorDetail(BaseModel):
    symbol: str
    error: str


class CandidateResult(BaseModel):
    symbol: str
    confidence_score: Optional[float] = None
    recommendation: str = "hold"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScannerResult(BaseModel):
    scan_type: str
    count: int
    candidates: List[CandidateResult] = Field(default_factory=list)


class StandardAgentResponse(GenericModel, Generic[T]):
    status: str
    agent_type: str = "scanner"
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=utc_timestamp)
    data: Optional[T] = None
    error: Optional[Any] = None
    confidence_score: Optional[float] = None


# Internal models for Fundamental analysis results
class QualityMetrics(BaseModel):
    roe: Optional[float]
    roa: Optional[float]
    debt_to_equity: Optional[float]
    free_cash_flow: Optional[float]
    profit_margins: Optional[float]
    score: Optional[float]


class GrowthMetrics(BaseModel):
    revenue_cagr: Optional[float]
    eps_growth: Optional[float]
    score: Optional[float]


class ValuationMetrics(BaseModel):
    pe_ratio: Optional[float]
    peg_ratio: Optional[float]
    pb_ratio: Optional[float]
    score: Optional[float]


class FundamentalCandidate(BaseModel):
    symbol: str
    grade: str
    fundamental_score: float
    quality: QualityMetrics
    growth: GrowthMetrics
    valuation: ValuationMetrics
    thesis: str
