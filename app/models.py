from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Generic, TypeVar, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.generics import GenericModel

T = TypeVar("T")

SCANNER_AGENT_TYPE = "scanner"
SCANNER_AGENT_VERSION = "1.1.0"
SCHEMA_VERSION = "1.0"

StrategyBucket = Literal["core_dividend", "value_rebound", "news_momentum"]
BucketHintStatus = Literal["suggested", "review", "conflict", "insufficient_evidence"]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="A list of stock symbols to scan. Defaults to a predefined list if empty.")
    screener: str = Field(default="thailand", description="The TradingView screener to use (e.g., 'thailand', 'america').")
    exchange: str = Field(default="SET", description="The stock exchange to use (e.g., 'SET', 'NASDAQ', 'NYSE').")


class BestFundamentalsRequest(BaseModel):
    universe: str = Field(default="NASDAQ_SP500", description="Universe to discover from. Currently supports NASDAQ_SP500.")
    max_universe: int = Field(default=1000, ge=1, le=6000, description="Maximum symbols to analyze from the broad market universe.")
    top_n: int = Field(default=10, ge=1, le=50, description="Number of fundamentally strong candidates to return.")
    exchange: str = Field(default="NASDAQ", description="Primary US exchange to use for market data lookup.")
    max_workers: int = Field(default=10, ge=1, le=20, description="Concurrent workers for analysis.")


class Candidate(BaseModel):
    symbol: str
    recommendation: str
    details: Dict[str, Any]


class ErrorDetail(BaseModel):
    symbol: str
    error: str


class StrategyBucketHintContract(BaseModel):
    """Non-binding Scanner evidence consumed by Manager_Agent."""

    bucket_hint_version: str = "scanner-bucket-hints-v2"
    bucket_hint_status: BucketHintStatus
    primary_strategy_bucket_hint: Optional[StrategyBucket] = None
    primary_strategy_bucket_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    strategy_bucket_confidence: float = Field(ge=0, le=1)
    strategy_bucket_hints: List[StrategyBucket] = Field(default_factory=list)
    bucket_hint_scores: Dict[str, float] = Field(default_factory=dict)
    bucket_hint_margin: float = 0.0
    bucket_hint_evidence: Dict[str, List[str]] = Field(default_factory=dict)
    bucket_hint_reasons: List[str] = Field(default_factory=list)
    bucket_hint_is_binding: bool = False
    manager_decision_required: bool = True
    controlled_strategy_buckets: List[StrategyBucket] = Field(default_factory=lambda: ["core_dividend", "value_rebound", "news_momentum"])


class CandidateResult(BaseModel):
    symbol: str
    confidence_score: Optional[float] = None
    recommendation: str = "hold"
    bucket_hint: Optional[StrategyBucketHintContract] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_bucket_hint(self):
        from app.services.candidate_bucket_context import enrich_candidate_metadata_with_bucket_hints

        candidate_context = {
            "symbol": self.symbol,
            "confidence_score": self.confidence_score,
            "recommendation": self.recommendation,
            **self.metadata,
        }
        enriched = enrich_candidate_metadata_with_bucket_hints(candidate_context, self.metadata)
        self.metadata = enriched
        self.bucket_hint = StrategyBucketHintContract.model_validate(enriched)
        return self


class ScannerCandidateContract(BaseModel):
    """
    Clean candidate payload for the multi-agent system.
    Scanner_Agent should discover candidates, not make final portfolio decisions.
    Manager_Agent can use these fields to call Fundamental_Agent, Technical_Agent,
    Learning_Agent, Database_Agent, and Execution_Agent.
    """

    symbol: str
    source_agent: str = "Scanner_Agent"
    candidate_score: Optional[float] = None
    discovery_rank: Optional[int] = None
    recommendation_hint: str = "WATCHLIST"
    exchange: Optional[str] = None
    screener: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    raw_scores: Dict[str, Any] = Field(default_factory=dict)
    bucket_hint: Optional[StrategyBucketHintContract] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_bucket_hint(self):
        from app.services.candidate_bucket_context import enrich_candidate_metadata_with_bucket_hints

        candidate_context = {
            "symbol": self.symbol,
            "candidate_score": self.candidate_score,
            "recommendation": self.recommendation_hint,
            **self.raw_scores,
        }
        enriched = enrich_candidate_metadata_with_bucket_hints(candidate_context, self.metadata)
        self.metadata = enriched
        self.bucket_hint = StrategyBucketHintContract.model_validate(enriched)
        for tag in enriched.get("bucket_hint_tags") or []:
            if tag not in self.tags:
                self.tags.append(tag)
        return self


class ScannerContractResult(BaseModel):
    scan_type: str = "candidate_discovery"
    count: int
    candidates: List[ScannerCandidateContract] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)


class ScannerResult(BaseModel):
    scan_type: str
    count: int
    candidates: List[CandidateResult] = Field(default_factory=list)


class StandardAgentResponse(GenericModel, Generic[T]):
    status: str
    agent_type: str = SCANNER_AGENT_TYPE
    version: str = SCANNER_AGENT_VERSION
    schema_version: str = SCHEMA_VERSION
    timestamp: str = Field(default_factory=utc_timestamp)
    correlation_id: Optional[str] = None
    data: Optional[T] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Any] = None
    confidence_score: Optional[float] = None

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_semantic(cls, value: str) -> str:
        parts = value.split(".")
        if not all(part.isdigit() for part in parts):
            raise ValueError('Schema version must be in semantic format (e.g., "1.0")')
        return value


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
