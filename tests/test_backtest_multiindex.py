import pandas as pd
import pytest

pytest.importorskip("yfinance")

from app.services import backtest


def test_backtest_accepts_yfinance_multiindex(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    closes = [100.0 + index for index in range(len(dates))]
    columns = pd.MultiIndex.from_tuples([("Close", "AAPL")])
    history = pd.DataFrame(closes, index=dates, columns=columns)

    monkeypatch.setattr(backtest.yf, "download", lambda *args, **kwargs: history)
    backtest.get_backtest_result.cache_clear()

    result = backtest.get_backtest_result("AAPL")

    assert result.current_price == closes[-1]
    assert result.return_5d is not None
    assert result.return_20d is not None
    assert result.win_rate == 1.0
    assert result.score > 0.5
