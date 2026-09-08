"""Carry observed fiscal values to Fundamental without synthetic histories."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.analyzers.growth_analyzer import REVENUE_ROWS, EPS_ROWS, OCF_ROWS, CAPEX_ROWS


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _row(statement: Any, names: list[str]):
    if statement is None or getattr(statement, "empty", True):
        return None
    index = {str(key).strip().lower(): key for key in statement.index}
    for name in names:
        key = index.get(name.lower())
        if key is not None:
            return statement.loc[key]
    return None


def _history(statement: Any, names: list[str]) -> dict[str, float]:
    row = _row(statement, names)
    if row is None:
        return {}
    values = {}
    for date, value in row.items():
        number = _number(value)
        if number is not None:
            key = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            values[key] = number
    return dict(sorted(values.items())[-4:])


def _cash_histories(statement: Any, prefix: str) -> dict:
    fcf = _history(statement, ["Free Cash Flow"])
    ocf = _history(statement, OCF_ROWS)
    if not fcf:
        capex = _history(statement, CAPEX_ROWS)
        # Yahoo statement capex is signed. Never substitute FCF for OCF.
        fcf = {date: value + capex[date] for date, value in ocf.items() if date in capex}
    return {prefix + "Free Cash Flow": fcf, prefix + "Operating Cash Flow": ocf}


def build_financial_evidence_payload(symbol: str, financials: dict) -> dict:
    info = financials.get("info") or {}
    mapping = {
        "ROE": "returnOnEquity",
        "ROA": "returnOnAssets",
        "ROIC": "returnOnInvestedCapital",
        "Profit Margins": "profitMargins",
        "Operating Margin": "operatingMargins",
        "Gross Margin": "grossMargins",
        "P/E Ratio": "trailingPE",
        "Forward P/E": "forwardPE",
        "PEG Ratio": "pegRatio",
        "P/B Ratio": "priceToBook",
        "EPS": "trailingEps",
        "Operating Cash Flow": "operatingCashflow",
        "Free Cash Flow": "freeCashflow",
        "Net Income": "netIncomeToCommon",
        "Total Revenue": "totalRevenue",
        "EBITDA": "ebitda",
        "Enterprise Value": "enterpriseValue",
        "Market Cap": "marketCap",
        "Dividend Yield": "dividendYield",
        "Dividend Rate": "dividendRate",
        "Payout Ratio": "payoutRatio",
    }
    values = {name: _number(info.get(key)) for name, key in mapping.items()}
    debt = _number(info.get("debtToEquity"))
    values["Debt to Equity Ratio"] = debt / 100.0 if debt is not None else None
    values["Debt to Equity Unit"] = "ratio"
    values["Sector"] = info.get("sector")
    values["Currency"] = info.get("financialCurrency") or info.get("currency")
    for scope, prefix in (("annual", "Historical "), ("quarterly", "Quarterly ")):
        income = financials.get(scope + "_income_statement")
        values[prefix + "Revenue"] = _history(income, REVENUE_ROWS)
        values[prefix + "EPS"] = _history(income, EPS_ROWS)
        values[prefix + "Net Income"] = _history(income, ["Net Income"])
        values.update(_cash_histories(financials.get(scope + "_cash_flow"), prefix))
    for current, history in (
        ("Total Revenue", "Historical Revenue"),
        ("Net Income", "Historical Net Income"),
        ("Operating Cash Flow", "Historical Operating Cash Flow"),
        ("Free Cash Flow", "Historical Free Cash Flow"),
    ):
        if values.get(current) is None and values.get(history):
            values[current] = values[history][max(values[history])]
    return {
        "schema_version": "scanner-financial-inputs.v1",
        "symbol": symbol.upper(),
        "source": "yfinance_financial_statements",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "synthetic": False,
        "ratio_unit": "decimal",
        "values": values,
    }
