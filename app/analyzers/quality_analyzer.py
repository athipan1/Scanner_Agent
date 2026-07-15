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


def calculate_roe(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Return on Equity from normalized statement cells."""

    net_income = _latest_value(financial_data.get("income_statement"), "Net Income")
    shareholder_equity = _latest_value(
        financial_data.get("balance_sheet"),
        "Stockholders Equity",
    )
    if net_income is None or shareholder_equity in (None, 0):
        return None
    return (net_income / shareholder_equity) * 100


def calculate_roa(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Return on Assets from normalized statement cells."""

    net_income = _latest_value(financial_data.get("income_statement"), "Net Income")
    total_assets = _latest_value(financial_data.get("balance_sheet"), "Total Assets")
    if net_income is None or total_assets in (None, 0):
        return None
    return (net_income / total_assets) * 100


def calculate_debt_to_equity(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Debt-to-Equity from normalized statement cells."""

    total_debt = _latest_value(financial_data.get("balance_sheet"), "Total Debt")
    shareholder_equity = _latest_value(
        financial_data.get("balance_sheet"),
        "Stockholders Equity",
    )
    if total_debt is None or shareholder_equity in (None, 0):
        return None
    return total_debt / shareholder_equity


def calculate_free_cash_flow(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate Free Cash Flow from normalized statement cells."""

    cash_flow = financial_data.get("cash_flow")
    operating_cash_flow = _latest_value(cash_flow, "Operating Cash Flow")
    capital_expenditure = _latest_value(cash_flow, "Capital Expenditure")
    if operating_cash_flow is None or capital_expenditure is None:
        return None
    return operating_cash_flow + capital_expenditure


def calculate_profit_margins(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate net profit margin from normalized statement cells."""

    income_statement = financial_data.get("income_statement")
    net_income = _latest_value(income_statement, "Net Income")
    total_revenue = _latest_value(income_statement, "Total Revenue")
    if net_income is None or total_revenue in (None, 0):
        return None
    return (net_income / total_revenue) * 100
