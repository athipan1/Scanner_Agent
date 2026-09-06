"""Complete broad-discovery observations without changing candidate selection."""
from __future__ import annotations


def build_discovery_funnel(symbols, candidates, errors, selected):
    selected_symbols = {c.symbol for c in selected}
    errors_by_symbol = {e.symbol: str(e.error) for e in errors}
    analyzed_symbols = {c.symbol for c in candidates}
    cutoff = min((c.candidate_score or 0.0 for c in selected), default=None)
    rejections = []
    for rank, candidate in enumerate(candidates, 1):
        if candidate.symbol not in selected_symbols:
            rejections.append({'symbol': candidate.symbol, 'score': candidate.candidate_score,
                'threshold': cutoff, 'gate': 'scanner_fundamental_rank',
                'reason_code': 'FUNDAMENTAL_TOP_K_OVERFLOW',
                'reason': 'Outside the ranked fundamental enrichment pool; rank includes evidence tie-breakers.',
                'rank': rank, 'rank_limit': len(selected), 'lane': 'discovery'})
    for symbol in symbols:
        if symbol in analyzed_symbols:
            continue
        error = errors_by_symbol.get(symbol)
        rejections.append({'symbol': symbol, 'score': None, 'threshold': None,
            'gate': 'scanner_provider',
            'reason_code': 'SCANNER_PROVIDER_ERROR' if error else 'SCANNER_PROVIDER_DEFERRED',
            'reason': error or 'Provider circuit breaker deferred this symbol.', 'lane': 'discovery'})
    return {'schema_version': 'scanner-discovery-funnel.v1',
        'route': 'discover-best-fundamentals', 'universe_count': len(symbols),
        'prefilter_count': None, 'prefilter_status': 'not_in_route',
        'ranked_market_count': None, 'ranked_market_status': 'not_in_route',
        'fundamental_ranked_count': len(candidates), 'enrichment_pool_count': len(selected),
        'buy_recommendation_required_at_scanner': False,
        'selection_basis': 'weighted_fundamental_score_then_evidence_quality_growth_tiebreakers',
        'rejections': rejections, 'thresholds_relaxed': False}
