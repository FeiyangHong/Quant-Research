"""Non-author gate review; reads calendars/identities/hashes, never returns."""
import hashlib
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]


def load(relative):
    return json.loads((ROOT/relative).read_text('utf-8'))


def test_real_gate_keeps_unknowns_and_explicit_boundary_execution_dates():
    gate=load('reports/m6_r1i/monthly_data_gate.json')
    rows=gate['decisions']
    # Independently fixed exchange-calendar boundary examples, not selectors.
    first=rows[0]
    assert (first['anchor'],first['release_at'],first['first_execution'],first['quarter_cutoff']) == (
        '2015-12-31','2016-01-04T21:00:00+08:00','2016-01-05','2015-09-30')
    validation=next(r for r in rows if r['period']=='validation')
    assert (validation['anchor'],validation['first_execution']) == ('2021-12-31','2022-01-05')
    assert (rows[-1]['anchor'],rows[-1]['first_execution']) == ('2024-11-29','2024-12-03')
    assert len(rows)==108 and gate['denominator_by_period']==dict(development=72,validation=36)
    assert gate['n_distribution']=={'UNKNOWN':108}
    assert gate['n_ge4_trend_on'] is None
    assert all(r['status']=='DATA_BLOCKED' and r['n_eligible'] is None and
               r['n_ge_4'] is None and r['trend_on'] is None for r in rows)
    assert not any(r['anchor'].startswith('2024-12') for r in rows)


def test_inventory_does_not_drop_unresolved_or_retired_identities():
    report=load('reports/m6_r1i/candidate_inventory.json')
    rows=report['records']
    assert len(rows)==report['count']==1148
    assert len({r['instrument_id'] for r in rows})==1148
    assert all(r['scope_exclusion_by_name'] is False for r in rows)
    retired=next(r for r in rows if r['instrument_id']=='sz.159917')
    assert retired['relevant_selection_dates']==[]
    assert retired['review_status']=='OUTSIDE_REQUIRED_ENDPOINTS_CONDITIONAL_ON_SOURCE_COMPLETENESS'
    relevant=[r for r in rows if r['relevant_selection_dates']]
    assert len(relevant)==1099
    assert sum(r['raw_history'] is None for r in relevant)==991
    assert all(r['csi_l1_id'] is None and r['historical_identity_complete'] is False for r in relevant)


@pytest.mark.archived_source
def test_independently_hash_archived_identity_and_history_bytes():
    report=load('reports/m6_r1i/archive_audit.json')
    inventory=load('reports/m6_r1i/candidate_inventory.json')
    expected=dict(report['source_hashes'])
    expected.update({r['raw_path']:r['sha256'] for r in report['endpoint_sources']})
    expected.update({r['raw_history']['raw_path']:r['raw_history']['sha256']
                     for r in inventory['records'] if r['raw_history']})
    absent=[p for p in expected if not (ROOT/p).exists()]
    if absent:
        pytest.skip('Archived original bytes unavailable; missing '+str(len(absent))+' files; no real-source PASS')
    assert len(report['endpoint_sources'])==61
    for relative,wanted in expected.items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==wanted,relative
