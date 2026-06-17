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


def get_financials(symbol: str, exchange: str = "SET") -> Optional[Dict[str, Any]]:
    """
    Fetch financial statements for a given stock symbol using yfinance.

    The scanner needs two different timeframes:
    - annual statements for 3Y revenue/EPS/FCF growth
    - quarterly statements for QoQ momentum

    Backward-compatible keys are kept:
    - income_statement, balance_sheet, cash_flow now point to annual data
    - quarterly_income_statement, quarterly_balance_sheet, quarterly_cash_flow are explicit
    """
    try:
        yf_symbol = map_symbol_for_yfinance(symbol, exchange)
        stock = yf.Ticker(yf_symbol)

        annual_income_statement = stock.income_stmt
        annual_balance_sheet = stock.balance_sheet
        annual_cash_flow = stock.cashflow

        quarterly_income_statement = stock.quarterly_income_stmt
        quarterly_balance_sheet = stock.quarterly_balance_sheet
        quarterly_cash_flow = stock.quarterly_cashflow

        has_annual = not (
            _is_empty(annual_income_statement)
            or _is_empty(annual_balance_sheet)
            or _is_empty(annual_cash_flow)
        )
        has_quarterly = not (
            _is_empty(quarterly_income_statement)
            or _is_empty(quarterly_balance_sheet)
            or _is_empty(quarterly_cash_flow)
        )

        if not has_annual and not has_quarterly:
            logger.warning(f"No annual or quarterly financial statements found for {symbol} ({yf_symbol})")
            return None

        return {
            # Backward compatibility: analyzers that read these keys now get annual data first.
            "income_statement": annual_income_statement if has_annual else quarterly_income_statement,
            "balance_sheet": annual_balance_sheet if has_annual else quarterly_balance_sheet,
            "cash_flow": annual_cash_flow if has_annual else quarterly_cash_flow,
            # Explicit annual statements for 3Y growth.
            "annual_income_statement": annual_income_statement,
            "annual_balance_sheet": annual_balance_sheet,
            "annual_cash_flow": annual_cash_flow,
            # Explicit quarterly statements for QoQ growth.
            "quarterly_income_statement": quarterly_income_statement,
            "quarterly_balance_sheet": quarterly_balance_sheet,
            "quarterly_cash_flow": quarterly_cash_flow,
            "has_annual_financials": has_annual,
            "has_quarterly_financials": has_quarterly,
            "yf_symbol": yf_symbol,
            "info": stock.info,
        }
    except Exception as e:
        logger.error(f"Error fetching financial data for {symbol}: {e}")
        return None
