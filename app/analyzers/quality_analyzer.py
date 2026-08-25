import math
from typing import Any, Dict, Optional


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _latest_value(statement: Any, row_name: str) -> Optional[float]:
    try:
        if statement is None or statement.empty:
            return None
        return _number(statement.loc[row_name].iloc[0])
    except (KeyError, IndexError, AttributeError, TypeError, ValueError):
        return None


def _profile_value(financial_data: Dict[str, Any], key: str) -> Optional[float]:
    info = financial_data.get("info")
    if not isinstance(info, dict):
        return None
    return _number(info.get(key))


def _profile_decimal_to_percent(value: Any) -> Optional[float]:
    number = _number(value)
    return None if number is None else number * 100.0


def calculate_roe(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Return on Equity from statements, then real provider profile."""

    net_income = _latest_value(financial_data.get("income_statement"), "Net Income")
    shareholder_equity = _latest_value(
        financial_data.get("balance_sheet"),
        "Stockholders Equity",
    )
    if net_income is not None and shareholder_equity not in (None, 0):
        return (net_income / shareholder_equity) * 100
    return _profile_decimal_to_percent(_profile_value(financial_data, "returnOnEquity"))


def calculate_roa(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Return on Assets from statements, then real provider profile."""

    net_income = _latest_value(financial_data.get("income_statement"), "Net Income")
    total_assets = _latest_value(financial_data.get("balance_sheet"), "Total Assets")
    if net_income is not None and total_assets not in (None, 0):
        return (net_income / total_assets) * 100
    return _profile_decimal_to_percent(_profile_value(financial_data, "returnOnAssets"))


def calculate_debt_to_equity(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Debt-to-Equity from statements, then yfinance percent profile."""

    total_debt = _latest_value(financial_data.get("balance_sheet"), "Total Debt")
    shareholder_equity = _latest_value(
        financial_data.get("balance_sheet"),
        "Stockholders Equity",
    )
    if total_debt is not None and shareholder_equity not in (None, 0):
        return total_debt / shareholder_equity
    profile = _profile_value(financial_data, "debtToEquity")
    return None if profile is None else profile / 100.0


def calculate_free_cash_flow(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Free Cash Flow from statements, then real provider profile."""

    cash_flow = financial_data.get("cash_flow")
    operating_cash_flow = _latest_value(cash_flow, "Operating Cash Flow")
    capital_expenditure = _latest_value(cash_flow, "Capital Expenditure")
    if operating_cash_flow is not None and capital_expenditure is not None:
        return operating_cash_flow + capital_expenditure
    return _profile_value(financial_data, "freeCashflow")


def calculate_profit_margins(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate net margin from statements, then provider decimal profile."""

    income_statement = financial_data.get("income_statement")
    net_income = _latest_value(income_statement, "Net Income")
    total_revenue = _latest_value(income_statement, "Total Revenue")
    if net_income is not None and total_revenue not in (None, 0):
        return (net_income / total_revenue) * 100
    return _profile_decimal_to_percent(_profile_value(financial_data, "profitMargins"))
