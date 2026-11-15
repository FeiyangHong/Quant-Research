"""Independent raw-response arithmetic; no producer candidate-selection helper."""
import hashlib
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/m6_stock_source'


def load(name):return json.loads((OUT/name).read_text('utf-8'))


def test_contract_preserves_all3779_and_does_not_claim_pit_admission():
    decision=load('source_contract_decision.json')
    coverage=load('fixed_denominator_coverage.json')['rows']
    assert decision['decision']=='FEASIBLE_FOR_NEXT_REGISTERED_DATA_PILOT'
    assert decision['route1_complete_snapshot'] is False
    assert decision['formal_cap_admitted']==0 and decision['full_pool_percentiles'] is None
    assert decision['valuation_object_unresolved'] is True
    assert decision['route2_new_requests']==0
    assert len(coverage)==len({r['instrument_id'] for r in coverage})==3779
    assert sum(r['bulk_probe_observed'] for r in coverage)==330
    assert all(r['formal_pit_share_count'] is None and r['formal_market_cap'] is None and
               r['size_percentile'] is None for r in coverage)


@pytest.mark.archived_source
def test_raw_batch_pagination_units_clocks_and_structure_only_events():
    requests=load('request_manifest.json')
    if any(not Path(r['raw_path']).exists() for r in requests):
        pytest.skip('Raw source probe absent; no independent raw-response PASS')
    bodies=[]
    for rec in requests:
        raw=Path(rec['raw_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==rec['sha256']
        assert len(raw)==rec['byte_count']
        bodies.append(json.loads(raw)['result'])
    assert [len(r['data']) for r in bodies]==[500,500,122]
    assert [r['pages'] for r in bodies]==[389,389,1]
    assert [r['count'] for r in bodies]==[194496,194496,122]
    assert sum(r['byte_count'] for r in requests)==2290722
    assert len({(r['SECUCODE'],r['END_DATE'],r['NOTICE_DATE'],r['CHANGE_REASON'])
                for b in bodies[:2] for r in b['data']})==1000
    assert all(r['END_DATE'][:10]<='2020-07-31' for b in bodies for r in b['data'])
    assert round((requests[0]['byte_count']+requests[1]['byte_count'])/2*389)==398879433
    fixed=bodies[2]['data']
    # M5 original-document counts, fixed before M6. Share units, not price ratios.
    facts={'600519.SH':(1256197800,1256197800,0),
           '002526.SZ':(1782793836,1782793836,0),
           '601398.SH':(356406257089,269612212539,86794044550),
           '600518.SH':(4973861675,4973861675,0),
           '300855.SZ':(200000000,200000000,0)}
    assert {r['SECUCODE'] for r in fixed}==set(facts)
    for sec,(total,a,h) in facts.items():
        known=[r for r in fixed if r['SECUCODE']==sec and r['NOTICE_DATE'] and r['NOTICE_DATE'][:10]<'2020-07-31']
        chosen=max(known,key=lambda r:(r['END_DATE'],r['NOTICE_DATE']))
        assert chosen['TOTAL_SHARES']==total and chosen['TOTAL_A_SHARES']==a
        assert (chosen['H_FREE_SHARE'] or 0)==h and a+h==total
    late=next(r for r in fixed if r['SECUCODE']=='002526.SZ' and r['END_DATE'].startswith('2020-06-30'))
    assert late['NOTICE_DATE'].startswith('2020-08-20')
    assert late['TOTAL_SHARES_CHANGE']==0 and late['LIMITED_SHARES_CHANGE']==-1792500
    # Late circulation detail cannot be used as known, nor invent a total change.
    assert late['TOTAL_SHARES']==facts['002526.SZ'][0]
