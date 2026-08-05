import pandas as pd
import pytest

from app.utils.yfinance_frames import extract_yfinance_series


def _index():
    return pd.date_range("2026-01-01", periods=3, freq="D")


def test_extracts_flat_close_series():
    frame = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0], "Volume": [10, 11, 12]},
        index=_index(),
    )

    result = extract_yfinance_series(frame, "Close", "AAPL")

    assert result.tolist() == [100.0, 101.0, 102.0]
    assert result.ndim == 1


def test_extracts_field_first_multiindex_series():
    columns = pd.MultiIndex.from_tuples(
        [("Close", "AAPL"), ("Volume", "AAPL")]
    )
    frame = pd.DataFrame(
        [[100.0, 10], [101.0, 11], [102.0, 12]],
        index=_index(),
        columns=columns,
    )

    result = extract_yfinance_series(frame, "Close", "AAPL")

    assert result.tolist() == [100.0, 101.0, 102.0]
    assert all(isinstance(value, float) for value in result.tolist())


def test_extracts_symbol_first_multiindex_series():
    columns = pd.MultiIndex.from_tuples(
        [("AAPL", "Close"), ("AAPL", "Volume")]
    )
    frame = pd.DataFrame(
        [[100.0, 10], [101.0, 11], [102.0, 12]],
        index=_index(),
        columns=columns,
    )

    result = extract_yfinance_series(frame, "Close", "AAPL")

    assert result.tolist() == [100.0, 101.0, 102.0]


def test_selects_requested_symbol_from_multi_symbol_frame():
    columns = pd.MultiIndex.from_tuples(
        [("Close", "AAPL"), ("Close", "MSFT")]
    )
    frame = pd.DataFrame(
        [[100.0, 200.0], [101.0, 201.0], [102.0, 202.0]],
        index=_index(),
        columns=columns,
    )

    result = extract_yfinance_series(frame, "Close", "MSFT")

    assert result.tolist() == [200.0, 201.0, 202.0]


def test_rejects_ambiguous_multi_symbol_frame_without_symbol():
    columns = pd.MultiIndex.from_tuples(
        [("Close", "AAPL"), ("Close", "MSFT")]
    )
    frame = pd.DataFrame(
        [[100.0, 200.0], [101.0, 201.0], [102.0, 202.0]],
        index=_index(),
        columns=columns,
    )

    with pytest.raises(ValueError, match="Expected one Close column"):
        extract_yfinance_series(frame, "Close")


def test_missing_field_returns_empty_series():
    frame = pd.DataFrame({"Open": [1.0, 2.0, 3.0]}, index=_index())

    result = extract_yfinance_series(frame, "Close", "AAPL")

    assert result.empty
