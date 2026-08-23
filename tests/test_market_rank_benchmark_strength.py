from app.services import market_ranker
from app.services.market_ranker import MarketRankResult


def _rank(symbol, *, score, return_20d, return_60d):
    return MarketRankResult(
        symbol=symbol,
        score=score,
        price=100.0,
        return_5d=0.01,
        return_20d=return_20d,
        return_60d=return_60d,
        volume_ratio=1.2,
        atr_pct=0.02,
        trend_score=0.8,
        reason=[],
    )


def test_market_rank_publishes_relative_returns_vs_spy(monkeypatch):
    rows = {
        "AAPL": _rank("AAPL", score=0.8, return_20d=0.10, return_60d=0.25),
        "SPY": _rank("SPY", score=0.6, return_20d=0.04, return_60d=0.12),
    }
    monkeypatch.setattr(market_ranker, "rank_symbol", lambda symbol: rows[symbol])

    selected, metadata = market_ranker.rank_market_symbols(["AAPL"])

    assert selected == ["AAPL"]
    assert metadata["AAPL"]["benchmark_symbol"] == "SPY"
    assert metadata["AAPL"]["benchmark_return_20d"] == 0.04
    assert metadata["AAPL"]["benchmark_return_60d"] == 0.12
    assert metadata["AAPL"]["relative_return_20d"] == 0.06
    assert metadata["AAPL"]["relative_return_60d"] == 0.13
    assert metadata["AAPL"]["outperforming_benchmark"] is True
    assert metadata["AAPL"]["relative_strength_method"] == (
        "benchmark_relative_returns"
    )


def test_market_rank_marks_underperformance_without_awarding_strength(monkeypatch):
    rows = {
        "WEAK": _rank("WEAK", score=0.7, return_20d=0.03, return_60d=0.08),
        "SPY": _rank("SPY", score=0.6, return_20d=0.04, return_60d=0.12),
    }
    monkeypatch.setattr(market_ranker, "rank_symbol", lambda symbol: rows[symbol])

    _, metadata = market_ranker.rank_market_symbols(["WEAK"])

    assert metadata["WEAK"]["relative_return_20d"] == -0.01
    assert metadata["WEAK"]["relative_return_60d"] == -0.04
    assert metadata["WEAK"]["outperforming_benchmark"] is False
