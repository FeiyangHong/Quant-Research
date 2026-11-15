"""Verify the completed M7 descriptions against the independent cash oracle."""
import csv
import itertools
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'reports/m7_cohort'


def read(path):return json.loads(Path(path).read_bytes())
def csvrows(name):
    with (REPORT/(name+'.csv')).open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))


def main():
    proof=read(ROOT/'reports/m7_review/independent_raw_probe.json')
    assert all(r['N_upper_bound']<3 for r in proof['months'])
    pairs=['R0-E0','R1-E1','E1-E0','R1-R0','R1-R0-E1+E0']
    pressure=['base','cost_2x','cost_3x','delay_1_session']
    rows=read(REPORT/'PAIRED_EVALUATION.json')
    assert len(rows)==40
    assert {(r['period'],r['path'],r['pair']) for r in rows}==set(itertools.product(['development','validation'],pressure,pairs))
    intervals=0
    for row in rows:
        expected_n=1461 if row['period']=='development' else 726
        assert row['n_dates']==expected_n
        assert row['mean_daily_net_increment']==0
        assert row['signed_annual_fixed_cost_capacity_cny']==0
        assert row['annual_incremental_cost'] is None and row['economic_status']=='BLOCKED_HURDLE'
        assert row['nonzero_daily_differences']==0
        if row['path']=='base':
            assert [r['block_length'] for r in row['descriptive_intervals']]==[60,20,120]
            for result in row['descriptive_intervals']:
                intervals+=1
                assert result['n_dates']==expected_n and result['mean_net_increment']==0
                assert result['status']=='BLOCKED_HURDLE'
                assert result['descriptive_status']=='INCONCLUSIVE_DEGENERATE'
                assert result['seed']==20261114 and result['repetitions']==5000
                for field in ['annual_incremental_cost','daily_hurdle','p_net','p_hac','ci95']:assert result[field] is None
        else:assert 'descriptive_intervals' not in row
    assert intervals==30
    products=csvrows('annual_product_pnl');accounts=csvrows('annual_account_reconciliation')
    assert len(accounts)==144 and len(products)==1008
    members=set(proof['raw_coverage'])
    for row in accounts:
        assert float(row['net_pnl_cny'])==float(row['product_pnl_cny'])==float(row['error_cny'])==0
        group=[r for r in products if r['trial_id']==row['trial_id'] and r['year']==row['year']]
        assert len(group)==7 and {r['instrument_id'] for r in group}==members
        assert all(float(r['net_pnl_cny'])==float(r['fees_cny'])==0 for r in group)
    returns=csvrows('daily_account_returns')
    assert len(returns)==34992
    assert all(float(r['net_daily_return'])==0 and float(r['nav_cny'])==100000 for r in returns)
    differences=csvrows('target_and_holdings_differences')
    assert len(differences)==32
    assert all(float(r[k])==0 for r in differences for k in
               ['selection_set_difference','target_vector_difference','actual_position_day_difference'])
    summary=read(REPORT/'RESULTS_SUMMARY.json')
    assert summary['actual_accounts']==32 and summary['conclusion']=='LIMITED_IDENTIFICATION'
    assert summary['primary']['period']=='validation' and summary['primary']['pair']=='R0-E0'
    assert summary['primary']['path']=='base'
    assert summary['unknown_fixed_cost'] is None and summary['economic_confirmation']=='BLOCKED_HURDLE'
    result=dict(status='PASS_INDEPENDENT_FIXED_EVALUATION',paired_descriptions=40,base_interval_records=30,
                annual_account_rows=144,annual_product_rows=1008,full_calendar_daily_return_rows=34992,
                conclusion='LIMITED_IDENTIFICATION',economic_confirmation='BLOCKED_HURDLE',
                caution='Zero differences have no ranking identification. Identical pressures are mechanically inactive, not measured cost robustness. Valid nondegenerate synthetic intervals were separately verified.')
    (ROOT/'reports/m7_review/independent_evaluation_probe.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
