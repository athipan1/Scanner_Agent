from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Optional

import json
import yfinance as yf


DEFAULT_FEEDBACK_PATH = Path("data/feedback_history.jsonl")
DEFAULT_HORIZONS = (1, 5, 10)


@dataclass
class FeedbackResult:
    symbol: str
    selected_at: str
    entry_price: Optional[float]
    current_price: Optional[float]
    return_pct: Optional[float]
    holding_days: Optional[int]
    final_score: Optional[float]
    scanner_version: Optional[str]
    outcome: str
    reason: List[str]


def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_between(start: Optional[datetime], end: Optional[datetime] = None) -> Optional[int]:
    if start is None:
        return None
    end = end or _now_utc()
    return max(0, (end - start).days)


def _latest_price(symbol: str) -> Optional[float]:
    try:
        history = yf.download(symbol, period="5d", interval="1d", progress=False, auto_adjust=True)
        if history is None or history.empty or "Close" not in history:
            return None
        close = history["Close"].dropna()
        if close.empty:
            return None
        return _safe_float(close.iloc[-1])
    except Exception:
        return None


def _classify_outcome(return_pct: Optional[float]) -> str:
    if return_pct is None:
        return "UNKNOWN"
    if return_pct >= 0.05:
        return "WIN"
    if return_pct <= -0.03:
        return "LOSS"
    return "NEUTRAL"


def _infer_scanner_version(details: Dict[str, object]) -> Optional[str]:
    for key in sorted(details.keys(), reverse=True):
        if key.startswith("scanner_v"):
            return key
    return None


def candidate_to_feedback_seed(candidate) -> Dict[str, object]:
    details = getattr(candidate, "details", {}) or {}
    symbol = getattr(candidate, "symbol", "")
    entry_price = _safe_float(details.get("close"))
    return {
        "symbol": symbol,
        "selected_at": _now_utc().isoformat(),
        "entry_price": entry_price,
        "recommendation": getattr(candidate, "recommendation", None),
        "final_score": _safe_float(details.get("final_score")),
        "scanner_version": _infer_scanner_version(details),
        "scores": {
            "prefilter_score": _safe_float(details.get("prefilter_score")),
            "market_rank_score": _safe_float(details.get("market_rank_score")),
            "technical_vote_score": _safe_float(details.get("technical_vote_score")),
            "indicator_score": _safe_float(details.get("indicator_score")),
            "momentum_score": _safe_float(details.get("momentum_score")),
            "relative_strength_score": _safe_float(details.get("relative_strength_score")),
            "sector_rotation_score": _safe_float(details.get("sector_rotation_score")),
            "growth_score": _safe_float(details.get("growth_score")),
            "backtest_score": _safe_float(details.get("backtest_score")),
            "fundamental_score": _safe_float(details.get("fundamental_score")),
            "risk_score": _safe_float(details.get("risk_score")),
        },
    }


def append_feedback_seeds(candidates: Iterable, path: Path = DEFAULT_FEEDBACK_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as file:
        for candidate in candidates:
            seed = candidate_to_feedback_seed(candidate)
            if not seed.get("symbol"):
                continue
            file.write(json.dumps(seed, ensure_ascii=False) + "\n")
            count += 1
    return count


def load_feedback_records(path: Path = DEFAULT_FEEDBACK_PATH) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def evaluate_record(record: Dict[str, object]) -> FeedbackResult:
    symbol = str(record.get("symbol", "")).upper().strip()
    selected_at = str(record.get("selected_at") or "")
    entry_price = _safe_float(record.get("entry_price"))
    current_price = _latest_price(symbol) if symbol else None
    return_pct = None
    if entry_price and current_price:
        return_pct = (current_price - entry_price) / entry_price

    holding_days = _days_between(_parse_datetime(selected_at))
    outcome = _classify_outcome(return_pct)
    reasons: List[str] = []
    if return_pct is not None:
        reasons.append(f"ผลตอบแทนล่าสุด {return_pct:.2%}")
    if holding_days is not None:
        reasons.append(f"ถือมาแล้วประมาณ {holding_days} วัน")
    if outcome == "WIN":
        reasons.append("สัญญาณนี้กำลังชนะ ควรศึกษาคะแนนที่สนับสนุน")
    elif outcome == "LOSS":
        reasons.append("สัญญาณนี้แพ้ ควรลดน้ำหนักปัจจัยที่พาเข้าผิด")
    else:
        reasons.append("ผลลัพธ์ยังไม่ชัดเจน")

    return FeedbackResult(
        symbol=symbol,
        selected_at=selected_at,
        entry_price=entry_price,
        current_price=current_price,
        return_pct=return_pct,
        holding_days=holding_days,
        final_score=_safe_float(record.get("final_score")),
        scanner_version=record.get("scanner_version"),
        outcome=outcome,
        reason=reasons,
    )


def evaluate_feedback_history(path: Path = DEFAULT_FEEDBACK_PATH) -> List[FeedbackResult]:
    return [evaluate_record(record) for record in load_feedback_records(path)]


def summarize_feedback(results: Iterable[FeedbackResult]) -> Dict[str, object]:
    result_list = list(results)
    known = [item for item in result_list if item.return_pct is not None]
    wins = [item for item in known if item.outcome == "WIN"]
    losses = [item for item in known if item.outcome == "LOSS"]
    neutrals = [item for item in known if item.outcome == "NEUTRAL"]

    avg_return = mean([item.return_pct for item in known]) if known else None
    win_rate = len(wins) / len(known) if known else None

    return {
        "total_records": len(result_list),
        "evaluated_records": len(known),
        "wins": len(wins),
        "losses": len(losses),
        "neutral": len(neutrals),
        "win_rate": win_rate,
        "average_return_pct": avg_return,
        "best_symbols": [item.symbol for item in sorted(known, key=lambda x: x.return_pct or 0, reverse=True)[:5]],
        "worst_symbols": [item.symbol for item in sorted(known, key=lambda x: x.return_pct or 0)[:5]],
    }


def recommended_weight_adjustments(records: Iterable[Dict[str, object]]) -> Dict[str, float]:
    score_keys = [
        "prefilter_score",
        "market_rank_score",
        "technical_vote_score",
        "indicator_score",
        "momentum_score",
        "relative_strength_score",
        "sector_rotation_score",
        "growth_score",
        "backtest_score",
        "fundamental_score",
        "risk_score",
    ]
    grouped = {key: {"win": [], "loss": []} for key in score_keys}

    for record in records:
        evaluated = evaluate_record(record)
        scores = record.get("scores") or {}
        if evaluated.outcome not in {"WIN", "LOSS"}:
            continue
        bucket = "win" if evaluated.outcome == "WIN" else "loss"
        for key in score_keys:
            value = _safe_float(scores.get(key))
            if value is not None:
                grouped[key][bucket].append(value)

    adjustments: Dict[str, float] = {}
    for key, buckets in grouped.items():
        if not buckets["win"] or not buckets["loss"]:
            adjustments[key] = 0.0
            continue
        win_avg = mean(buckets["win"])
        loss_avg = mean(buckets["loss"])
        # Positive means winners had stronger values than losers, so weight can be nudged up.
        adjustments[key] = round(max(-0.03, min(0.03, (win_avg - loss_avg) * 0.05)), 4)
    return adjustments
