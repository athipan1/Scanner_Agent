from app.services.candidate_data_enrichment import build_fundamental_data_bundle


def test_fundamental_bundle_reports_statement_and_market_coverage():
    financials = {
        "yf_symbol": "AAPL",
        "has_annual_income_statement": True,
        "has_annual_balance_sheet": True,
        "has_annual_cash_flow": True,
        "has_quarterly_income_statement": True,
        "has_quarterly_balance_sheet": False,
        "has_quarterly_cash_flow": True,
    }
    diagnostics = {
        "status": "success",
        "provider_errors": [],
    }
    market = {
        "market_data_sources": ["alpaca_latest_quote", "reused_yfinance_info"],
        "data_quality": {
            "status": "partial",
            "coverage_ratio": 0.9,
            "missing_fields": ["pegRatio"],
        },
    }

    bundle = build_fundamental_data_bundle(
        "AAPL",
        financials,
        diagnostics,
        market,
    )

    assert bundle["schema_version"] == "scanner-data-bundle.v1"
    assert bundle["data_quality"]["status"] == "partial"
    assert "yfinance_financial_statements" in bundle["sources"]
    assert "alpaca_latest_quote" in bundle["sources"]
    statements = bundle["financial_statements"]
    assert statements["provider_status"] == "success"
    assert statements["available_statements"] == [
        "annual_income_statement",
        "annual_balance_sheet",
        "annual_cash_flow",
        "quarterly_income_statement",
        "quarterly_cash_flow",
    ]
    assert statements["missing_statements"] == ["quarterly_balance_sheet"]
