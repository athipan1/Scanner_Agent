from datetime import datetime

import pandas as pd

from app.services.financial_evidence_payload import build_financial_evidence_payload


def test_observed_fiscal_history_and_units_survive_handoff():
    dates = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    income = pd.DataFrame(
        [[172.8, 144, 120, 100], [6, 5, 4, 3]], index=["Total Revenue", "Diluted EPS"], columns=dates
    )
    cash = pd.DataFrame(
        [[50, 40, 30, 20], [-10, -8, -6, -4]],
        index=["Operating Cash Flow", "Capital Expenditure"],
        columns=dates,
    )
    payload = build_financial_evidence_payload(
        "TEST",
        {
            "annual_income_statement": income,
            "annual_cash_flow": cash,
            "info": {"returnOnEquity": 0.30, "debtToEquity": 25},
        },
    )
    values = payload["values"]
    assert values["Historical Revenue"]["2025-12-31"] == 172.8
    assert values["Historical EPS"]["2022-12-31"] == 3
    assert values["Operating Cash Flow"] == 50
    assert values["Free Cash Flow"] == 40
    assert values["ROE"] == 0.30
    assert values["Debt to Equity Ratio"] == 0.25
    assert payload["synthetic"] is False
    assert datetime.fromisoformat(payload["observed_at"]).tzinfo is not None


def test_missing_ocf_is_never_replaced_by_fcf_or_fabricated_history():
    payload = build_financial_evidence_payload("TEST", {"info": {"freeCashflow": 100}})
    assert payload["values"]["Operating Cash Flow"] is None
    assert payload["values"]["Historical Revenue"] == {}
    assert payload["values"]["Historical Free Cash Flow"] == {}
