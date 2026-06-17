from typing import Optional, Dict, Any
import pandas as pd


def _get_row(df: pd.DataFrame, row_names: list[str]):
    try:
        if df is None or df.empty:
            return None
    except Exception:
        return None
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


def _annual_income_statement(financial_data: Dict[str, Any]) -> pd.DataFrame:
    return financial_data.get("annual_income_statement") or financial_data.get("income_statement")


def _annual_cash_flow(financial_data: Dict[str, Any]) -> pd.DataFrame:
    return financial_data.get("annual_cash_flow") or financial_data.get("cash_flow")


def _quarterly_income_statement(financial_data: Dict[str, Any]) -> pd.DataFrame:
    return financial_data.get("quarterly_income_statement") or financial_data.get("income_statement")


def _quarterly_cash_flow(financial_data: Dict[str, Any]) -> pd.DataFrame:
    return financial_data.get("quarterly_cash_flow") or financial_data.get("cash_flow")


def _calculate_cagr_from_annual_row(row, years: int = 3) -> Optional[float]:
    try:
        clean = row.dropna()
        if len(clean) < 2:
            return None
        latest = float(clean.iloc[0])
        oldest_index = min(len(clean) - 1, years)
        oldest = float(clean.iloc[oldest_index])
        periods = max(1, oldest_index)
        if oldest <= 0 or latest <= 0:
            return None
        return (((latest / oldest) ** (1 / periods)) - 1) * 100
    except Exception:
        return None


def calculate_revenue_cagr(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculate annual revenue CAGR over up to 3 fiscal years, returned as percent."""
    try:
        income_statement = _annual_income_statement(financial_data)
        revenue_row = _get_row(income_statement, ["Total Revenue", "Operating Revenue"])
        if revenue_row is None:
            return None
        return _calculate_cagr_from_annual_row(revenue_row, years=years)
    except Exception:
        return None


def calculate_eps_growth(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculate annual EPS growth over up to 3 fiscal years, returned as percent."""
    try:
        income_statement = _annual_income_statement(financial_data)
        eps_row = _get_row(income_statement, ["Basic EPS", "Diluted EPS"])
        if eps_row is None:
            return None
        clean = eps_row.dropna()
        if len(clean) < 2:
            return None
        latest = float(clean.iloc[0])
        oldest_index = min(len(clean) - 1, years)
        previous = float(clean.iloc[oldest_index])
        return _safe_growth(latest, previous)
    except Exception:
        return None


def calculate_fcf_growth(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculate annual free-cash-flow growth over up to 3 fiscal years, returned as percent."""
    try:
        cash_flow = _annual_cash_flow(financial_data)
        fcf_row = _get_row(cash_flow, ["Free Cash Flow"])
        if fcf_row is None:
            ocf_row = _get_row(cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex_row = _get_row(cash_flow, ["Capital Expenditure", "Capital Expenditures"])
            if ocf_row is None or capex_row is None:
                return None
            fcf_row = ocf_row + capex_row
        clean = fcf_row.dropna()
        if len(clean) < 2:
            return None
        latest = float(clean.iloc[0])
        oldest_index = min(len(clean) - 1, years)
        previous = float(clean.iloc[oldest_index])
        return _safe_growth(latest, previous)
    except Exception:
        return None


def calculate_qoq_revenue_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate latest quarter revenue growth versus previous quarter, returned as percent."""
    try:
        income_statement = _quarterly_income_statement(financial_data)
        revenue_row = _get_row(income_statement, ["Total Revenue", "Operating Revenue"])
        if revenue_row is None or len(revenue_row.dropna()) < 2:
            return None
        clean = revenue_row.dropna()
        return _safe_growth(clean.iloc[0], clean.iloc[1])
    except Exception:
        return None


def calculate_qoq_eps_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate latest quarter EPS growth versus previous quarter, returned as percent."""
    try:
        income_statement = _quarterly_income_statement(financial_data)
        eps_row = _get_row(income_statement, ["Basic EPS", "Diluted EPS"])
        if eps_row is None or len(eps_row.dropna()) < 2:
            return None
        clean = eps_row.dropna()
        return _safe_growth(clean.iloc[0], clean.iloc[1])
    except Exception:
        return None


def calculate_qoq_fcf_growth(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculate latest quarter FCF growth versus previous quarter, returned as percent."""
    try:
        cash_flow = _quarterly_cash_flow(financial_data)
        fcf_row = _get_row(cash_flow, ["Free Cash Flow"])
        if fcf_row is None:
            ocf_row = _get_row(cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex_row = _get_row(cash_flow, ["Capital Expenditure", "Capital Expenditures"])
            if ocf_row is None or capex_row is None:
                return None
            fcf_row = ocf_row + capex_row
        clean = fcf_row.dropna()
        if len(clean) < 2:
            return None
        return _safe_growth(clean.iloc[0], clean.iloc[1])
    except Exception:
        return None
