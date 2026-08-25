import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import yfinance as yf

from app.utils.symbol_mapper import map_symbol_for_yfinance

logger = logging.getLogger(__name__)

StatementLoader = Callable[[], Any]

_PROFILE_QUALITY_FIELDS = (
    "returnOnEquity",
    "returnOnAssets",
    "debtToEquity",
    "profitMargins",
    "freeCashflow",
)
_PROFILE_GROWTH_FIELDS = (
    "revenueGrowth",
    "earningsGrowth",
)
_PROFILE_VALUATION_FIELDS = (
    "trailingPE",
    "forwardPE",
    "pegRatio",
    "priceToBook",
)
_MIN_PROFILE_QUALITY_FIELDS = 2
_MIN_PROFILE_TOTAL_FIELDS = 4


def _is_empty(statement) -> bool:
    try:
        return statement is None or statement.empty
    except Exception:
        return True


def _safe_number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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


def _get_info(stock, diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    """Fetch profile fundamentals once, without treating a missing API as failure."""

    try:
        getter = getattr(stock, "get_info", None)
    except AttributeError:
        getter = None
    except Exception as exc:
        diagnostics.append({"stage": "stock_info", "error": str(exc)[:300]})
        return {}

    try:
        if callable(getter):
            value = getter() or {}
        else:
            value = getattr(stock, "info", None) or {}
    except AttributeError:
        return {}
    except Exception as exc:
        diagnostics.append({"stage": "stock_info", "error": str(exc)[:300]})
        logger.debug("stock.info failed: %s", exc)
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _profile_evidence(info: Dict[str, Any]) -> Dict[str, Any]:
    quality = [field for field in _PROFILE_QUALITY_FIELDS if _safe_number(info.get(field)) is not None]
    growth = [field for field in _PROFILE_GROWTH_FIELDS if _safe_number(info.get(field)) is not None]
    valuation = [field for field in _PROFILE_VALUATION_FIELDS if _safe_number(info.get(field)) is not None]
    available = list(dict.fromkeys([*quality, *growth, *valuation]))
    usable = (
        len(quality) >= _MIN_PROFILE_QUALITY_FIELDS
        and len(available) >= _MIN_PROFILE_TOTAL_FIELDS
        and bool(valuation)
    )
    return {
        "usable": usable,
        "available_fields": available,
        "quality_fields": quality,
        "growth_fields": growth,
        "valuation_fields": valuation,
        "available_count": len(available),
        "minimum_quality_fields": _MIN_PROFILE_QUALITY_FIELDS,
        "minimum_total_fields": _MIN_PROFILE_TOTAL_FIELDS,
        "requires_valuation_field": True,
    }


def get_financials_with_diagnostics(
    symbol: str,
    exchange: str = "SET",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Fetch statements and preserve real profile evidence as a partial fallback.

    Missing statement frames are no longer an automatic analysis failure when the
    same yfinance company profile contains enough finite quality and valuation
    fields. The fallback is explicitly labelled ``profile_fallback`` and all
    statement coverage flags remain false, so downstream quality gates can remain
    strict and no financial statement is fabricated.
    """

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

    info = _get_info(stock, provider_errors)
    profile_evidence = _profile_evidence(info)
    statement_evidence_available = has_annual or has_quarterly

    if not statement_evidence_available and not profile_evidence["usable"]:
        status = "provider_error" if provider_errors else "no_statements"
        logger.warning(
            "No usable financial statement/profile evidence found for %s (%s): %s",
            symbol,
            yf_symbol,
            status,
        )
        return None, {
            "status": status,
            "yf_symbol": yf_symbol,
            "provider_errors": provider_errors,
            "profile_evidence": profile_evidence,
        }

    evidence_mode = "financial_statements" if statement_evidence_available else "profile_fallback"
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
        "financial_evidence_mode": evidence_mode,
        "financial_provider_diagnostics": {
            "status": evidence_mode,
            "provider_error_count": len(provider_errors),
            "provider_errors": provider_errors[:5],
            "profile_evidence": profile_evidence,
            "statement_evidence_available": statement_evidence_available,
        },
    }
    return data, {
        "status": evidence_mode,
        "yf_symbol": yf_symbol,
        "provider_errors": provider_errors,
        "profile_evidence": profile_evidence,
        "statement_evidence_available": statement_evidence_available,
    }


def get_financials(symbol: str, exchange: str = "SET") -> Optional[Dict[str, Any]]:
    """Backward-compatible wrapper returning only financial data."""

    data, _ = get_financials_with_diagnostics(symbol, exchange)
    return data
