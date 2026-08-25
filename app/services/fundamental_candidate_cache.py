from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from app.models import ScannerCandidateContract

CACHE_SCHEMA = "scanner-fundamental-candidate-cache.v1"
_DEFAULT_TTL_SECONDS = 6 * 60 * 60
_SAFE_KEY = re.compile(r"[^A-Z0-9._-]+")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def cache_enabled() -> bool:
    """Return whether persistent broad-discovery caching is explicitly enabled."""

    return _bool_env("SCANNER_FUNDAMENTAL_CACHE_ENABLED", False)


def cache_ttl_seconds() -> int:
    raw = os.getenv("SCANNER_FUNDAMENTAL_CACHE_TTL_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return max(300, min(value, 7 * 24 * 60 * 60))


def cache_directory() -> Path:
    configured = os.getenv("SCANNER_FUNDAMENTAL_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(".cache") / "scanner" / "fundamentals"


def _cache_key(symbol: str, exchange: str) -> str:
    raw = f"{exchange.strip().upper()}__{symbol.strip().upper()}"
    return _SAFE_KEY.sub("_", raw).strip("_") or "UNKNOWN"


def _cache_path(symbol: str, exchange: str) -> Path:
    return cache_directory() / f"{_cache_key(symbol, exchange)}.json"


def _cache_metadata(*, hit: bool, age_seconds: float | None = None) -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA,
        "enabled": cache_enabled(),
        "hit": hit,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "ttl_seconds": cache_ttl_seconds(),
        "scope": "broad_fundamental_discovery_only",
        "production_execution_evidence_reused": False,
    }


def annotate_fresh_candidate(candidate: ScannerCandidateContract) -> ScannerCandidateContract:
    metadata = dict(candidate.metadata or {})
    metadata["fundamental_cache"] = _cache_metadata(hit=False)
    return candidate.model_copy(update={"metadata": metadata}, deep=True)


def load_candidate(symbol: str, exchange: str) -> ScannerCandidateContract | None:
    """Load a validated fresh candidate from the JSON cache.

    The cache is deliberately limited to broad fundamental discovery. Final
    production enrichment must still refresh Technical, quote, ATR, volume and
    execution evidence before any Manager/Risk/Execution decision.
    """

    if not cache_enabled():
        return None

    path = _cache_path(symbol, exchange)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("schema_version") != CACHE_SCHEMA:
        return None
    if str(payload.get("symbol") or "").strip().upper() != symbol.strip().upper():
        return None
    if str(payload.get("exchange") or "").strip().upper() != exchange.strip().upper():
        return None

    try:
        created_at = float(payload["created_at_epoch"])
    except (KeyError, TypeError, ValueError):
        return None
    age_seconds = max(0.0, time.time() - created_at)
    if age_seconds > cache_ttl_seconds():
        return None

    try:
        candidate = ScannerCandidateContract.model_validate(payload["candidate"])
    except Exception:
        return None

    metadata = dict(candidate.metadata or {})
    metadata["fundamental_cache"] = _cache_metadata(
        hit=True,
        age_seconds=age_seconds,
    )
    return candidate.model_copy(update={"metadata": metadata}, deep=True)


def store_candidate(
    candidate: ScannerCandidateContract,
    exchange: str,
) -> bool:
    """Atomically persist a successful broad-discovery candidate as JSON."""

    if not cache_enabled():
        return False

    path = _cache_path(candidate.symbol, exchange)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CACHE_SCHEMA,
            "created_at_epoch": time.time(),
            "symbol": candidate.symbol.strip().upper(),
            "exchange": exchange.strip().upper(),
            "candidate": candidate.model_dump(mode="json"),
        }
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def cache_status() -> dict[str, Any]:
    directory = cache_directory()
    entry_count = 0
    if cache_enabled():
        try:
            entry_count = sum(1 for path in directory.glob("*.json") if path.is_file())
        except OSError:
            entry_count = 0
    return {
        "schema_version": CACHE_SCHEMA,
        "enabled": cache_enabled(),
        "ttl_seconds": cache_ttl_seconds(),
        "entry_count": entry_count,
        "scope": "broad_fundamental_discovery_only",
        "production_execution_evidence_reused": False,
    }
