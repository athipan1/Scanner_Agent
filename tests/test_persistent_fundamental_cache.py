import json
import time

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


def test_persistent_cache_round_trip_is_explicit_and_broker_isolated(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_TTL_SECONDS", "3600")

    candidate = cache.annotate_fresh_candidate(_candidate("AAPL"))
    assert cache.store_candidate(candidate, "NASDAQ") is True

    loaded = cache.load_candidate("AAPL", "NASDAQ")

    assert loaded is not None
    evidence = loaded.metadata["fundamental_cache"]
    assert evidence["hit"] is True
    assert evidence["scope"] == "broad_fundamental_discovery_only"
    assert evidence["production_execution_evidence_reused"] is False
    assert cache.cache_status()["entry_count"] == 1


def test_expired_cache_entry_is_not_reused(monkeypatch, tmp_path):
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_CACHE_TTL_SECONDS", "300")

    candidate = _candidate("MSFT")
    assert cache.store_candidate(candidate, "NASDAQ") is True
    path = next(tmp_path.glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at_epoch"] = time.time() - 301
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.load_candidate("MSFT", "NASDAQ") is None


def test_discovery_uses_cache_before_provider(monkeypatch):
    monkeypatch.setattr(
        cached.base,
        "build_us_fundamental_universe",
        lambda max_universe: {
            "symbols": ["AAA", "BBB"],
            "sources": {"universe_degraded": False},
        },
    )
    monkeypatch.setattr(cached.base, "_is_discoverable_stock_symbol", lambda symbol: True)
    monkeypatch.setattr(cached, "load_candidate", lambda symbol, exchange: _candidate("AAA", 0.9) if symbol == "AAA" else None)
    provider_calls = []

    def analyze(symbol, exchange):
        provider_calls.append(symbol)
        return _candidate(symbol, 0.8)

    monkeypatch.setattr(cached.base, "analyze_fundamental_candidate", analyze)
    monkeypatch.setattr(cached, "store_candidate", lambda candidate, exchange: True)
    monkeypatch.setattr(
        cached,
        "cache_status",
        lambda: {
            "schema_version": cache.CACHE_SCHEMA,
            "enabled": True,
            "ttl_seconds": 3600,
            "entry_count": 1,
            "scope": "broad_fundamental_discovery_only",
            "production_execution_evidence_reused": False,
        },
    )

    candidates, errors, metadata = cached.discover_best_fundamentals(
        max_universe=2,
        top_n=2,
        max_workers=4,
    )

    assert errors == []
    assert provider_calls == ["BBB"]
    assert [candidate.symbol for candidate in candidates] == ["AAA", "BBB"]
    assert metadata["fundamental_cache"]["hit_count"] == 1
    assert metadata["fundamental_cache"]["miss_count"] == 1
    assert metadata["analyzed_count"] == 2


def test_rate_limit_batch_reduces_provider_concurrency(monkeypatch):
    symbols = [f"R{i}" for i in range(6)]
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_PROVIDER_BATCH_SIZE", "3")
    monkeypatch.setenv("SCANNER_FUNDAMENTAL_RATE_LIMIT_COOLDOWN_SECONDS", "0")
    monkeypatch.setattr(
        cached.base,
        "build_us_fundamental_universe",
        lambda max_universe: {
            "symbols": symbols,
            "sources": {"universe_degraded": False},
        },
    )
    monkeypatch.setattr(cached.base, "_is_discoverable_stock_symbol", lambda symbol: True)
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

    def analyze(symbol, exchange):
        if symbol in {"R0", "R1", "R2"}:
            raise ValueError("429 Too Many Requests")
        return _candidate(symbol)

    monkeypatch.setattr(cached.base, "analyze_fundamental_candidate", analyze)

    candidates, errors, metadata = cached.discover_best_fundamentals(
        max_universe=6,
        top_n=6,
        max_workers=4,
    )

    assert len(candidates) == 3
    assert len(errors) == 3
    control = metadata["adaptive_provider_control"]
    assert control["rate_limit_events"] == 3
    assert control["throttle_events"] >= 1
    assert control["minimum_workers_seen"] == 1
    assert control["trading_thresholds_relaxed"] is False
