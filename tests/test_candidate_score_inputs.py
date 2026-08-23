from app.services.candidate_score_inputs import build_candidate_score_inputs


def test_candidate_score_inputs_projects_scanner_evidence_without_authority():
    result = build_candidate_score_inputs(
        {
            "symbol": "AAPL",
            "technical": {
                "indicator_values": {
                    "close": 210.0,
                    "sma50": 205.0,
                    "sma200": 190.0,
                }
            },
            "market_rank": {
                "market_rank_score": 0.78,
                "return_20d": 0.08,
                "return_60d": 0.18,
                "volume_ratio": 1.4,
                "trend_score": 0.9,
                "benchmark_symbol": "SPY",
                "benchmark_return_20d": 0.03,
                "benchmark_return_60d": 0.08,
                "relative_return_20d": 0.05,
                "relative_return_60d": 0.10,
                "outperforming_benchmark": True,
            },
            "opportunity_profile": {
                "schema_version": "scanner-opportunity-profile.v1",
                "status": "qualified",
                "workflow_status": "ready",
                "opportunity_score": 0.82,
                "fail_closed": False,
                "execution_context": {
                    "relative_volume": 1.4,
                    "spread_bps": 4.0,
                    "atr_pct": 0.02,
                },
            },
            "data_quality": {
                "analysis": {"status": "complete", "coverage_ratio": 1.0}
            },
        }
    )

    assert result["schema_version"] == "candidate-score-inputs.v1"
    assert result["technical"]["price_above_sma200"] is True
    assert result["technical"]["sma50_above_sma200"] is True
    assert result["market_strength"]["outperforming_benchmark"] is True
    assert result["market_strength"]["relative_strength_passed"] is True
    assert result["market_strength"]["relative_return_20d"] == 0.05
    assert result["market_strength"]["relative_return_60d"] == 0.10
    assert result["market_strength"]["method"] == "benchmark_relative_returns"
    assert result["market_strength"]["stronger_than_universe_proxy"] is True
    assert result["market_strength"]["universe_rank_proxy"] is True
    assert result["technical"]["relative_volume"] == 1.4
    assert result["authority"]["broker_order_authorized"] is False
    assert result["authority"]["risk_approval_allowed"] is False
    assert result["authority"]["execution_agent_allowed"] is False


def test_universe_rank_alone_cannot_claim_benchmark_relative_strength():
    result = build_candidate_score_inputs(
        {
            "symbol": "AAPL",
            "technical": {
                "indicator_values": {
                    "close": 210.0,
                    "sma50": 205.0,
                    "sma200": 190.0,
                }
            },
            "market_rank": {
                "market_rank_score": 0.90,
                "return_20d": 0.15,
                "return_60d": 0.30,
                "volume_ratio": 1.5,
            },
            "opportunity_profile": {
                "status": "qualified",
                "fail_closed": False,
                "execution_context": {"relative_volume": 1.5},
            },
            "data_quality": {
                "analysis": {"status": "complete", "coverage_ratio": 1.0}
            },
        }
    )

    assert result["market_strength"]["universe_rank_proxy"] is True
    assert result["market_strength"]["stronger_than_universe_proxy"] is None
    assert result["market_strength"]["outperforming_benchmark"] is None
    assert result["market_strength"]["relative_strength_passed"] is None
    assert result["market_strength"]["method"] == "unavailable"


def test_candidate_score_inputs_fail_closed_on_missing_evidence():
    result = build_candidate_score_inputs(
        {
            "symbol": "XYZ",
            "technical": {"indicator_values": {"close": 10.0}},
            "market_rank": {},
            "opportunity_profile": {
                "status": "avoid",
                "fail_closed": True,
                "execution_context": {},
            },
            "data_quality": {
                "analysis": {"status": "partial", "coverage_ratio": 0.5}
            },
        }
    )

    assert result["technical"]["price_above_sma200"] is None
    assert result["market_strength"]["stronger_than_universe_proxy"] is None
    assert result["market_strength"]["outperforming_benchmark"] is None
    assert result["market_strength"]["method"] == "unavailable"
    assert result["opportunity"]["fail_closed"] is True
    assert result["data_quality"]["technical_input_coverage"] < 1.0
