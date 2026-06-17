import yfinance as yf
from typing import Optional, Dict, Any
import logging
from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)


def _is_empty(statement) -> bool:
    try:
        return statement is None or statement.empty
    except Exception:
        return True


def _first_non_empty(*statements):
    for statement in statements:
        if not _is_empty(statement):
            return statement
    return None


def _call_optional(stock, method_name: str, **kwargs):
    try:
        method = getattr(stock, method_name, None)
        if callable(method):
            return method(**kwargs)
    except Exception as exc:
        logger.debug(f"Optional yfinance call {method_name} failed: {exc}")
    return None


def _get_annual_income_statement(stock):
    return _first_non_empty(
        getattr(stock, "income_stmt", None),
        getattr(stock, "financials", None),
        _call_optional(stock, "get_income_stmt", freq="yearly"),
        _call_optional(stock, "get_financials", freq="yearly"),
        _call_optional(stock, "get_income_stmt"),
        _call_optional(stock, "get_financials"),
    )


def _get_annual_balance_sheet(stock):
    return _first_non_empty(
        getattr(stock, "balance_sheet", None),
        getattr(stock, "balancesheet", None),
        _call_optional(stock, "get_balance_sheet", freq="yearly"),
        _call_optional(stock, "get_balancesheet", freq="yearly"),
        _call_optional(stock, "get_balance_sheet"),
        _call_optional(stock, "get_balancesheet"),
    )


def _get_annual_cash_flow(stock):
    return _first_non_empty(
        getattr(stock, "cashflow", None),
        getattr(stock, "cash_flow", None),
        _call_optional(stock, "get_cashflow", freq="yearly"),
        _call_optional(stock, "get_cash_flow", freq="yearly"),
        _call_optional(stock, "get_cashflow"),
        _call_optional(stock, "get_cash_flow"),
    )


def _get_quarterly_income_statement(stock):
    return _first_non_empty(
        getattr(stock, "quarterly_income_stmt", None),
        getattr(stock, "quarterly_financials", None),
        _call_optional(stock, "get_income_stmt", freq="quarterly"),
        _call_optional(stock, "get_financials", freq="quarterly"),
    )


def _get_quarterly_balance_sheet(stock):
    return _first_non_empty(
        getattr(stock, "quarterly_balance_sheet", None),
        getattr(stock, "quarterly_balancesheet", None),
        _call_optional(stock, "get_balance_sheet", freq="quarterly"),
        _call_optional(stock, "get_balancesheet", freq="quarterly"),
    )


def _get_quarterly_cash_flow(stock):
    return _first_non_empty(
        getattr(stock, "quarterly_cashflow", None),
        getattr(stock, "quarterly_cash_flow", None),
        _call_optional(stock, "get_cashflow", freq="quarterly"),
        _call_optional(stock, "get_cash_flow", freq="quarterly"),
    )


def get_financials(symbol: str, exchange: str = "SET") -> Optional[Dict[str, Any]]:
    """
    Fetch financial statements for a given stock symbol using yfinance.

    The scanner needs two different timeframes:
    - annual statements for 3Y revenue/EPS/FCF growth
    - quarterly statements for QoQ momentum

    Fallbacks are intentionally broad because yfinance may expose annual data
    through different attributes depending on ticker/provider response.
    """
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

        # Growth readiness should not fail just because balance sheet is missing.
        has_annual = has_annual_income or has_annual_cash_flow
        has_quarterly = has_quarterly_income or has_quarterly_cash_flow

        if not has_annual and not has_quarterly:
            logger.warning(f"No annual or quarterly financial statements found for {symbol} ({yf_symbol})")
            return None

        try:
            info = stock.info
        except Exception as exc:
            logger.debug(f"stock.info failed for {symbol} ({yf_symbol}): {exc}")
            info = {}

        return {
            # Backward compatibility: analyzers that read these keys now get annual data first.
            "income_statement": annual_income_statement if has_annual_income else quarterly_income_statement,
            "balance_sheet": annual_balance_sheet if has_annual_balance else quarterly_balance_sheet,
            "cash_flow": annual_cash_flow if has_annual_cash_flow else quarterly_cash_flow,
            # Explicit annual statements for 3Y growth.
            "annual_income_statement": annual_income_statement,
            "annual_balance_sheet": annual_balance_sheet,
            "annual_cash_flow": annual_cash_flow,
            # Explicit quarterly statements for QoQ growth.
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
        }
    except Exception as e:
        logger.error(f"Error fetching financial data for {symbol}: {e}")
        return None
