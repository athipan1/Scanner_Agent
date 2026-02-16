def map_symbol_for_yfinance(symbol: str, exchange: str) -> str:
    """
    Maps a stock symbol to a format compatible with yfinance based on the exchange.

    Args:
        symbol (str): The stock symbol.
        exchange (str): The stock exchange (e.g., 'SET', 'NASDAQ').

    Returns:
        str: The mapped symbol (e.g., 'PTT.BK' for SET exchange).
    """
    if exchange.upper() == "SET":
        if not symbol.endswith(".BK"):
            return f"{symbol}.BK"
    return symbol
