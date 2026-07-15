import pandas as pd

from app.data_sources import financial_statements
from app.services import fundamental_discovery


class EmptyTicker:
    income_stmt = pd.DataFrame()
    financials = pd.DataFrame()
    balance_sheet = pd.DataFrame()
    balancesheet = pd.DataFrame()
    cashflow = pd.DataFrame()
    cash_flow = pd.DataFrame()
    quarterly_income_stmt = pd.DataFrame()
    quarterly_financials = pd.DataFrame()
    quarterly_balance_sheet = pd.DataFrame()
    quarterly_balancesheet = pd.DataFrame()
    quarterly_cashflow = pd.DataFrame()
    quarterly_cash_flow = pd.DataFrame()


class FailingTicker:
    @property
    def income_stmt(self):
        raise RuntimeError("provider transport failed")

    @property
    def financials(self):
        raise RuntimeError("provider transport failed")

    @property
    def balance_sheet(self):
        raise RuntimeError("provider transport failed")

    @property
    def balancesheet(self):
        raise RuntimeError("provider transport failed")

    @property
    def cashflow(self):
        raise RuntimeError("provider transport failed")

    @property
    def cash_flow(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_income_stmt(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_financials(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_balance_sheet(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_balancesheet(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_cashflow(self):
        raise RuntimeError("provider transport failed")

    @property
    def quarterly_cash_flow(self):
        raise RuntimeError("provider transport failed")

    def __getattr__(self, name):
        if name.startswith("get_"):
            def fail(**kwargs):
                raise RuntimeError("provider transport failed")
            return fail
        raise AttributeError(name)


def test_no_statements_is_not_misclassified_as_provider_failure(monkeypatch):
    monkeypatch.setattr(financial_statements.yf, "Ticker", lambda symbol: EmptyTicker())

    data, diagnostics = financial_statements.get_financials_with_diagnostics(
        "EMPTY",
        "NASDAQ",
    )

    assert data is None
    assert diagnostics["status"] == "no_statements"
    assert diagnostics["provider_errors"] == []


def test_provider_failures_are_preserved_for_error_taxonomy(monkeypatch):
    monkeypatch.setattr(financial_statements.yf, "Ticker", lambda symbol: FailingTicker())

    data, diagnostics = financial_statements.get_financials_with_diagnostics(
        "FAIL",
        "NASDAQ",
    )

    assert data is None
    assert diagnostics["status"] == "provider_error"
    assert diagnostics["provider_errors"]
    assert fundamental_discovery._classify_discovery_error(
        "financial provider error [annual_income_statement]: provider transport failed"
    ) == "financial_provider_error"
