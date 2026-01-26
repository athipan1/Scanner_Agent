import yfinance as yf
from typing import Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetches current market data for a given stock symbol using yfinance.

    Args:
        symbol (str): The stock symbol (e.g., "AAPL").

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing key market data
                                     (e.g., price, market cap), or None
                                     if the data cannot be fetched.
    """
    try:
        stock = yf.Ticker(symbol)
        info = stock.info

        # yfinance's .info dictionary contains a wealth of market data.
        # We can extract the most relevant fields here.
        required_keys = ["currentPrice", "marketCap", "industry", "sector", "pegRatio", "trailingPE", "forwardPE", "priceToBook"]

        market_data = {key: info.get(key) for key in required_keys}

        # Ensure essential data is present
        if not all(market_data.values()):
            return None

        return market_data

    except Exception as e:
        logger.error(f"Error fetching market data for {symbol}: {e}")
        return None
