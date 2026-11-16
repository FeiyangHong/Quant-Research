"""Read only M8 accounts; paired descriptions never impute unknown fixed fees."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.evaluation import paired_inference
from quant_research.data import load_dataset
from quant_research.provenance import write_json

REPORT = ROOT / 'reports/m8_rotation'
PAIRS = [('R0', 'E0'), ('R1', 'E1'), ('E1', 'E0'), ('R1', 'R0')]


def read(path):
    return json.loads(Path(path).read_bytes())


def reconcile(tables, initial_cash, members):
    values, flows, fees = defaultdict(dict), defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for row in tables['positions']:
        values[row['date']][row['instrument_id']] = row['market_value']
    for row in tables['fills']:
        day, sid = row['date'], row['instrument_id']
        flows[day][sid] += (row['notional'] if row['side'] == 'SELL' else -row['notional']) - row['fees']
        fees[day][sid] += row['fees']
    for row in tables['cash_events']:
        if row['event'] == 'DIVIDEND_RECEIVABLE':
            flows[row['date']][row['instrument_id']] += row['amount']
        if row['event'].startswith('LIQUIDATION'):
            raise ValueError('Liquidation attribution requires explicit rights accounting; never silently ignored')
    prior, prior_nav, max_error = {}, initial_cash, 0.
    daily, annual = [], defaultdict(lambda: defaultdict(float))
    for row in tables['nav']:
        day = row['date']
        current = values[day]
        pnl = {sid: current.get(sid, 0.) - prior.get(sid, 0.) + flows[day].get(sid, 0.) for sid in members}
        error = abs(sum(pnl.values()) - row['nav'] + prior_nav)
        max_error = max(max_error, error)
        if error > 1e-6:
            raise ValueError('Attribution fails daily account reconciliation: ' + day)
        for sid, amount in pnl.items():
            annual[day[:4]][sid] += amount
        daily.append(dict(date=day, **pnl))
        prior, prior_nav = current, row['nav']
    return daily, annual, fees, max_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admitted', type=Path, required=True)
    args = parser.parse_args()
    registry, paths = read(REPORT / 'EXPERIMENT_REGISTRY.json'), read(REPORT / 'ACCOUNT_PATHS.json')
    if {r['trial_id'] for r in paths} != {r['trial_id'] for r in registry['trials']} or len(paths) != 32:
        raise ValueError('All32 paths must be explicitly accounted for')
    if any(r['status'] != 'COMPLETED' for r in paths):
        raise ValueError('Do not summarize failed paths as zero returns')
    members = read(REPORT / 'COHORT_SELECTION.json')['selected_instruments']
    returns, tables_by_key, metrics, years, annual_accounts, daily_returns = {}, {}, [], [], [], []
    product_returns, product_cash_pnl = {}, {}
    monthly_targets = []
    for run in paths:
        path = ROOT / run['artifact_directory']
        for name, expected in run['exported_tables'].items():
            if hashlib.sha256((path / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Changed account artifact: ' + str(path / name))
        tables = {name: read(path / (name + '.json')) for name in
                  ('nav', 'positions', 'fills', 'cash_events', 'orders', 'rejected_orders', 'decisions', 'order_events', 'exposure')}
        nav = pd.DataFrame(tables['nav']).set_index('date')
        ret = nav.nav.astype(float) / nav.nav.astype(float).shift(1).fillna(run['initial_cash']) - 1
        key = (run['period'], run['path'], run['variant'])
        returns[key], tables_by_key[key] = ret, tables
        ident = {k: run[k] for k in ('trial_id', 'period', 'variant', 'path', 'run_id')}
        daily, annual, fees, max_error = reconcile(tables, run['initial_cash'], members)
        cash_pnl = pd.DataFrame(daily).set_index('date')[members]
        product_cash_pnl[key] = cash_pnl
        product_returns[key] = cash_pnl.div(nav.nav.shift(1).fillna(run['initial_cash']), axis=0)
        if not np.allclose(product_returns[key].sum(axis=1), ret, atol=1e-12, rtol=0):
            raise ValueError('Product return contributions do not reconcile to daily account returns')
        total_fees = sum(f['fees'] for f in tables['fills'])
        slippage = sum(f['slippage_cost'] for f in tables['fills'])
        m = dict(ident, **run['metrics'], final_nav_cny=float(nav.nav.iloc[-1]),
                 transaction_fees_cny=total_fees, embedded_slippage_cny=slippage,
                 gross_traded_notional_cny=sum(f['notional'] for f in tables['fills']),
                 traded_notional_over_mean_nav=sum(f['notional'] for f in tables['fills']) / float(nav.nav.mean()),
                 mean_cash_weight=float((nav.cash_total / nav.nav).mean()),
                 order_count=len(tables['orders']), fill_count=len(tables['fills']),
                 rejected_order_count=len(tables['rejected_orders']),
                 holding_sessions=len({p['date'] for p in tables['positions'] if p['quantity'] > 0}),
                 capacity_truncated_attempts=sum(e.get('event') == 'DAILY_CAPACITY'
                     and e.get('capacity_quantity', 0) < e.get('quantity_requested', 0)
                     for e in tables['order_events']),
                 passive_instrument_breach_sessions=len({e['date'] for e in tables['exposure']
                     if e['scope'] == 'INSTRUMENT' and e['breach']}),
                 passive_gross_breach_sessions=len({e['date'] for e in tables['exposure']
                     if e['scope'] == 'GROSS' and e['breach']}),
                 first_date=nav.index[0], last_date=nav.index[-1],
                 daily_attribution_max_error_cny=max_error)
        metrics.append(m)
        for day, value in ret.items():
            daily_returns.append(dict(ident, date=day, net_daily_return=float(value), nav_cny=float(nav.loc[day, 'nav'])))
        prior_nav = run['initial_cash']
        for year, group in nav.groupby(nav.index.str[:4]):
            actual = float(group.nav.iloc[-1]) - prior_nav
            annual_return = float(group.nav.iloc[-1]) / prior_nav - 1
            attributed = sum(annual[year].values())
            annual_accounts.append(dict(ident, year=year, net_pnl_cny=actual,
                                        annual_return=annual_return,
                                        product_pnl_cny=attributed, error_cny=attributed-actual))
            if abs(attributed - actual) > 1e-6:
                raise ValueError('Annual account reconciliation failed')
            prior_nav = float(group.nav.iloc[-1])
            for sid in members:
                years.append(dict(ident, year=year, instrument_id=sid, net_pnl_cny=annual[year][sid],
                                  fees_cny=sum(v.get(sid, 0.) for d, v in fees.items() if d.startswith(year))))
        for d in tables['decisions']:
            monthly_targets.append(dict(ident, anchor_date=d['diagnostics']['signal_anchor_date'],
                                        decision_date=d['decision_date'], execution_date=d['execution_date'],
                                        status=d['status'], eligible_count=d['diagnostics']['eligible_count'],
                                        eligible=d['diagnostics']['eligible'], trend=d['diagnostics']['trend'],
                                        weights=d['weights']))
    paired, differences, paired_months, paired_products = [], [], [], []
    for period in ('development', 'validation'):
        for pressure in ('base', 'cost_2x', 'cost_3x', 'delay_1_session'):
            series = {v: returns[(period, pressure, v)] for v in ('E0', 'R0', 'E1', 'R1')}
            if any(not s.index.equals(series['E0'].index) for s in series.values()):
                raise ValueError('Full calendar pairing is mandatory')
            comparisons = [(a + '-' + b, series[a] - series[b], a, b) for a, b in PAIRS]
            comparisons.append(('R1-R0-E1+E0', series['R1']-series['R0']-series['E1']+series['E0'], None, None))
            for label, delta, a, b in comparisons:
                item = dict(period=period, path=pressure, pair=label, n_dates=len(delta),
                            mean_daily_net_increment=float(delta.mean()),
                            signed_annual_fixed_cost_capacity_cny=float(delta.mean()*252*100000),
                            annual_incremental_cost=None, economic_status='BLOCKED_HURDLE',
                            nonzero_daily_differences=int((delta.abs()>1e-15).sum()))
                if pressure == 'base':
                    zero = delta * 0
                    item['descriptive_intervals'] = [paired_inference(delta, zero,
                        annual_incremental_cost=None, primary_capital=100000,
                        block_length=block, repetitions=5000, seed=20261114) for block in (60,20,120)]
                paired.append(item)
                for month, values in delta.groupby(delta.index.str[:7]):
                    paired_months.append(dict(period=period,path=pressure,pair=label,month=month,
                                              sum_daily_return_difference=float(values.sum()),
                                              mean_daily_return_difference=float(values.mean()),
                                              nonzero_days=int((values.abs()>1e-15).sum())))
                if a is not None:
                    product_delta = product_returns[(period,pressure,a)] - product_returns[(period,pressure,b)]
                    cash_delta = product_cash_pnl[(period,pressure,a)] - product_cash_pnl[(period,pressure,b)]
                    if not np.allclose(product_delta.sum(axis=1), delta, atol=1e-12, rtol=0):
                        raise ValueError('Paired product contributions fail full-calendar reconciliation')
                    for granularity, width in (('year', 4), ('month', 7)):
                        for bucket, group in product_delta.groupby(product_delta.index.str[:width]):
                            for sid in members:
                                paired_products.append(dict(period=period,path=pressure,pair=label,
                                    granularity=granularity,bucket=bucket,instrument_id=sid,
                                    sum_paired_daily_return_contribution=float(group[sid].sum()),
                                    difference_in_cash_pnl_cny=float(cash_delta.loc[group.index,sid].sum()),
                                    interpretation='Return contributions use each account prior NAV; cash PnL difference is a separate quantity'))
                    ta, tb = tables_by_key[(period,pressure,a)], tables_by_key[(period,pressure,b)]
                    da = {r['execution_date']: r for r in ta['decisions']}
                    db = {r['execution_date']: r for r in tb['decisions']}
                    if set(da) != set(db): raise ValueError('Decision calendars differ')
                    pa = {(r['date'],r['instrument_id']):r['quantity'] for r in ta['positions']}
                    pb = {(r['date'],r['instrument_id']):r['quantity'] for r in tb['positions']}
                    differences.append(dict(period=period,path=pressure,pair=label,monthly_decisions=len(da),
                        selection_set_difference=sum(set(da[d]['weights']) != set(db[d]['weights']) for d in da),
                        target_vector_difference=sum(da[d]['weights'] != db[d]['weights'] for d in da),
                        actual_position_day_difference=len({k[0] for k in set(pa)|set(pb) if pa.get(k,0)!=pb.get(k,0)}),
                        actual_product_day_difference=sum(pa.get(k,0)!=pb.get(k,0) for k in set(pa)|set(pb))))
    for name, rows in [('account_metrics',metrics),('annual_product_pnl',years),
                       ('annual_account_reconciliation',annual_accounts),('daily_account_returns',daily_returns),
                       ('paired_month_contributions',paired_months),('target_and_holdings_differences',differences),
                       ('paired_product_contributions',paired_products)]:
        pd.DataFrame(rows).to_csv(REPORT / (name+'.csv'),index=False,encoding='utf-8',lineterminator='\n')
    write_json(REPORT/'PAIRED_EVALUATION.json',paired)
    write_json(REPORT/'MONTHLY_TARGETS.json',monthly_targets)
    context = []
    for period in ('development', 'validation'):
        data = load_dataset(args.admitted / period)
        first = '2020-01-01' if period == 'development' else '2022-01-01'
        market = data.benchmark.sort_values(['date', 'available_at']).drop_duplicates('date', keep='last')
        prior = float(market.loc[market.date.lt(first), 'total_return_index'].iloc[-1])
        initial = prior
        for row in market.loc[market.date.ge(first)].itertuples():
            context.append(dict(period=period, date=row.date,
                hs300_total_return=float(row.total_return_index / prior - 1),
                hs300_tr_normalized=float(100000 * row.total_return_index / initial),
                cash_normalized=100000, purpose='NONTRADED_BACKGROUND_ONLY'))
            prior = row.total_return_index
    pd.DataFrame(context).to_csv(REPORT/'market_context.csv', index=False, encoding='utf-8', lineterminator='\n')
    write_json(REPORT/'RESULTS_SUMMARY.json',dict(
        scope=registry['registry_version'],actual_accounts=32,failed=0,not_run=0,
        conclusion='LIMITED_IDENTIFICATION' if all(not d['weights'] for d in monthly_targets) else 'INCONCLUSIVE',
        primary=[r for r in paired if r['period']=='validation' and r['path']=='base' and r['pair']=='R0-E0'][0],
        total_fills=sum(m['fill_count'] for m in metrics),total_orders=sum(m['order_count'] for m in metrics),
        total_account_sessions=sum(m['n_sessions'] for m in metrics),
        annual_product_rows=len(years),annual_account_rows=len(annual_accounts),
        max_daily_attribution_error_cny=max(m['daily_attribution_max_error_cny'] for m in metrics),
        unknown_fixed_cost=None,economic_confirmation='BLOCKED_HURDLE',
        interpretation='Historical rule-constrained simulation, not realized profit or full-market inference',
        no_new_significance_grid=True,descriptive_intervals_only_base_paths=True,
        concentration='UNDEFINED_NO_NONZERO_CONTRIBUTIONS' if all(r['net_pnl_cny']==0 for r in years) else 'SEE_ANNUAL_AND_MONTHLY_TABLES'))
    print('Evaluated32 preserved accounts; full-calendar paired descriptions; no fixed-fee imputation')


if __name__ == '__main__':
    main()
