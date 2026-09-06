import importlib.util
from pathlib import Path
from types import SimpleNamespace as Row

spec=importlib.util.spec_from_file_location('discovery_funnel',Path(__file__).parents[1]/'app/services/discovery_funnel.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_every_unselected_symbol_has_a_reason_without_fabricating_market_stages():
    candidates=[Row(symbol='AAPL',candidate_score=90),Row(symbol='MSFT',candidate_score=80)]
    result=module.build_discovery_funnel(['AAPL','MSFT','FAIL','DEFER'],candidates,[Row(symbol='FAIL',error='missing market data')],candidates[:1])
    assert result['universe_count']==4
    assert result['fundamental_ranked_count']==2
    assert result['prefilter_count'] is None
    assert result['ranked_market_status']=='not_in_route'
    assert {r['symbol'] for r in result['rejections']}=={'MSFT','FAIL','DEFER'}
    assert result['rejections'][0]['threshold']==90
    assert result['thresholds_relaxed'] is False
