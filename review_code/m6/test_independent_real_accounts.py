"""Separate Decimal case expectations; never read author expected/fill predictions."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import pandas as pd
import pytest
from quant_research.execution import run_backtest

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/m6_stock_execution'


def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def load_case(name):
    return json.loads((OUT/(name+'_inputs.json')).read_text('utf-8'))


def assert_kangmei(snapshot,result):
    bars={r['date']:r for r in snapshot['bars']}
    assert snapshot['actions']==[]
    # Instructions fixed before collecting this price window, never actual fills.
    assert [(r['execution_date'],r['fixed_quantities']['sh.600518']) for r in snapshot['decisions']]==[
        ('2019-05-13',100),('2019-05-14',200),('2019-05-21',0)]
    assert money(bars['2019-05-13']['open'])==Decimal('5.78')
    assert money(bars['2019-05-14']['open'])==Decimal('5.60')
    first=Decimal(100)*Decimal('5.78');second=Decimal(100)*Decimal('5.60')
    first_fee=Decimal('5')+money(first*Decimal('.00002'))
    second_fee=Decimal('5')+money(second*Decimal('.00002'))
    assert first_fee==second_fee==Decimal('5.01')
    positions=result['positions']
    assert len(result['nav'])==41
    for _,row in result['nav'].iterrows():
        day=row['date'];quantity=0;cash=Decimal('10000000');sellable=0
        if day>='2019-05-13':quantity+=100;cash-=first+first_fee
        if day>='2019-05-14':quantity+=100;cash-=second+second_fee;sellable=100
        if day>='2019-05-15':sellable=200
        holding=Decimal(quantity)*Decimal(str(bars[day]['close']))
        for field,expected in [('cash_total',cash),('cash_available',cash),('cash_reserved',Decimal(0)),
                               ('holdings_value',holding),('nav',cash+holding),
                               ('hypothetical_liquidation_nav',cash+holding),('receivables',Decimal(0)),
                               ('dividend_tax_payable',Decimal(0)),('dividend_tax_paid',Decimal(0))]:
            assert money(row[field])==money(expected),(day,field)
        daily=positions.loc[positions.date.eq(day)]
        assert daily.quantity.sum()==quantity
        assert daily.sellable_quantity.sum()==sellable
    fills=result['fills']
    assert fills['quantity'].tolist()==[100,100]
    assert fills['date'].tolist()==['2019-05-13','2019-05-14']
    assert fills['side'].tolist()==['BUY','BUY']
    assert fills['stamp_duty'].tolist()==[0,0]
    assert fills['fees'].tolist()==[5.01,5.01]
    rejects=result['rejected_orders']
    attempts=rejects.loc[rejects.reason.eq('OPEN_AT_ADVERSE_LIMIT')]
    assert attempts.date.tolist()==['2019-05-21','2019-05-22','2019-05-23','2019-05-24','2019-05-27']
    for day in attempts.date:
        assert money(bars[day]['open'])==money(bars[day]['lower_limit'])
    assert sum(rejects.reason.eq('SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS'))==1
    assert money(result['nav'].iloc[-1]['cash_total'])==Decimal('9998851.98')
    assert money(result['nav'].iloc[-1]['nav'])==Decimal('9999689.98')


def test_saved_real_kangmei_all41days_against_separate_hand_oracle():
    tables={key:pd.read_csv(OUT/('kangmei_st_'+key+'.csv'))
            for key in ['nav','positions','fills','rejected_orders']}
    assert_kangmei(load_case('kangmei_st'),tables)


@pytest.mark.archived_source
def test_replay_real_manifest_through_main_engine_and_hand_oracle():
    snap=load_case('kangmei_st')
    missing=[r['path'] for r in snap['manifest']['source_artifacts'] if not Path(r['path']).exists()]
    if missing:pytest.skip('Archived originals absent; real-manifest replay not counted as PASS')
    dataset={**snap,**{key:pd.DataFrame(snap[key]) for key in ['instruments','bars','actions','tax_rules']}}
    result=run_backtest(dataset,snap['decisions'],10000000,slippage_multiplier=0,engineering_replay=True)
    assert_kangmei(snap,result)


@pytest.mark.parametrize('name,count',[('moutai_ordinary',34),('moutai_special',35)])
def test_missing_transfer_rule_cases_remain_zero_position_rejection_ledgers(name,count):
    results=json.loads((OUT/'results.json').read_text('utf-8'))
    case=next(r for r in results['cases'] if r['case']==name)
    assert case['status']=='BLOCKED' and case['has_actual_event_position'] is False
    assert case['missing_components']==['transfer_fee'] and case['actual_fill_count']==0
    nav=pd.read_csv(OUT/(name+'_nav.csv'));positions=pd.read_csv(OUT/(name+'_positions.csv'))
    assert len(nav)==count and nav.nav.eq(10000000).all() and nav.cash_total.eq(10000000).all()
    assert nav.holdings_value.eq(0).all() and positions.quantity.eq(0).all()
