from app.models import ScannerCandidateContract


def test_scanner_contract_preserves_candidate_score_inputs_in_data_bundle():
    candidate = ScannerCandidateContract(
        symbol="AAPL",
        candidate_score=0.8,
        recommendation_hint="WATCHLIST",
        metadata={
            "details": {
                "data_bundle": {
                    "symbol": "AAPL",
                    "technical": {
                        "indicator_values": {
                            "close": 210.0,
                            "sma50": 205.0,
                            "sma200": 190.0,
                        }
                    },
                    "market_rank": {
                        "market_rank_score": 0.8,
                        "return_20d": 0.08,
                        "return_60d": 0.20,
                        "volume_ratio": 1.4,
                        "trend_score": 0.9,
                        "benchmark_symbol": "SPY",
                        "benchmark_return_20d": 0.03,
                        "benchmark_return_60d": 0.08,
                        "relative_return_20d": 0.05,
                        "relative_return_60d": 0.12,
                        "outperforming_benchmark": True,
                    },
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": "qualified",
                        "workflow_status": "ready",
                        "opportunity_score": 0.82,
                        "fail_closed": False,
                        "execution_context": {"relative_volume": 1.4},
                    },
                    "data_quality": {
                        "analysis": {
                            "status": "complete",
                            "coverage_ratio": 1.0,
                        }
                    },
                }
            }
        },
    )

    bundle = candidate.metadata["details"]["data_bundle"]
    inputs = bundle["candidate_score_inputs"]
    assert inputs["schema_version"] == "candidate-score-inputs.v1"
    assert inputs["technical"]["price_above_sma200"] is True
    assert inputs["technical"]["sma50_above_sma200"] is True
    assert inputs["market_strength"]["outperforming_benchmark"] is True
    assert inputs["market_strength"]["relative_strength_passed"] is True
    assert inputs["market_strength"]["method"] == "benchmark_relative_returns"
    assert inputs["market_strength"]["stronger_than_universe_proxy"] is True
    assert inputs["authority"]["broker_order_authorized"] is False
