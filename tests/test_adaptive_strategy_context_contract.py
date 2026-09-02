from app.models import ScannerCandidateContract
from app.services.adaptive_production_discovery import _attach_strategy_context


def test_bucket_hint_is_available_to_strategy_aware_production_enrichment():
    candidate = ScannerCandidateContract(
        symbol="VALUE",
        candidate_score=0.78,
        recommendation_hint="FUNDAMENTAL_TOP_10",
        raw_scores={
            "fundamental_score": 82.0,
            "valuation_score": 90.0,
            "quality_score": 70.0,
            "growth_score": 55.0,
        },
        metadata={
            "source": "real_market_fundamental_discovery",
            "data_bundle": {"schema_version": "scanner-data-bundle.v1"},
        },
    )

    assert candidate.metadata.get("primary_strategy_bucket_hint") is not None
    _attach_strategy_context(candidate)

    context = candidate.metadata["data_bundle"]["strategy_context"]
    assert context["primary_strategy_bucket_hint"] == candidate.metadata[
        "primary_strategy_bucket_hint"
    ]
    assert context["strategy_bucket_confidence"] == candidate.metadata[
        "strategy_bucket_confidence"
    ]
    assert context["is_binding"] is False
    assert context["manager_decision_required"] is True
