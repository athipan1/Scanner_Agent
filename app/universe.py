from __future__ import annotations

from collections import defaultdict, deque
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

# Fallback list keeps GitHub Actions stable if public market-listing endpoints are unavailable.
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

NASDAQ_TRADER_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"


def normalize_symbols(symbols: Iterable[str] | None) -> List[str]:
    normalized = []
    seen = set()
    for symbol in symbols or []:
        clean_symbol = str(symbol).upper().strip()
        clean_symbol = clean_symbol.replace(".", "-")
        clean_symbol = clean_symbol.replace(" ", "")
        if not clean_symbol or clean_symbol in seen:
            continue
        if clean_symbol in {"SYMBOL", "NAN", "FILECREATIONTIME"}:
            continue
        if len(clean_symbol) > 8:
            continue
        normalized.append(clean_symbol)
        seen.add(clean_symbol)
    return normalized


def diversify_symbols_by_initial(symbols: Iterable[str] | None) -> List[str]:
    """Round-robin symbols by first character while preserving per-group order.

    NASDAQ Trader files are alphabetical. Truncating the first 1,000 rows therefore
    over-samples symbols beginning with A and B. This deterministic round-robin
    ordering spreads a bounded discovery run across the whole alphabet without
    randomizing results between workflow runs.
    """

    groups = defaultdict(deque)
    for symbol in normalize_symbols(symbols):
        initial = symbol[0] if symbol else "#"
        groups[initial].append(symbol)

    ordered: List[str] = []
    initials = sorted(groups)
    while initials:
        remaining = []
        for initial in initials:
            group = groups[initial]
            if group:
                ordered.append(group.popleft())
            if group:
                remaining.append(initial)
        initials = remaining
    return ordered


def _read_nasdaq_trader_file(file_name: str) -> pd.DataFrame:
    url = f"{NASDAQ_TRADER_BASE_URL}/{file_name}"
    return pd.read_csv(url, sep="|", dtype=str)


def _filter_listed_equities(table: pd.DataFrame, symbol_column: str) -> List[str]:
    data = table.copy()

    if "Test Issue" in data.columns:
        data = data[data["Test Issue"].fillna("N") != "Y"]
    if "ETF" in data.columns:
        data = data[data["ETF"].fillna("N") != "Y"]
    if "Financial Status" in data.columns:
        data = data[data["Financial Status"].fillna("N") != "D"]
    if "Market Category" in data.columns:
        data = data[data["Market Category"].notna()]
    if "Symbol" in data.columns:
        data = data[
            ~data["Symbol"].astype(str).str.startswith("File Creation Time", na=False)
        ]

    return normalize_symbols(data[symbol_column].dropna().tolist())


@lru_cache(maxsize=1)
def load_nasdaq_listed_symbols() -> List[str]:
    try:
        table = _read_nasdaq_trader_file("nasdaqlisted.txt")
        return _filter_listed_equities(table, "Symbol")
    except Exception:
        return []


@lru_cache(maxsize=1)
def load_other_listed_symbols() -> List[str]:
    try:
        table = _read_nasdaq_trader_file("otherlisted.txt")
        if "ACT Symbol" in table.columns:
            return _filter_listed_equities(table, "ACT Symbol")
        return []
    except Exception:
        return []


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
def load_us_listed_universe() -> List[str]:
    listed_symbols = normalize_symbols(
        load_nasdaq_listed_symbols() + load_other_listed_symbols()
    )
    if len(listed_symbols) >= 1_000:
        return listed_symbols
    return []


@lru_cache(maxsize=1)
def load_us_phase1_universe() -> List[str]:
    symbols = normalize_symbols(load_us_listed_universe())
    if len(symbols) >= 1_000:
        return diversify_symbols_by_initial(symbols)

    symbols = normalize_symbols(load_sp500_symbols() + load_nasdaq100_symbols())
    if len(symbols) >= 300:
        return symbols

    return list(US_LARGE_CAP_FALLBACK)


def resolve_universe(
    symbols: Iterable[str] | None,
    screener: str = "america",
    exchange: str = "NASDAQ",
) -> List[str]:
    explicit_symbols = normalize_symbols(symbols)
    if explicit_symbols:
        return explicit_symbols

    if screener.lower() in {"thailand", "thai", "set"} or exchange.upper() == "SET":
        return list(THAI_BLUE_CHIP_UNIVERSE)

    return load_us_phase1_universe()
