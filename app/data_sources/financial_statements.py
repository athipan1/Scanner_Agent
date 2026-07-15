import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import yfinance as yf

from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)

StatementLoader = Callable[[], Any]


def _is_empty(statement) -> bool:
    try:
        return statement is None or statement.empty
    except Exception:
        return True


def _first_non_empty_lazy(
    *loaders: StatementLoader,
    diagnostics: Optional[List[Dict[str, str]]] = None,
    stage: str = "statement",
):
    """Run provider fallbacks one at a time and record failed provider calls."""

    for loader in loaders:
        try:
            statement = loader()
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.append({"stage": stage, "error": str(exc)[:300]})
            logger.debug("Optional yfinance %s loader failed: %s", stage, exc)
            continue
        if not _is_empty(statement):
            return statement
    return None


def _call_optional(stock, method_name: str, **kwargs):
    method = getattr(stock, method_name, None)
    if callable(method):
        return method(**kwargs)
    return None


def _get_annual_income_statement(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "income_stmt", None),
        lambda: getattr(stock, "financials", None),
        lambda: _call_optional(stock, "get_income_stmt", freq="yearly"),
        lambda: _call_optional(stock, "get_financials", freq="yearly"),
        lambda: _call_optional(stock, "get_income_stmt"),
        lambda: _call_optional(stock, "get_financials"),
        diagnostics=diagnostics,
        stage="annual_income_statement",
    )


def _get_annual_balance_sheet(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "balance_sheet", None),
        lambda: getattr(stock, "balancesheet", None),
        lambda: _call_optional(stock, "get_balance_sheet", freq="yearly"),
        lambda: _call_optional(stock, "get_balancesheet", freq="yearly"),
        lambda: _call_optional(stock, "get_balance_sheet"),
        lambda: _call_optional(stock, "get_balancesheet"),
        diagnostics=diagnostics,
        stage="annual_balance_sheet",
    )


def _get_annual_cash_flow(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "cashflow", None),
        lambda: getattr(stock, "cash_flow", None),
        lambda: _call_optional(stock, "get_cashflow", freq="yearly"),
        lambda: _call_optional(stock, "get_cash_flow", freq="yearly"),
        lambda: _call_optional(stock, "get_cashflow"),
        lambda: _call_optional(stock, "get_cash_flow"),
        diagnostics=diagnostics,
        stage="annual_cash_flow",
    )


def _get_quarterly_income_statement(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_income_stmt", None),
        lambda: getattr(stock, "quarterly_financials", None),
        lambda: _call_optional(stock, "get_income_stmt", freq="quarterly"),
        lambda: _call_optional(stock, "get_financials", freq="quarterly"),
        diagnostics=diagnostics,
        stage="quarterly_income_statement",
    )


def _get_quarterly_balance_sheet(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_balance_sheet", None),
        lambda: getattr(stock, "quarterly_balancesheet", None),
        lambda: _call_optional(stock, "get_balance_sheet", freq="quarterly"),
        lambda: _call_optional(stock, "get_balancesheet", freq="quarterly"),
        diagnostics=diagnostics,
        stage="quarterly_balance_sheet",
    )


def _get_quarterly_cash_flow(stock, diagnostics=None):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_cashflow", None),
        lambda: getattr(stock, "quarterly_cash_flow", None),
        lambda: _call_optional(stock, "get_cashflow", freq="quarterly"),
        lambda: _call_optional(stock, "get_cash_flow", freq="quarterly"),
        diagnostics=diagnostics,
        stage="quarterly_cash_flow",
    )


def get_financials_with_diagnostics(
    symbol: str,
    exchange: str = "SET",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Fetch statements and distinguish missing data from provider failures."""

    provider_errors: List[Dict[str, str]] = []
    yf_symbol = map_symbol_for_yfinance(symbol, exchange)
    try:
        stock = yf.Ticker(yf_symbol)
        annual_income_statement = _get_annual_income_statement(stock, provider_errors)
        annual_balance_sheet = _get_annual_balance_sheet(stock, provider_errors)
        annual_cash_flow = _get_annual_cash_flow(stock, provider_errors)
        quarterly_income_statement = _get_quarterly_income_statement(
            stock,
            provider_errors,
        )
        quarterly_balance_sheet = _get_quarterly_balance_sheet(
            stock,
            provider_errors,
        )
        quarterly_cash_flow = _get_quarterly_cash_flow(stock, provider_errors)
    except Exception as exc:
        provider_errors.append({"stage": "ticker_initialization", "error": str(exc)[:300]})
        return None, {
            "status": "provider_error",
            "yf_symbol": yf_symbol,
            "provider_errors": provider_errors,
        }

    has_annual_income = not _is_empty(annual_income_statement)
    has_annual_cash_flow = not _is_empty(annual_cash_flow)
    has_annual_balance = not _is_empty(annual_balance_sheet)
    has_quarterly_income = not _is_empty(quarterly_income_statement)
    has_quarterly_cash_flow = not _is_empty(quarterly_cash_flow)
    has_quarterly_balance = not _is_empty(quarterly_balance_sheet)
    has_annual = has_annual_income or has_annual_cash_flow
    has_quarterly = has_quarterly_income or has_quarterly_cash_flow

    if not has_annual and not has_quarterly:
        status = "provider_error" if provider_errors else "no_statements"
        logger.warning(
            "No annual or quarterly financial statements found for %s (%s): %s",
            symbol,
            yf_symbol,
            status,
        )
        return None, {
            "status": status,
            "yf_symbol": yf_symbol,
            "provider_errors": provider_errors,
        }

    try:
        info = stock.info or {}
    except Exception as exc:
        provider_errors.append({"stage": "stock_info", "error": str(exc)[:300]})
        logger.debug("stock.info failed for %s (%s): %s", symbol, yf_symbol, exc)
        info = {}

    data = {
        "income_statement": annual_income_statement
        if has_annual_income
        else quarterly_income_statement,
        "balance_sheet": annual_balance_sheet
        if has_annual_balance
        else quarterly_balance_sheet,
        "cash_flow": annual_cash_flow if has_annual_cash_flow else quarterly_cash_flow,
        "annual_income_statement": annual_income_statement,
        "annual_balance_sheet": annual_balance_sheet,
        "annual_cash_flow": annual_cash_flow,
        "quarterly_income_statement": quarterly_income_statement,
        "quarterly_balance_sheet": quarterly_balance_sheet,
        "quarterly_cash_flow": quarterly_cash_flow,
        "has_annual_financials": has_annual,
        "has_annual_income_statement": has_annual_income,
        "has_annual_cash_flow": has_annual_cash_flow,
        "has_annual_balance_sheet": has_annual_balance,
        "has_quarterly_financials": has_quarterly,
        "has_quarterly_income_statement": has_quarterly_income,
        "has_quarterly_cash_flow": has_quarterly_cash_flow,
        "has_quarterly_balance_sheet": has_quarterly_balance,
        "yf_symbol": yf_symbol,
        "info": info,
        "financial_provider_diagnostics": {
            "status": "success",
            "provider_error_count": len(provider_errors),
            "provider_errors": provider_errors[:5],
        },
    }
    return data, {
        "status": "success",
        "yf_symbol": yf_symbol,
        "provider_errors": provider_errors,
    }


def get_financials(symbol: str, exchange: str = "SET") -> Optional[Dict[str, Any]]:
    """Backward-compatible wrapper returning only financial data."""

    data, _ = get_financials_with_diagnostics(symbol, exchange)
    return data
