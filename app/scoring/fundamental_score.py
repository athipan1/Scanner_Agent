from typing import Dict, Any, Optional
from app.config import settings

def calculate_quality_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the quality score based on a set of quality metrics using a granular scale."""
    score = 0
    max_score = 0

    # ROE: >15: 1.0, 10-15: 0.7, 5-10: 0.3
    if metrics.get("roe") is not None:
        max_score += 1
        val = metrics["roe"]
        if val > 15: score += 1.0
        elif val > 10: score += 0.7
        elif val > 5: score += 0.3

    # ROA: >10: 1.0, 7-10: 0.7, 4-7: 0.3
    if metrics.get("roa") is not None:
        max_score += 1
        val = metrics["roa"]
        if val > 10: score += 1.0
        elif val > 7: score += 0.7
        elif val > 4: score += 0.3

    # Debt-to-Equity: <0.5: 1.0, 0.5-1.0: 0.7, 1.0-1.5: 0.3
    if metrics.get("debt_to_equity") is not None:
        max_score += 1
        val = metrics["debt_to_equity"]
        if val < 0.5: score += 1.0
        elif val < 1.0: score += 0.7
        elif val < 1.5: score += 0.3

    # Positive Free Cash Flow
    if metrics.get("free_cash_flow") is not None:
        max_score += 1
        if metrics["free_cash_flow"] > 0:
            score += 1.0

    # Profit Margin: >10: 1.0, 7-10: 0.7, 4-7: 0.3
    if metrics.get("profit_margins") is not None:
        max_score += 1
        val = metrics["profit_margins"]
        if val > 10: score += 1.0
        elif val > 7: score += 0.7
        elif val > 4: score += 0.3

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_growth_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the growth score based on growth metrics using a granular scale."""
    score = 0
    max_score = 0

    # Revenue CAGR: >10: 1.0, 7-10: 0.7, 4-7: 0.3
    if metrics.get("revenue_cagr") is not None:
        max_score += 1
        val = metrics["revenue_cagr"]
        if val > 10: score += 1.0
        elif val > 7: score += 0.7
        elif val > 4: score += 0.3

    # EPS Growth: >10: 1.0, 7-10: 0.7, 4-7: 0.3
    if metrics.get("eps_growth") is not None:
        max_score += 1
        val = metrics["eps_growth"]
        if val > 10: score += 1.0
        elif val > 7: score += 0.7
        elif val > 4: score += 0.3

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_valuation_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the valuation score based on valuation metrics using a granular scale."""
    score = 0
    max_score = 0

    # P/E: <20: 1.0, 20-30: 0.7, 30-40: 0.3
    if metrics.get("pe_ratio") is not None:
        max_score += 1
        val = metrics["pe_ratio"]
        if val < 20: score += 1.0
        elif val < 30: score += 0.7
        elif val < 40: score += 0.3

    # PEG: <1.0: 1.0, 1.0-1.5: 0.7, 1.5-2.0: 0.3
    if metrics.get("peg_ratio") is not None:
        max_score += 1
        val = metrics["peg_ratio"]
        if val < 1.0: score += 1.0
        elif val < 1.5: score += 0.7
        elif val < 2.0: score += 0.3

    # P/B: <3.0: 1.0, 3.0-4.5: 0.7, 4.5-6.0: 0.3
    if metrics.get("pb_ratio") is not None:
        max_score += 1
        val = metrics["pb_ratio"]
        if val < 3.0: score += 1.0
        elif val < 4.5: score += 0.7
        elif val < 6.0: score += 0.3

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_fundamental_score(scores: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the final fundamental score from the individual scores."""
    total_score = 0
    total_weight = 0

    if scores.get("quality_score") is not None:
        total_score += scores["quality_score"] * settings.QUALITY_SCORE_WEIGHT
        total_weight += settings.QUALITY_SCORE_WEIGHT

    if scores.get("growth_score") is not None:
        total_score += scores["growth_score"] * settings.GROWTH_SCORE_WEIGHT
        total_weight += settings.GROWTH_SCORE_WEIGHT

    if scores.get("valuation_score") is not None:
        total_score += scores["valuation_score"] * settings.VALUATION_SCORE_WEIGHT
        total_weight += settings.VALUATION_SCORE_WEIGHT

    if total_weight == 0:
        return None

    return total_score / total_weight

def get_grade(score: float) -> str:
    """Assigns a grade based on the fundamental score."""
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    else:
        return "C"
