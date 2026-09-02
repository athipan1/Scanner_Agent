from app.models import ScannerCandidateContract
from app.services.adaptive_production_discovery import _attach_strategy_context


def test_bucket_hint_is_available_to_strategy_aware_production_enrichment():
    candidate = ScannerCandidateContract(
        symbol="VALUE",
        candidate_score=0.78,
        recommendation_hint="FUNDAMENTAL_TOP_10",
        raw_scores={
            "quality_score": 55.0,
            "valuation_score": 90.0,
            "growth_score": 25.0,
            "free_cash_flow": 100_000.0,
            "debt_to_equity": 2.0,
            "pe_ratio": 10.0,
            "pb_ratio": 1.2,
        },
        metadata={
            "source": "real_market_fundamental_discovery",
            "sector": "Financial Services",
            "data_bundle": {"schema_version": "scanner-data-bundle.v1"},
        },
    )

    assert candidate.metadata["primary_strategy_bucket_hint"] == "value_rebound"
    _attach_strategy_context(candidate)

    context = candidate.metadata["data_bundle"]["strategy_context"]
    assert context["primary_strategy_bucket_hint"] == "value_rebound"
    assert context["strategy_bucket_confidence"] == candidate.metadata[
        "strategy_bucket_confidence"
    ]
    assert context["is_binding"] is False
    assert context["manager_decision_required"] is True
