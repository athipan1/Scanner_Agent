from __future__ import annotations

from typing import Any, Hashable, Optional

import pandas as pd


def _empty_series(field: str) -> pd.Series:
    return pd.Series(dtype="float64", name=field)


def _column_contains_symbol(column: Hashable, symbol: str) -> bool:
    parts = column if isinstance(column, tuple) else (column,)
    normalized_symbol = symbol.upper().strip()
    return any(str(part).upper().strip() == normalized_symbol for part in parts)


def _select_single_column(
    data: pd.DataFrame,
    *,
    field: str,
    symbol: Optional[str],
) -> pd.Series:
    if data.shape[1] == 0:
        return _empty_series(field)

    if symbol:
        matches = [
            column
            for column in data.columns
            if _column_contains_symbol(column, symbol)
        ]
        if len(matches) == 1:
            return data[matches[0]]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple {field} columns matched symbol {symbol}: {matches}"
            )

    if data.shape[1] == 1:
        return data.iloc[:, 0]

    raise ValueError(
        f"Expected one {field} column but received {data.shape[1]}; "
        "provide a symbol to select the intended series."
    )


def extract_yfinance_series(
    frame: Any,
    field: str,
    symbol: Optional[str] = None,
) -> pd.Series:
    """Return one numeric OHLCV series from yfinance output.

    Depending on yfinance version and request shape, ``download`` can return
    either flat columns (``Close``) or MultiIndex columns such as
    (``Close``, ``AAPL``) / (``AAPL``, ``Close``). Scanner calculations need
    a one-dimensional scalar series, so this helper normalizes both layouts
    and rejects ambiguous multi-symbol data instead of silently selecting the
    wrong ticker.
    """

    if frame is None:
        return _empty_series(field)
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(
            f"Expected a pandas DataFrame for {field}, got {type(frame).__name__}"
        )
    if frame.empty:
        return _empty_series(field)

    selected: Any
    if isinstance(frame.columns, pd.MultiIndex):
        matching_levels = [
            level
            for level in range(frame.columns.nlevels)
            if field in frame.columns.get_level_values(level)
        ]
        if not matching_levels:
            return _empty_series(field)
        selected = frame.xs(
            field,
            axis=1,
            level=matching_levels[0],
            drop_level=True,
        )
    else:
        if field not in frame.columns:
            return _empty_series(field)
        selected = frame[field]

    if isinstance(selected, pd.DataFrame):
        selected = _select_single_column(
            selected,
            field=field,
            symbol=symbol,
        )

    if not isinstance(selected, pd.Series):
        selected = pd.Series(selected, index=frame.index, name=field)

    normalized = pd.to_numeric(selected, errors="coerce").dropna().astype(float)
    normalized.name = field
    return normalized
