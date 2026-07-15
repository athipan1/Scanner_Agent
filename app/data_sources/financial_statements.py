import logging
from typing import Any, Callable, Dict, Optional

import yfinance as yf

from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)


StatementLoader = Callable[[], Any]


def _is_empty(statement) -> bool:
    try:
        return statement is None or statement.empty
    except Exception:
        return True


def _first_non_empty_lazy(*loaders: StatementLoader):
    """Run provider fallbacks one at a time and stop after the first success.

    The previous implementation accepted already-evaluated values. Python therefore
    executed every yfinance property and method before `_first_non_empty` could
    choose one, producing a request storm for broad-universe discovery.
    """

    for loader in loaders:
        try:
            statement = loader()
        except Exception as exc:
            logger.debug("Optional yfinance statement loader failed: %s", exc)
            continue
        if not _is_empty(statement):
            return statement
    return None


def _call_optional(stock, method_name: str, **kwargs):
    try:
        method = getattr(stock, method_name, None)
        if callable(method):
            return method(**kwargs)
    except Exception as exc:
        logger.debug("Optional yfinance call %s failed: %s", method_name, exc)
    return None


def _get_annual_income_statement(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "income_stmt", None),
        lambda: getattr(stock, "financials", None),
        lambda: _call_optional(stock, "get_income_stmt", freq="yearly"),
        lambda: _call_optional(stock, "get_financials", freq="yearly"),
        lambda: _call_optional(stock, "get_income_stmt"),
        lambda: _call_optional(stock, "get_financials"),
    )


def _get_annual_balance_sheet(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "balance_sheet", None),
        lambda: getattr(stock, "balancesheet", None),
        lambda: _call_optional(stock, "get_balance_sheet", freq="yearly"),
        lambda: _call_optional(stock, "get_balancesheet", freq="yearly"),
        lambda: _call_optional(stock, "get_balance_sheet"),
        lambda: _call_optional(stock, "get_balancesheet"),
    )


def _get_annual_cash_flow(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "cashflow", None),
        lambda: getattr(stock, "cash_flow", None),
        lambda: _call_optional(stock, "get_cashflow", freq="yearly"),
        lambda: _call_optional(stock, "get_cash_flow", freq="yearly"),
        lambda: _call_optional(stock, "get_cashflow"),
        lambda: _call_optional(stock, "get_cash_flow"),
    )


def _get_quarterly_income_statement(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_income_stmt", None),
        lambda: getattr(stock, "quarterly_financials", None),
        lambda: _call_optional(stock, "get_income_stmt", freq="quarterly"),
        lambda: _call_optional(stock, "get_financials", freq="quarterly"),
    )


def _get_quarterly_balance_sheet(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_balance_sheet", None),
        lambda: getattr(stock, "quarterly_balancesheet", None),
        lambda: _call_optional(stock, "get_balance_sheet", freq="quarterly"),
        lambda: _call_optional(stock, "get_balancesheet", freq="quarterly"),
    )


def _get_quarterly_cash_flow(stock):
    return _first_non_empty_lazy(
        lambda: getattr(stock, "quarterly_cashflow", None),
        lambda: getattr(stock, "quarterly_cash_flow", None),
        lambda: _call_optional(stock, "get_cashflow", freq="quarterly"),
        lambda: _call_optional(stock, "get_cash_flow", freq="quarterly"),
    )


def get_financials(symbol: str, exchange: str = "SET") -> Optional[Dict[str, Any]]:
    """Fetch annual and quarterly statements with provider-friendly fallbacks."""

    try:
        yf_symbol = map_symbol_for_yfinance(symbol, exchange)
        stock = yf.Ticker(yf_symbol)

        annual_income_statement = _get_annual_income_statement(stock)
        annual_balance_sheet = _get_annual_balance_sheet(stock)
        annual_cash_flow = _get_annual_cash_flow(stock)

        quarterly_income_statement = _get_quarterly_income_statement(stock)
        quarterly_balance_sheet = _get_quarterly_balance_sheet(stock)
        quarterly_cash_flow = _get_quarterly_cash_flow(stock)

        has_annual_income = not _is_empty(annual_income_statement)
        has_annual_cash_flow = not _is_empty(annual_cash_flow)
        has_annual_balance = not _is_empty(annual_balance_sheet)
        has_quarterly_income = not _is_empty(quarterly_income_statement)
        has_quarterly_cash_flow = not _is_empty(quarterly_cash_flow)
        has_quarterly_balance = not _is_empty(quarterly_balance_sheet)

        # Growth readiness should not fail just because a balance sheet is absent.
        has_annual = has_annual_income or has_annual_cash_flow
        has_quarterly = has_quarterly_income or has_quarterly_cash_flow

        if not has_annual and not has_quarterly:
            logger.warning(
                "No annual or quarterly financial statements found for %s (%s)",
                symbol,
                yf_symbol,
            )
            return None

        try:
            info = stock.info or {}
        except Exception as exc:
            logger.debug("stock.info failed for %s (%s): %s", symbol, yf_symbol, exc)
            info = {}

        return {
            # Backward compatibility: analyzers read annual data first.
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
            # Reused by market_data so broad discovery does not call stock.info twice.
            "info": info,
        }
    except Exception as exc:
        logger.error("Error fetching financial data for %s: %s", symbol, exc)
        return None
