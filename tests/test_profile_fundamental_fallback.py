from __future__ import annotations

import pandas as pd
import pytest

from app.analyzers import quality_analyzer
from app.data_sources import financial_statements, market_data
from app.services import fundamental_discovery


class ProfileOnlyTicker:
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

    def get_info(self):
        return {
            "currentPrice": 50.0,
            "marketCap": 10_000_000_000,
            "returnOnEquity": 0.21,
            "returnOnAssets": 0.10,
            "debtToEquity": 42.0,
            "profitMargins": 0.18,
            "freeCashflow": 250_000_000,
            "trailingPE": 18.0,
            "priceToBook": 2.1,
            "revenueGrowth": 0.12,
            "earningsGrowth": 0.15,
            "sector": "Technology",
            "industry": "Software",
        }


class SparseProfileTicker(ProfileOnlyTicker):
    def get_info(self):
        return {
            "currentPrice": 10.0,
            "marketCap": 100_000_000,
            "trailingPE": 20.0,
        }


def test_profile_only_provider_evidence_is_retained_without_fabricating_statements(
    monkeypatch,
):
    monkeypatch.setattr(
        financial_statements.yf,
        "Ticker",
        lambda symbol: ProfileOnlyTicker(),
    )

    data, diagnostics = financial_statements.get_financials_with_diagnostics(
        "PROFILE",
        "NASDAQ",
    )

    assert data is not None
    assert diagnostics["status"] == "profile_fallback"
    assert diagnostics["profile_evidence"]["usable"] is True
    assert data["financial_evidence_mode"] == "profile_fallback"
    assert data["has_annual_financials"] is False
    assert data["has_quarterly_financials"] is False
    assert data["annual_income_statement"] is None
    assert data["annual_cash_flow"] is None
    assert data["financial_provider_diagnostics"]["statement_evidence_available"] is False


def test_sparse_profile_is_still_rejected(monkeypatch):
    monkeypatch.setattr(
        financial_statements.yf,
        "Ticker",
        lambda symbol: SparseProfileTicker(),
    )

    data, diagnostics = financial_statements.get_financials_with_diagnostics(
        "SPARSE",
        "NASDAQ",
    )

    assert data is None
    assert diagnostics["status"] == "no_statements"
    assert diagnostics["profile_evidence"]["usable"] is False


def test_quality_analyzer_normalizes_profile_units_without_inventing_statement_rows():
    financials = {"info": ProfileOnlyTicker().get_info()}

    assert quality_analyzer.calculate_roe(financials) == pytest.approx(21.0)
    assert quality_analyzer.calculate_roa(financials) == pytest.approx(10.0)
    assert quality_analyzer.calculate_debt_to_equity(financials) == pytest.approx(0.42)
    assert quality_analyzer.calculate_profit_margins(financials) == pytest.approx(18.0)
    assert quality_analyzer.calculate_free_cash_flow(financials) == pytest.approx(250_000_000)


def test_profile_fallback_can_produce_research_candidate_with_partial_evidence(monkeypatch):
    profile = ProfileOnlyTicker().get_info()
    financials = {
        "income_statement": None,
        "balance_sheet": None,
        "cash_flow": None,
        "annual_income_statement": None,
        "annual_balance_sheet": None,
        "annual_cash_flow": None,
        "quarterly_income_statement": None,
        "quarterly_balance_sheet": None,
        "quarterly_cash_flow": None,
        "has_annual_financials": False,
        "has_annual_income_statement": False,
        "has_annual_cash_flow": False,
        "has_annual_balance_sheet": False,
        "has_quarterly_financials": False,
        "has_quarterly_income_statement": False,
        "has_quarterly_cash_flow": False,
        "has_quarterly_balance_sheet": False,
        "yf_symbol": "PROFILE",
        "info": profile,
        "financial_evidence_mode": "profile_fallback",
        "financial_provider_diagnostics": {
            "status": "profile_fallback",
            "statement_evidence_available": False,
        },
    }
    diagnostics = {
        "status": "profile_fallback",
        "yf_symbol": "PROFILE",
        "provider_errors": [],
        "statement_evidence_available": False,
    }
    market = {
        **profile,
        "valuation_metric_count": 2,
        "valuation_data_complete": False,
        "market_data_sources": ["reused_yfinance_info"],
        "data_quality": {"status": "partial"},
        "provider_status": {"yfinance": "reused"},
        "provider_errors": [],
    }

    monkeypatch.setattr(
        fundamental_discovery.financial_statements,
        "get_financials_with_diagnostics",
        lambda symbol, exchange: (financials, diagnostics),
    )
    monkeypatch.setattr(
        fundamental_discovery.market_data,
        "get_market_data",
        lambda symbol, exchange, yfinance_info=None: market,
    )

    candidate = fundamental_discovery.analyze_fundamental_candidate(
        "PROFILE",
        "NASDAQ",
    )

    assert candidate.symbol == "PROFILE"
    assert candidate.candidate_score is not None
    assert candidate.metadata["financial_provider_diagnostics"]["status"] == "profile_fallback"
    assert candidate.metadata["has_annual_income_statement"] is False
    assert candidate.metadata["has_annual_cash_flow"] is False
    assert candidate.raw_scores["roe"] == pytest.approx(21.0)
    assert candidate.raw_scores["debt_to_equity"] == pytest.approx(0.42)
    assert candidate.raw_scores["evidence_coverage"] < 0.8
