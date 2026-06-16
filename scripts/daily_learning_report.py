from __future__ import annotations

from pathlib import Path
from typing import Iterable

import json

from app.services.scanner import scan_market
from app.services.feedback_loop import evaluate_feedback_history, load_feedback_records, summarize_feedback
from app.services.weight_tuner import tune_score_weights


REPORT_PATH = Path("data/daily_learning_report.md")


def _pct(value):
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def _line_items(items: Iterable[str]) -> str:
    items = list(items)
    if not items:
        return "- ไม่มีข้อมูล"
    return "\n".join(f"- {item}" for item in items)


def build_report() -> str:
    candidates, errors = scan_market(symbols=[], screener="america", exchange="NASDAQ")
    feedback_results = evaluate_feedback_history()
    feedback_summary = summarize_feedback(feedback_results)
    feedback_records = load_feedback_records()
    tuning_result = tune_score_weights(feedback_records)

    lines = []
    lines.append("# AI Scanner Daily Learning Report")
    lines.append("")
    lines.append("## สรุปการสแกนวันนี้")
    lines.append(f"- Candidates ที่ผ่านเข้ารอบ: {len(candidates)}")
    lines.append(f"- Errors: {len(errors)}")
    lines.append("")

    lines.append("## Top Candidates")
    if not candidates:
        lines.append("- วันนี้ยังไม่มีหุ้นที่ผ่านเกณฑ์")
    for index, candidate in enumerate(candidates, start=1):
        details = candidate.details or {}
        lines.append(f"### {index}. {candidate.symbol}")
        lines.append(f"- Recommendation: {candidate.recommendation}")
        lines.append(f"- Final Score: {details.get('final_score', 'N/A')}")
        lines.append(f"- Exchange: {details.get('resolved_exchange', 'N/A')}")
        reasons = details.get("reason") or []
        lines.append("- เหตุผล:")
        lines.append(_line_items(reasons[:8]))
        lines.append("")

    lines.append("## Feedback ย้อนหลัง")
    lines.append(f"- Records ทั้งหมด: {feedback_summary.get('total_records')}")
    lines.append(f"- Records ที่ประเมินได้: {feedback_summary.get('evaluated_records')}")
    lines.append(f"- Wins: {feedback_summary.get('wins')}")
    lines.append(f"- Losses: {feedback_summary.get('losses')}")
    lines.append(f"- Neutral: {feedback_summary.get('neutral')}")
    lines.append(f"- Win Rate: {_pct(feedback_summary.get('win_rate'))}")
    lines.append(f"- Average Return: {_pct(feedback_summary.get('average_return_pct'))}")
    lines.append(f"- Best Symbols: {', '.join(feedback_summary.get('best_symbols') or []) or 'N/A'}")
    lines.append(f"- Worst Symbols: {', '.join(feedback_summary.get('worst_symbols') or []) or 'N/A'}")
    lines.append("")

    lines.append("## Weight Tuning")
    lines.append(f"- สถานะ: {tuning_result.reason}")
    lines.append("- Adjustments:")
    for key, value in tuning_result.adjustments.items():
        lines.append(f"  - {key}: {value:+.4f}")
    lines.append("")
    lines.append("- Current Weights:")
    for key, value in tuning_result.weights.items():
        lines.append(f"  - {key}: {value:.4f}")

    return "\n".join(lines) + "\n"


def main() -> None:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
