from app.models import ScannerCandidateContract
from app.services import cached_fundamental_discovery as cached
from app.services import fundamental_candidate_cache as cache


def _candidate(symbol: str, score: float = 0.8) -> ScannerCandidateContract:
    return ScannerCandidateContract(
        symbol=symbol,
        candidate_score=score,
        exchange="NASDAQ",
        screener="america",
        recommendation_hint="FUNDAMENTAL_TOP_10",
        raw_scores={
            "fundamental_score": score * 100,
            "evidence_coverage": 1.0,
        },
        metadata={"source": "real_market_fundamental_discovery"},
    )


def _stub_runtime(monkeypatch, symbols):
    monkeypatch.setattr(
        cached.base,
        "build_us_fundamental_universe",
        lambda max_universe: {
            "symbols": list(symbols),
            "sources": {"universe_degraded": False},
        },
    )
    monkeypatch.setattr(
        cached.base,
        "_is_discoverable_stock_symbol",
        lambda symbol: True,
    )
    monkeypatch.setattr(cached, "load_candidate", lambda symbol, exchange: None)
    monkeypatch.setattr(cached, "store_candidate", lambda candidate, exchange: True)
    monkeypatch.setattr(
        cached,
        "cache_status",
        lambda: {
            "schema_version": cache.CACHE_SCHEMA,
            "enabled": True,
            "ttl_seconds": 3600,
            "entry_count": 0,
            "scope": "broad_fundamental_discovery_only",
            "production_execution_evidence_reused": False,
        },
    )
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_RATE_LIMIT_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv(
        "SCANNER_FUNDAMENTAL_RATE_LIMIT_MAX_COOLDOWN_SECONDS",
        "0",
    )


def test_rate_limited_symbols_are_retried_serially_and_recovered(monkeypatch):
    symbols = [f"R{i}" for i in range(6)]
    _stub_runtime(monkeypatch, symbols)
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_PROVIDER_BATCH_SIZE", "3")
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_RATE_LIMIT_RETRY_ATTEMPTS", "1")

    calls = {}

    def analyze(symbol, exchange):
        calls[symbol] = calls.get(symbol, 0) + 1
        if symbol in {"R0", "R1", "R2"} and calls[symbol] == 1:
            raise ValueError("429 Too Many Requests")
        return _candidate(symbol)

    monkeypatch.setattr(cached.base, "analyze_fundamental_candidate", analyze)

    candidates, errors, metadata = cached.discover_best_fundamentals(
        max_universe=6,
        top_n=6,
        max_workers=4,
    )

    assert errors == []
    assert {candidate.symbol for candidate in candidates} == set(symbols)
    control = metadata["adaptive_provider_control"]
    assert control["rate_limit_events"] == 3
    assert control["retry_symbol_attempts"] == 3
    assert control["recovered_rate_limit_events"] == 3
    assert control["unresolved_rate_limit_events"] == 0
    assert control["minimum_workers_seen"] == 1
    assert control["provider_request_attempts"] == 9
    assert control["trading_thresholds_relaxed"] is False


def test_sustained_provider_pressure_opens_bounded_circuit_after_candidate_buffer(
    monkeypatch,
):
    symbols = [f"S{i}" for i in range(30)]
    _stub_runtime(monkeypatch, symbols)
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_PROVIDER_BATCH_SIZE", "5")
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_RATE_LIMIT_RETRY_ATTEMPTS", "0")
    monkeypatch.setenv(
        "SCANNER_FUNDAMENTAL_PROVIDER_CIRCUIT_BREAKER_BATCHES",
        "3",
    )
    monkeypatch.setenv(
        "SCANNER_FUNDAMENTAL_PROVIDER_CANDIDATE_BUFFER_MULTIPLIER",
        "2",
    )

    def analyze(symbol, exchange):
        index = int(symbol[1:])
        if index >= 5:
            raise ValueError("HTTP 429 Too Many Requests")
        return _candidate(symbol, score=0.9 - index / 100)

    monkeypatch.setattr(cached.base, "analyze_fundamental_candidate", analyze)

    candidates, errors, metadata = cached.discover_best_fundamentals(
        max_universe=30,
        top_n=2,
        max_workers=4,
    )

    assert [candidate.symbol for candidate in candidates] == ["S0", "S1"]
    control = metadata["adaptive_provider_control"]
    assert control["provider_circuit_opened"] is True
    assert control["provider_request_avoided_count"] == 10
    assert control["candidate_buffer_required"] == 4
    assert control["minimum_workers_seen"] == 1
    assert control["minimum_batch_size_seen"] == 5
    assert control["trading_thresholds_relaxed"] is False
    assert control["production_execution_evidence_reused"] is False
    assert metadata["requested_universe_count"] == 30
    assert metadata["attempted_count"] == 20
    assert metadata["deferred_provider_count"] == 10
    assert len(errors) == 15
