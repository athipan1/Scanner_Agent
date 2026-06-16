from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

import json

from app.services.feedback_loop import load_feedback_records, recommended_weight_adjustments


DEFAULT_WEIGHTS_PATH = Path("data/score_weights.json")

BASE_WEIGHTS = {
    "prefilter_score": 0.04,
    "market_rank_score": 0.08,
    "technical_vote_score": 0.13,
    "indicator_score": 0.17,
    "momentum_score": 0.10,
    "relative_strength_score": 0.06,
    "sector_rotation_score": 0.09,
    "growth_score": 0.05,
    "backtest_score": 0.12,
    "fundamental_score": 0.11,
    "risk_score": 0.05,
}

MIN_WEIGHT = 0.02
MAX_WEIGHT = 0.25


@dataclass
class WeightTuningResult:
    weights: Dict[str, float]
    adjustments: Dict[str, float]
    reason: str


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    clipped = {key: max(MIN_WEIGHT, min(MAX_WEIGHT, float(value))) for key, value in weights.items()}
    total = sum(clipped.values()) or 1.0
    return {key: round(value / total, 4) for key, value in clipped.items()}


def load_score_weights(path: Path = DEFAULT_WEIGHTS_PATH) -> Dict[str, float]:
    if not path.exists():
        return dict(BASE_WEIGHTS)
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        loaded = {key: float(data.get(key, BASE_WEIGHTS[key])) for key in BASE_WEIGHTS}
        return _normalize(loaded)
    except Exception:
        return dict(BASE_WEIGHTS)


def save_score_weights(weights: Dict[str, float], path: Path = DEFAULT_WEIGHTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(_normalize(weights), file, ensure_ascii=False, indent=2, sort_keys=True)


def tune_score_weights(records: Iterable[Dict[str, object]] | None = None) -> WeightTuningResult:
    records = list(records if records is not None else load_feedback_records())
    current_weights = load_score_weights()

    if len(records) < 20:
        return WeightTuningResult(
            weights=current_weights,
            adjustments={key: 0.0 for key in current_weights},
            reason="ข้อมูล Feedback ยังน้อยกว่า 20 records จึงยังไม่ปรับน้ำหนัก",
        )

    adjustments = recommended_weight_adjustments(records)
    tuned_weights = dict(current_weights)
    for key, adjustment in adjustments.items():
        if key in tuned_weights:
            tuned_weights[key] = tuned_weights[key] + adjustment

    tuned_weights = _normalize(tuned_weights)
    save_score_weights(tuned_weights)
    return WeightTuningResult(
        weights=tuned_weights,
        adjustments=adjustments,
        reason="ปรับน้ำหนักจากค่าเฉลี่ยคะแนนของสัญญาณที่ชนะเทียบกับสัญญาณที่แพ้",
    )
