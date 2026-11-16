"""Recompute utilities and registered intervals from independent ledgers."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import json
import csv
import ast
import math
from pathlib import Path
import numpy as np
from independent_accounts import ROOT, LEDGERS, D, read, sha, close
from independent_statistics import intervals, concentration


def returns(ledger):
    prior=D(100000); result=[]
    for row in ledger:
        value=D(row['nav'])
        result.append(value/prior-1)
        prior=value
    return result


def utilities(values):
    return [r-D('2.5')*r*r for r in values]


def mean(values):return sum(values)/len(values)


def metric_check(record,ledger,rs):
    navs=[D(row['nav']) for row in ledger]
    peak=D(100000); drawdowns=[]; longest=0; duration=0
    for nav in navs:
        peak=max(peak,nav); dd=nav/peak-1;drawdowns.append(dd)
        duration=duration+1 if dd < D('-1e-12') else 0;longest=max(duration,longest)
    span=(date.fromisoformat(ledger[-1]['date'])-date.fromisoformat(ledger[0]['date'])).days+1
    vol=D(str(np.std([float(r) for r in rs],ddof=1)*np.sqrt(252)))
    expected=dict(total_return=navs[-1]/100000-1,max_drawdown=min(drawdowns),
        cagr=D(str(float(navs[-1]/100000)**(365.25/span)-1)),annual_volatility=vol,
        sharpe_zero_cash=mean(rs)*252/vol,worst_day=min(rs))
    for key,value in expected.items():close(record['metrics'][key],value,key,D('2e-11'))
    assert record['metrics']['n_sessions']==len(rs)
    assert record['metrics']['max_drawdown_duration_sessions']==longest
    count=math.ceil(.05*len(rs))
    rolling=[float(np.std([float(r) for r in rs[i-59:i+1]],ddof=1)*np.sqrt(252)) for i in range(59,len(rs))]
    fills=read(Path(record['private_artifact_directory'])/'fills.json')
    return dict(trial_id=record['trial_id'],sessions=len(rs),final_nav=str(navs[-1]),
        mean_utility_score=str(mean(utilities(rs))),total_return=str(expected['total_return']),
        worst5pct_count=count,worst5pct_mean=str(mean(sorted(rs)[:count])),
        rolling60_count=len(rolling),rolling60_above10pct=sum(v>.1 for v in rolling)/len(rolling),
        rolling60_quantiles={str(q):float(np.quantile(rolling,q)) for q in (0,.25,.5,.75,1)},
        mean_cash_weight=str(mean([D(r['cash'])/D(r['nav']) for r in ledger])),
        transaction_fees_cny=str(sum((f['fees'] for f in fills),D(0))),
        embedded_slippage_cny=str(sum((f['slippage_cost'] for f in fills),D(0))),
        traded_notional_over_mean_nav=str(sum((f['notional'] for f in fills),D(0))/mean(navs)),
        ledger_sha256=sha(LEDGERS/(record['trial_id']+'.json')))


def product_attribution(record,ledger):
    """Daily source-audited positions and cash flows; receivables recognized ex-date."""
    private=Path(record['private_artifact_directory'])
    flows=defaultdict(lambda:defaultdict(lambda:D(0)))
    for fill in read(private/'fills.json'):
        cash=(fill['notional'] if fill['side']=='SELL' else -fill['notional'])-fill['fees']
        flows[fill['date']][fill['instrument_id']]+=cash
    for event in read(private/'cash_events.json'):
        if event['event']=='DIVIDEND_RECEIVABLE':flows[event['date']][event['instrument_id']]+=event['amount']
    positions=defaultdict(dict)
    for p in read(private/'positions.json'):positions[p['date']][p['instrument_id']]=p['market_value']
    prior_values={};prior_nav=D(100000);buckets=defaultdict(lambda:[D(0),D(0)]);checks=0
    for row in ledger:
        day=row['date'];current=positions[day]
        values={sid:current.get(sid,D(0))-prior_values.get(sid,D(0))+flows[day].get(sid,D(0))
                for sid in set(current)|set(prior_values)|set(flows[day])}
        close(sum(values.values()),D(row['nav'])-prior_nav,'per-product daily source cash PnL',D('1e-6'))
        for sid,pnl in values.items():
            for width in (4,7):
                buckets[day[:width],sid][0]+=pnl
                buckets[day[:width],sid][1]+=pnl/prior_nav
        checks+=1;prior_values=current;prior_nav=D(row['nav'])
    return buckets,checks


def main():
    records=read(ROOT/'reports/m9_risk/ACCOUNT_PATHS.json')
    if isinstance(records,dict):records=records['accounts']
    assert len(records)==24
    full=read(ROOT/'reports/m9_review/ALL_ACCOUNT_INDEPENDENT_REVIEW.json')
    assert full['decision']=='PASS_DATA_AND_ACCOUNTING'
    evaluation=read(ROOT/'reports/m9_risk/UTILITY_EVALUATION.json')
    assert evaluation['gamma']==5 and evaluation['unit']=='UTILITY_SCORE_PER_DAY'
    series={};ledgers={};account_checks=[];products={};product_daily=0
    for record in records:
        key=(record['period'],record['path'],record['variant'])
        ledger=read(LEDGERS/(record['trial_id']+'.json'))
        rs=returns(ledger)
        series[key]=rs;ledgers[key]=ledger
        account_checks.append(metric_check(record,ledger,rs))
        products[key],count=product_attribution(record,ledger);product_daily+=count
    checks=[];monthly=[]
    for entry in evaluation['pairs']:
        period,pressure=entry['period'],entry['path']
        assert entry['pair']=='VE-CE'
        keys=[(period,pressure,v) for v in ('VE','CE','VR')]
        dates=[row['date'] for row in ledgers[keys[0]]]
        assert all([row['date'] for row in ledgers[k]]==dates for k in keys)
        rs={v:series[period,pressure,v] for v in ('VE','CE','VR')}
        us={v:utilities(values) for v,values in rs.items()}
        du=[a-b for a,b in zip(us['VE'],us['CE'])]
        dr=[a-b for a,b in zip(rs['VE'],rs['CE'])]
        close(entry['mean_utility_difference'],mean(du),'utility difference',D('1e-12'))
        close(entry['annualized_utility_score_difference'],mean(du)*252,'annualized score not CAGR',D('1e-12'))
        close(entry['mean_net_return_difference'],mean(dr),'raw return difference',D('1e-12'))
        for variant in ('VE','CE','VR'):
            close(entry['absolute_mean_utility'][variant],mean(us[variant]),'absolute utility',D('1e-12'))
        assert entry['absolute_mean_utility']['cash']==0
        independent_intervals=[]
        if pressure=='base':
            for field,values,ci_field in [('utility_intervals',du,'utility_ci'),('net_return_intervals',dr,'ci95')]:
                observed=entry[field]
                assert [v['block_length'] for v in observed]==[60,20,120]
                for interval in observed:
                    assert interval['seed']==20261114 and interval['repetitions']==5000
                    expected=intervals(values,interval['block_length'])
                    close(interval['hac_se'],D(str(expected['hac_se'])),'HAC',D('1e-12'))
                    assert interval['hac_lag']==expected['hac_lag']
                    for a,e in zip(interval[ci_field],expected['ci95']):close(a,D(str(e)),'bootstrap CI',D('1e-12'))
                    if field=='utility_intervals':
                        assert 'mean_net_increment' not in interval
                        assert 'daily_hurdle' not in interval
                    else:
                        assert interval['annual_incremental_cost'] is None and interval['daily_hurdle'] is None
                        assert interval['p_net'] is None and interval['p_hac'] is None
                    independent_intervals.append(dict(measure='utility_score' if field=='utility_intervals' else 'net_daily_return',
                        block_length=interval['block_length'],**expected))
        else:
            assert not entry.get('utility_intervals') and not entry.get('net_return_intervals')
        sums=defaultdict(lambda:D(0))
        for day,value in zip(dates,du):sums[day[:7]]+=value
        monthly.append(dict(period=period,path=pressure,utility_month_concentration=concentration(sums),
                            monthly_utility_sums={k:str(v) for k,v in sums.items()}))
        checks.append(dict(period=period,path=pressure,mean_utility_difference=str(mean(du)),
            mean_net_return_difference=str(mean(dr)),intervals=independent_intervals))
    assert len(checks)==8 and sum(len(c['intervals']) for c in checks)==12
    primary=next(c for c in checks if (c['period'],c['path'])==('validation','base'))
    ci=next(v['ci95'] for v in primary['intervals'] if v['measure']=='utility_score' and v['block_length']==60)
    state='DESCRIPTIVE_UTILITY_SUPPORT' if ci[0]>0 else ('NOT_SUPPORTED_CURRENT_RISK_RULE' if ci[1]<=0 else 'INCONCLUSIVE')
    assert evaluation['primary_statistical_state']==state
    robust=all(D(c['mean_utility_difference'])>0 for c in checks if (c['period']=='development' and c['path']=='base')
               or (c['period']=='validation' and c['path']!='base'))
    assert evaluation['robustness_sign_check']==('ROBUSTNESS_SIGN_CHECK_PASSED' if robust else 'CROSS_PERIOD_OR_EXECUTION_SIGN_NOT_STABLE')
    assert evaluation['unknown_fixed_fee'] is None and evaluation['economic_confirmation']=='BLOCKED_HURDLE'
    for entry in evaluation['auxiliary']:
        key=entry['period'],entry['path']
        expected=mean([a-b for a,b in zip(series[key+('VR',)],series[key+('VE',)])])
        close(entry['mean_net_return_difference'],expected,'VR-VE descriptive mean',D('1e-12'))
        assert entry['inference']=='DESCRIPTIVE_ONLY_NO_AUXILIARY_CI'
    product_bucket_checks=0;monthly_checks=0;annual_checks=0
    with (ROOT/'reports/m9_risk/annual_product_pnl.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            key=row['period'],row['path'],row['variant']
            expected=products[key][row['year'],row['instrument_id']][0]
            close(row['net_pnl_cny'],expected,'annual product source cash PnL',D('1e-6'))
            product_bucket_checks+=1
    with (ROOT/'reports/m9_risk/paired_product_contributions.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            a,b=row['pair'].split('-');key=row['period'],row['path'];bucket=row['year'],row['instrument_id']
            x,y=products[key+(a,)][bucket],products[key+(b,)][bucket]
            close(row['cash_pnl_difference_cny'],x[0]-y[0],'paired cash product',D('1e-6'))
            close(row['sum_net_daily_return_contribution'],x[1]-y[1],'paired return product',D('1e-11'))
            assert row['utility_attribution'].startswith('NOT_ADDITIVE_BY_PRODUCT')
            product_bucket_checks+=1
    with (ROOT/'reports/m9_risk/paired_month_contributions.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            a,b=row['pair'].split('-');key=row['period'],row['path'];month=row['month']
            dates=[r['date'] for r in ledgers[key+(a,)]]
            xs,ys=series[key+(a,)],series[key+(b,)]
            dr=[x-y for day,x,y in zip(dates,xs,ys) if day.startswith(month)]
            du=[x-y for day,x,y in zip(dates,utilities(xs),utilities(ys)) if day.startswith(month)]
            close(row['sum_net_daily_return_difference'],sum(dr),'month return',D('1e-11'))
            close(row['sum_daily_utility_difference'],sum(du),'month utility',D('1e-11'))
            close(row['mean_daily_utility_difference'],mean(du),'month mean utility',D('1e-11'))
            assert int(row['n_dates'])==len(dr);monthly_checks+=1
    with (ROOT/'reports/m9_risk/annual_account_reconciliation.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            key=row['period'],row['path'],row['variant'];year=row['year']
            dates=[r['date'] for r in ledgers[key]]
            ys=[r for day,r in zip(dates,series[key]) if day.startswith(year)]
            compound=D(1)
            for r in ys:compound*=1+r
            close(row['total_return'],compound-1,'annual compound return',D('1e-11'))
            close(row['mean_utility'],mean(utilities(ys)),'annual mean utility',D('1e-11'))
            close(row['annual_volatility'],D(str(np.std([float(r) for r in ys],ddof=1)*np.sqrt(252))),'annual risk',D('1e-11'))
            annual_checks+=1
    summaries={r['trial_id']:r for r in account_checks}
    with (ROOT/'reports/m9_risk/account_metrics.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            expected=summaries[row['trial_id']]
            close(row['mean_utility'],D(expected['mean_utility_score']),'absolute account utility',D('1e-12'))
            close(row['worst_five_percent_daily_mean'],D(expected['worst5pct_mean']),'empirical lower-tail mean',D('1e-12'))
            assert int(row['tail_sample_count'])==expected['worst5pct_count']
            assert int(row['rolling60_count'])==expected['rolling60_count']
            close(row['rolling60_above_10pct_fraction'],D(str(expected['rolling60_above10pct'])),'realized risk exceedance',D('1e-12'))
            for key,value in ast.literal_eval(row['rolling60_volatility_quantiles']).items():
                close(value,D(str(expected['rolling60_quantiles'][key])),'realized risk quantiles',D('1e-11'))
            for field in ('mean_cash_weight','transaction_fees_cny','embedded_slippage_cny','traded_notional_over_mean_nav'):
                close(row[field],D(expected[field]),field,D('1e-8'))
    divergences=read(ROOT/'reports/m9_risk/EXECUTION_DIVERGENCES.json')
    assert len(divergences)==18
    for row in divergences:
        key=row['period'],row['variant']
        base=ledgers[key[0],'base',key[1]];other=ledgers[key[0],row['path'],key[1]]
        differing=[(a,b) for a,b in zip(base,other) if abs(D(a['nav'])-D(b['nav']))>D('1e-9')]
        positions=[(a,b) for a,b in zip(base,other) if a['positions']!=b['positions']]
        assert row['first_nav_divergence']==(differing[0][0]['date'] if differing else None)
        assert row['first_position_divergence']==(positions[0][0]['date'] if positions else None)
        assert row['unchanged_anchor_targets'] is True
        if differing:
            close(row['first_day_nav_difference_cny'],D(differing[0][1]['nav'])-D(differing[0][0]['nav']),'first divergence',D('1e-6'))
    out=dict(decision='PASS_INDEPENDENT_STATISTICS',author_role='INDEPENDENT_REVIEWER',
        reviewer_code_sha256={name:sha(Path(__file__).parent/name) for name in
            ('independent_accounts.py','independent_statistics.py','review_statistics.py')},
        account_metrics=account_checks,paired_checks=checks,monthly_concentration=monthly,
        primary_statistical_state=state,robustness_all_four_points_positive=robust,
        independent_daily_product_accounting_checks=product_daily,utility_evaluation_sha256=sha(ROOT/'reports/m9_risk/UTILITY_EVALUATION.json'),
        annual_and_paired_product_buckets=product_bucket_checks,paired_month_checks=monthly_checks,annual_account_checks=annual_checks,
        first_execution_divergence_checks=len(divergences),
        all_account_review_sha256=sha(ROOT/'reports/m9_review/ALL_ACCOUNT_INDEPENDENT_REVIEW.json'),
        limits=['12 registered marginal CIs only; no stress significance grid.',
                'Utility score is not raw return, certainty equivalent, Alpha, or currency fee capacity.',
                'Positive VE-CE utility difference does not imply positive absolute utility or positive compound return.',
                'Unknown annual incremental fixed cost remains null.'])
    (ROOT/'reports/m9_review/INDEPENDENT_STATISTICS.json').write_text(json.dumps(out,indent=2)+'\n')
    print(out['decision'],len(account_checks),len(checks),12,state)


if __name__=='__main__':main()
