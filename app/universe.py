from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List

import pandas as pd

US_GROWTH_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "AMD", "NFLX", "CRM", "ADBE", "ORCL", "NOW", "INTC",
    "QCOM", "TXN", "AMAT", "MU", "PANW", "CRWD", "SNOW", "SHOP",
    "UBER", "ABNB", "PYPL", "SQ", "COIN", "PLTR", "SMCI", "ARM",
    "JPM", "BAC", "V", "MA", "UNH", "LLY", "JNJ", "XOM", "COST", "WMT",
]

THAI_BLUE_CHIP_UNIVERSE = [
    "PTT", "AOT", "DELTA", "CPALL", "BBL", "SCB", "KBANK", "GULF",
    "ADVANC", "SCC", "BDMS", "PTTEP", "EA", "CPN", "TRUE", "HMPRO",
    "INTUCH", "MINT", "CRC", "OR",
]

# Fallback list keeps GitHub Actions stable if Wikipedia/Nasdaq pages are unavailable.
US_LARGE_CAP_FALLBACK = sorted(set(US_GROWTH_UNIVERSE + [
    "ABBV", "ABT", "ACN", "ADP", "AEP", "AFL", "AIG", "AJG", "ALL", "AMGN",
    "ANET", "APD", "APH", "AXP", "BA", "BK", "BKNG", "BLK", "BMY", "BSX",
    "CAT", "CB", "CCI", "CHTR", "CI", "CL", "CMCSA", "CME", "CMG", "COP",
    "CSCO", "CVS", "CVX", "DE", "DHR", "DIS", "DUK", "ELV", "EMR", "ETN",
    "FI", "GE", "GILD", "GM", "GS", "HD", "HON", "IBM", "ICE", "ISRG",
    "KO", "LIN", "LMT", "LOW", "MAR", "MCD", "MDT", "MMC", "MO", "MRK",
    "MS", "NEE", "NKE", "PEP", "PFE", "PG", "PM", "RTX", "SBUX", "SCHW",
    "SO", "SPG", "T", "TMO", "TMUS", "UNP", "UPS", "VRTX", "WFC", "ZTS",
]))


def normalize_symbols(symbols: Iterable[str] | None) -> List[str]:
    normalized = []
    seen = set()
    for symbol in symbols or []:
        clean_symbol = str(symbol).upper().strip().replace(".", "-")
        if clean_symbol and clean_symbol not in seen:
            normalized.append(clean_symbol)
            seen.add(clean_symbol)
    return normalized


@lru_cache(maxsize=1)
def load_sp500_symbols() -> List[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        symbols = tables[0]["Symbol"].tolist()
        return normalize_symbols(symbols)
    except Exception:
        return []


@lru_cache(maxsize=1)
def load_nasdaq100_symbols() -> List[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for table in tables:
            for column in table.columns:
                column_name = str(column).lower()
                if "ticker" in column_name or "symbol" in column_name:
                    symbols = table[column].dropna().astype(str).tolist()
                    cleaned = normalize_symbols(symbols)
                    if len(cleaned) >= 80:
                        return cleaned
    except Exception:
        return []
    return []


@lru_cache(maxsize=1)
def load_us_phase1_universe() -> List[str]:
    symbols = normalize_symbols(load_sp500_symbols() + load_nasdaq100_symbols())
    if len(symbols) >= 300:
        return symbols
    return list(US_LARGE_CAP_FALLBACK)


def resolve_universe(symbols: Iterable[str] | None, screener: str = "america", exchange: str = "NASDAQ") -> List[str]:
    explicit_symbols = normalize_symbols(symbols)
    if explicit_symbols:
        return explicit_symbols

    if screener.lower() in {"thailand", "thai", "set"} or exchange.upper() == "SET":
        return list(THAI_BLUE_CHIP_UNIVERSE)

    return load_us_phase1_universe()
