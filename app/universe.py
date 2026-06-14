from __future__ import annotations

from typing import Iterable, List

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


def normalize_symbols(symbols: Iterable[str] | None) -> List[str]:
    return [str(symbol).upper().strip() for symbol in (symbols or []) if str(symbol).strip()]


def resolve_universe(symbols: Iterable[str] | None, screener: str = "america", exchange: str = "NASDAQ") -> List[str]:
    explicit_symbols = normalize_symbols(symbols)
    if explicit_symbols:
        return explicit_symbols

    if screener.lower() in {"thailand", "thai", "set"} or exchange.upper() == "SET":
        return list(THAI_BLUE_CHIP_UNIVERSE)

    return list(US_GROWTH_UNIVERSE)
