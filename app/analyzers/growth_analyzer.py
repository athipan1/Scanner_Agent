from typing import Optional, Dict, Any
import pandas as pd
import numpy as np


def _get_row(df: pd.DataFrame, row_names: list[str]):
    for row in row_names:
        if row in df.index:
            return df.loc[row]
    return None


def _safe_growth(latest: float, previous: float) -> Optional[float]:
    try:
        if previous == 0 or previous is None or latest is None:
            return None
        return ((float(latest) - float(previous)) / abs(float(previous))) * 100
    except Exception:
        return None


def calculate_revenue_cagr(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculates the Compound Annual Growth Rate of revenue over a specified period."""
    try:
        income_statement = financial_data["income_statement"]
        revenue_row = _get_row(income_statement, ["Total Revenue", "Operating Revenue"])
        if revenue_row is None:
            return None
        if len(income_statement.columns) < (years * 4):
            return None

        ltm_revenue = revenue_row.iloc[:4].sum()
        nyears_ago_revenue = revenue_row.iloc[(years * 4 - 4):(years * 4)].sum()
        if nyears_ago_revenue <= 0 or ltm_revenue <= 0:
            return None
        cagr = ((ltm_revenue / nyears_ago_revenue) ** (1 / years)) - 1
        return cagr * 100
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def calculate_eps_growth(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculates EPS growth over a specified period."""
    try:
        income_statement = financial_data["income_statement"]
        eps_row = _get_row(income_statement, ["Basic EPS", "Diluted EPS"])
        if eps_row is None:
            return None
        if len(income_statement.columns) < (years * 4):
            return None

        ltm_eps = eps_row.iloc[:4].sum()
        nyears_ago_eps = eps_row.iloc[(years * 4 - 4):(years * 4)].sum()
        return _safe_growth(ltm_eps, nyears_ago_eps)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def calculate_fcf_growth(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculates Free Cash Flow growth over a specified period using quarterly cash flow data."""
    try:
        cash_flow = financial_data["cash_flow"]
        fcf_row = _get_row(cash_flow, ["Free Cash Flow"])
        if fcf_row is None:
            ocf_row = _get_row(cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex_row = _get_row(cash_flow, ["Capital Expenditure", "Capital Expenditures"])
            if ocf_row is None or capex_row is None:
                return None
            fcf_row = ocf_row + capex_row
        if len(cash_flow.columns) < (years * 4):
            return None

        ltm_fcf = fcf_row.iloc[:4].sum()
        nyears_ago_fcf = fcf_row.iloc[(years * 4 - 4):(years * 4)].sum()
        return _safe_growth(ltm_fcf, nyears_ago_fcf)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def calculate_qoq_revenue_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates quarter-over-quarter revenue growth."""
    try:
        income_statement = financial_data["income_statement"]
        revenue_row = _get_row(income_statement, ["Total Revenue", "Operating Revenue"])
        if revenue_row is None or len(revenue_row) < 2:
            return None
        return _safe_growth(revenue_row.iloc[0], revenue_row.iloc[1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def calculate_qoq_eps_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates quarter-over-quarter EPS growth."""
    try:
        income_statement = financial_data["income_statement"]
        eps_row = _get_row(income_statement, ["Basic EPS", "Diluted EPS"])
        if eps_row is None or len(eps_row) < 2:
            return None
        return _safe_growth(eps_row.iloc[0], eps_row.iloc[1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def calculate_qoq_fcf_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates quarter-over-quarter Free Cash Flow growth."""
    try:
        cash_flow = financial_data["cash_flow"]
        fcf_row = _get_row(cash_flow, ["Free Cash Flow"])
        if fcf_row is None:
            ocf_row = _get_row(cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex_row = _get_row(cash_flow, ["Capital Expenditure", "Capital Expenditures"])
            if ocf_row is None or capex_row is None:
                return None
            fcf_row = ocf_row + capex_row
        if len(fcf_row) < 2:
            return None
        return _safe_growth(fcf_row.iloc[0], fcf_row.iloc[1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
