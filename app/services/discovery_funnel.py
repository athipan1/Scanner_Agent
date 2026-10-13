"""Complete broad-discovery observations without changing candidate selection."""
from __future__ import annotations


def build_discovery_funnel(symbols, candidates, errors, selected):
    selected_symbols = {c.symbol for c in selected}
    errors_by_symbol = {e.symbol: str(e.error) for e in errors}
    analyzed_symbols = {c.symbol for c in candidates}
    cutoff = min((c.candidate_score or 0.0 for c in selected), default=None)
    # The fundamental discovery endpoint has NOT fetched nested-OOS bar
    # history or generated an executable BUY verdict. Publish these unknowns
    # explicitly instead of treating high-ranked stocks as trade-ready.
    readiness = []
    for candidate in selected:
        metadata = getattr(candidate, 'metadata', None)
        metadata = metadata if isinstance(metadata, dict) else {}
        raw_scores = getattr(candidate, 'raw_scores', None)
        raw_scores = raw_scores if isinstance(raw_scores, dict) else {}
        coverage = raw_scores.get('evidence_coverage', metadata.get('evidence_coverage'))
        readiness.append({
            'symbol': candidate.symbol,
            'ranked_fundamental_score': candidate.candidate_score,
            'fundamental_coverage_observed': coverage,
            'historical_bars_observed': None,
            'nested_oos_history_eligible': None,
            'buy_verdict': 'not_evaluated',
            'production_entry_authorized': False,
            'next_research_gate': 'verify_882_daily_bars_and_sealed_holdout',
        })
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
        'rejections': rejections, 'thresholds_relaxed': False,
        'research_readiness': {'schema_version': 'scanner-research-readiness.v1',
            'history_fetch_performed': False, 'buy_verdict_evaluated': False,
            'ranked_candidates': readiness,
            'safe_next_step': 'Manager validates 882 1d bars before exact nested-OOS; no scanner BUY permission',
            'production_authority_granted': False}}
