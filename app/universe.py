from __future__ import annotations

from collections import defaultdict, deque
from functools import lru_cache
import re
from typing import Any, Dict, Iterable, List

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

_NON_COMMON_SECURITY_PATTERNS = (
    re.compile(r"\bwarrants?\b", re.IGNORECASE),
    re.compile(r"\brights?\b", re.IGNORECASE),
    re.compile(r"\bunits?\s*$", re.IGNORECASE),
    re.compile(r"\bpreferred\b", re.IGNORECASE),
    re.compile(r"\bpreference shares?\b", re.IGNORECASE),
    re.compile(r"\bnotes?\s+due\b", re.IGNORECASE),
    re.compile(r"\bbonds?\b", re.IGNORECASE),
    re.compile(r"\bdebentures?\b", re.IGNORECASE),
)

_SOURCE_STATUS: Dict[str, Dict[str, Any]] = {}


def _record_source_status(
    name: str,
    *,
    source: str,
    fallback_used: bool,
    effective_count: int,
    error: str | None = None,
) -> None:
    _SOURCE_STATUS[name] = {
        "source": source,
        "fallback_used": fallback_used,
        "effective_count": int(effective_count),
        "error": error,
    }


def get_universe_source_status() -> Dict[str, Dict[str, Any]]:
    """Return source provenance for the cached universe loaders."""

    return {name: dict(row) for name, row in _SOURCE_STATUS.items()}


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
    """Round-robin symbols by first character while preserving group order."""

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


def _is_common_equity_security_name(value: object) -> bool:
    """Reject explicit derivative/debt classes without guessing from ticker suffix."""

    name = str(value or "").strip()
    if not name:
        return True
    return not any(pattern.search(name) for pattern in _NON_COMMON_SECURITY_PATTERNS)


def _filter_listed_equities(table: pd.DataFrame, symbol_column: str) -> List[str]:
    data = table.copy()

    if "Test Issue" in data.columns:
        data = data[data["Test Issue"].fillna("N") != "Y"]
    if "ETF" in data.columns:
        data = data[data["ETF"].fillna("N") != "Y"]
    if "NextShares" in data.columns:
        data = data[data["NextShares"].fillna("N") != "Y"]
    if "Financial Status" in data.columns:
        data = data[data["Financial Status"].fillna("N") != "D"]
    if "Market Category" in data.columns:
        data = data[data["Market Category"].notna()]
    if "Security Name" in data.columns:
        data = data[data["Security Name"].map(_is_common_equity_security_name)]
    if "Symbol" in data.columns:
        data = data[
            ~data["Symbol"].astype(str).str.startswith("File Creation Time", na=False)
        ]

    return normalize_symbols(data[symbol_column].dropna().tolist())


@lru_cache(maxsize=1)
def load_nasdaq_listed_symbols() -> List[str]:
    try:
        table = _read_nasdaq_trader_file("nasdaqlisted.txt")
        symbols = _filter_listed_equities(table, "Symbol")
        _record_source_status(
            "nasdaq_listed",
            source="nasdaq_trader",
            fallback_used=False,
            effective_count=len(symbols),
        )
        return symbols
    except Exception as exc:
        _record_source_status(
            "nasdaq_listed",
            source="unavailable",
            fallback_used=False,
            effective_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )
        return []


@lru_cache(maxsize=1)
def load_other_listed_symbols() -> List[str]:
    try:
        table = _read_nasdaq_trader_file("otherlisted.txt")
        if "ACT Symbol" in table.columns:
            symbols = _filter_listed_equities(table, "ACT Symbol")
            _record_source_status(
                "other_listed",
                source="nasdaq_trader",
                fallback_used=False,
                effective_count=len(symbols),
            )
            return symbols
    except Exception as exc:
        _record_source_status(
            "other_listed",
            source="unavailable",
            fallback_used=False,
            effective_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )
        return []
    _record_source_status(
        "other_listed",
        source="unavailable",
        fallback_used=False,
        effective_count=0,
    )
    return []


@lru_cache(maxsize=1)
def load_sp500_symbols() -> List[str]:
    live_error: str | None = None
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        symbols = normalize_symbols(tables[0]["Symbol"].tolist())
        if len(symbols) >= 400:
            _record_source_status(
                "sp500",
                source="wikipedia_live",
                fallback_used=False,
                effective_count=len(symbols),
            )
            return symbols
        live_error = f"partial benchmark membership: {len(symbols)} symbols"
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"

    fallback = list(US_LARGE_CAP_FALLBACK)
    _record_source_status(
        "sp500",
        source="static_large_cap_priority_fallback",
        fallback_used=True,
        effective_count=len(fallback),
        error=live_error,
    )
    return fallback


@lru_cache(maxsize=1)
def load_nasdaq100_symbols() -> List[str]:
    live_error: str | None = None
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for table in tables:
            for column in table.columns:
                column_name = str(column).lower()
                if "ticker" in column_name or "symbol" in column_name:
                    symbols = normalize_symbols(
                        table[column].dropna().astype(str).tolist()
                    )
                    if len(symbols) >= 80:
                        _record_source_status(
                            "nasdaq100",
                            source="wikipedia_live",
                            fallback_used=False,
                            effective_count=len(symbols),
                        )
                        return symbols
        live_error = "no Nasdaq-100 table with at least 80 symbols"
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"

    fallback = list(US_GROWTH_UNIVERSE)
    _record_source_status(
        "nasdaq100",
        source="static_growth_priority_fallback",
        fallback_used=True,
        effective_count=len(fallback),
        error=live_error,
    )
    return fallback


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
