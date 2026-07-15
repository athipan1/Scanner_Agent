import pandas as pd
import pytest

from app.analyzers import quality_analyzer


def _financials():
    return {
        "income_statement": pd.DataFrame(
            {"2025": ["200", "1000"]},
            index=["Net Income", "Total Revenue"],
        ),
        "balance_sheet": pd.DataFrame(
            {"2025": ["500", "2000", "125"]},
            index=["Stockholders Equity", "Total Assets", "Total Debt"],
        ),
        "cash_flow": pd.DataFrame(
            {"2025": ["300", "-50"]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        ),
    }


def test_quality_metrics_accept_numeric_string_statement_cells():
    financials = _financials()

    assert quality_analyzer.calculate_roe(financials) == pytest.approx(40.0)
    assert quality_analyzer.calculate_roa(financials) == pytest.approx(10.0)
    assert quality_analyzer.calculate_debt_to_equity(financials) == pytest.approx(0.25)
    assert quality_analyzer.calculate_free_cash_flow(financials) == pytest.approx(250.0)
    assert quality_analyzer.calculate_profit_margins(financials) == pytest.approx(20.0)


def test_quality_metrics_ignore_unparseable_cells():
    financials = _financials()
    financials["balance_sheet"].loc["Total Debt", "2025"] = "unknown"

    assert quality_analyzer.calculate_debt_to_equity(financials) is None
