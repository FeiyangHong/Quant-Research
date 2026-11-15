"""Independent interval-boundary and actual held/order intersection check."""
import hashlib
import json
from pathlib import Path
from collections import defaultdict

import pandas as pd

from quant_research.temporal import master_record

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/m4_review'


def read(path):
    return json.loads(Path(path).read_bytes())


def rows(path):
    value = read(path)
    return value['records'] if isinstance(value, dict) else value


def main():
    summary_path = ROOT/'reports/real_data_phase3/results_summary.json'
    summary = read(summary_path)
    assert hashlib.sha256(summary_path.read_bytes()).hexdigest() == 'c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb'
    drift, checks, exits, retirement_actions = [], 0, {}, {}
    for period in ('development','validation'):
        groups = defaultdict(list)
        for row in rows(ROOT/'data/admitted_r1/phase2_v1'/period/'instruments.json'):
            groups[row['instrument_id']].append(row)
            if row.get('delisted_on'):
                exits[(period,row['instrument_id'])] = dict(instrument_id=row['instrument_id'],period=period,
                    delisted_on=row['delisted_on'],available_at=row['available_at'])
        retirement_actions[period] = [r for r in rows(ROOT/'data/admitted_r1/phase2_v1'/period/'actions.json')
                                      if r['action_type'] in ('DELISTING','LIQUIDATION','LIQUIDATION_PAYMENT')]
        for sid, group in groups.items():
            dates = {'2016-01-01','2024-12-31'}
            for row in group:
                for key in ('available_at','effective_from','effective_to'):
                    if row.get(key):
                        stamp = pd.Timestamp(row[key])
                        if stamp.tzinfo: stamp = stamp.tz_convert('Asia/Shanghai')
                        dates.update((stamp + pd.Timedelta(days=shift)).strftime('%Y-%m-%d') for shift in (-1,0,1))
            for day in sorted(d for d in dates if '2010-01-01' <= d <= '2024-12-31'):
                for clock in ('00:00:00','09:30:00','21:00:00'):
                    at = pd.Timestamp(day+'T'+clock+'+08:00')
                    valid = [r for r in group if pd.Timestamp(r['available_at']) <= at
                             and (not r.get('effective_from') or r['effective_from'] <= day)
                             and (not r.get('effective_to') or r['effective_to'] > day)]
                    old = max(valid, key=lambda r: pd.Timestamp(r['available_at'])) if valid else None
                    new = master_record(group, at)
                    checks += 1
                    if (old or {}).get('revision_id') != (new or {}).get('revision_id'):
                        drift.append(dict(period=period,instrument_id=sid,at=at.isoformat(),
                                          frozen_interval_revision=(old or {}).get('revision_id'),
                                          repaired_revision=(new or {}).get('revision_id')))
    grid = pd.read_csv(ROOT/'reports/m4_frozen/effective_interval_discrepancy_grid.csv', dtype=str).fillna('')
    mismatch = {(r.period,r.date,r.instrument_id) for r in grid.itertuples()}
    intersections, counts, exit_holdings, flagged_rights = [], defaultdict(int), [], []
    for run in summary['runs']:
        folder = Path(summary['provenance']['matrix_roots'][run['period']])/run['directory']
        for name in ('positions','orders'):
            data_path=folder/(name+'.json')
            assert hashlib.sha256(data_path.read_bytes()).hexdigest() == run['table_hashes'][name]
            for row in rows(data_path):
                counts[name] += 1
                if name == 'positions' and (run['period'],row['instrument_id']) in exits:
                    exit_holdings.append(dict(run_id=run['directory'],date=row['date'],quantity=row['quantity'],
                                              instrument_id=row['instrument_id']))
                if name == 'positions' and row.get('delisted_rights'):
                    flagged_rights.append(dict(run_id=run['directory'],date=row['date'],instrument_id=row['instrument_id']))
                dates = [row['date']] if name=='positions' else [row['decision_date'],row['execution_date']]
                for day in dates:
                    if (run['period'],day,row['instrument_id']) in mismatch:
                        intersections.append(dict(run_id=run['directory'],table=name,date=day,
                                                  instrument_id=row['instrument_id']))
    result=dict(status='INDEPENDENT_READ_ONLY_CHECK_COMPLETE',runs=448,
                boundary_checks=checks,repaired_vs_original_strategy_drift=drift,
                raw_interval_grid_rows=len(grid),actual_position_order_rows=dict(counts),
                position_order_intersections=intersections,
                retained_exit_master_records=list(exits.values()), retirement_action_rows=retirement_actions,
                positions_in_retained_exit_securities=exit_holdings, delisted_rights_position_rows=flagged_rights,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                temporal_sha256=hashlib.sha256((ROOT/'src/quant_research/temporal.py').read_bytes()).hexdigest(),
                limitation='Positions/orders checked independently; other call contexts and annual attribution checked separately. No internal complete call trace; no strategy replay or holdout.')
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'independent_frozen_check.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in result.items() if k not in ('position_order_intersections','repaired_vs_original_strategy_drift')}))
    print('drift',len(drift),'intersections',len(intersections))
    annual = pd.read_csv(ROOT/'reports/m4_frozen/annual_etf_pnl_all448.csv')
    grouped = annual.groupby(['run_id','year']).agg(pnl=('net_pnl_cny','sum'),fees=('fees_cny','sum'))
    original = {(r['directory'], y['year']):(y['pnl_cny'],y['fees_cny'])
                for r in summary['runs'] for y in r['year_contributions']}
    errors = [abs(row.pnl-original[key][0]) for key,row in grouped.iterrows()]
    fee_errors = [abs(row.fees-original[key][1]) for key,row in grouped.iterrows()]
    assert len(grouped) == len(original) == 2016 and max(errors) < 1e-6 and max(fee_errors) < 1e-6
    reconciliation = dict(status='PASS',frozen_runs=448,account_years=2016,
        annual_etf_rows=len(annual),zero_etf_rows=int(annual.net_pnl_cny.eq(0).sum()),
        max_pnl_difference_cny=max(errors),max_fee_difference_cny=max(fee_errors),
        method='Independent groupby of annual ETF output against original frozen per-run year_contributions; no new strategy performance.',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'independent_annual_reconciliation.json').write_bytes((json.dumps(reconciliation,indent=2)+'\n').encode())
    print(json.dumps(reconciliation))


if __name__ == '__main__':
    main()
