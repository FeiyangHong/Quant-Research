"""Reviewer-owned hand-built cohort; invented prices are engineering only."""
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_research.cohort import cohort_dependencies, generate_cohort_targets
from quant_research.execution import run_backtest
from quant_research.strategy import StrategyBlockedError, generate_targets

IDS = ['sz.159936','sz.159938','sz.159939','sz.159940','sz.159944','sz.159945','sz.159946']
SCOPE = 'R1I_FIXED_COHORT_V1'


def fixture(n=3):
    days = pd.bdate_range('2014-01-02', '2016-02-03').strftime('%Y-%m-%d').tolist()
    masters, bars = [], []
    for number, sid in enumerate(IDS):
        masters.append(dict(instrument_id=sid, asset_type='ETF', board='ETF', listed_on=days[0],
                            delisted_on=None, available_at='2014-01-01T21:00:00+08:00',
                            account_verified=True,status='NORMAL',benchmark_id='ARTIFICIAL'+sid,
                            strategy_universe=SCOPE,lot_size=100,tick_size=.001,t_plus=1,
                            revision_id='original'+sid,supersedes_id=None))
        for i, day in enumerate(days):
            bars.append(dict(date=day,instrument_id=sid,open=2.,close=2.,high=2.1,low=1.9,
                             volume=20000000,amount=40000000. if number<n else 10000000.,
                             upper_limit=2.2,lower_limit=1.8,suspended=False,
                             total_return_index=100*np.exp(-.0001*(7-number)*i),
                             available_at=day+'T16:00:00+08:00'))
    benchmark=pd.DataFrame(dict(date=days,total_return_index=100.+np.arange(len(days)),
                               available_at=[d+'T16:00:00+08:00' for d in days]))
    return SimpleNamespace(calendar=days,instruments=pd.DataFrame(masters),bars=pd.DataFrame(bars),
                           benchmark=benchmark,actions=pd.DataFrame(),
                           manifest=dict(research_scope=SCOPE,synthetic=True))


def active(data, variant='R0', delay=1):
    return [d for d in generate_cohort_targets(data,variant,delay)
            if d.diagnostics['signal_anchor_date']>='2016-01-29']


def test_legal_anchor_and_negative_relative_momentum_are_hand_determined():
    data=fixture(4)
    before=generate_cohort_targets(data,'R0')
    assert all(d.weights=={} for d in before if d.diagnostics['signal_anchor_date']<'2016-01-29')
    first=active(data)[0]
    assert first.decision_date=='2016-02-01' and first.execution_date=='2016-02-02'
    assert list(first.weights)==IDS[1:4]
    assert all(value<0 for value in first.diagnostics['momentum'].values())
    assert first.diagnostics['momentum'][IDS[0]]==pytest.approx(-.0007*105)
    delayed=active(data,delay=2)[0]
    assert delayed.execution_date=='2016-02-03' and delayed.weights==first.weights
    assert delayed.diagnostics['momentum']==first.diagnostics['momentum']
    with pytest.raises(StrategyBlockedError):generate_targets(data,universe='R1I')


@pytest.mark.parametrize('cost',[1,2,3])
def test_n3_canonical_orders_and_full_first_account_match_decimal_input_oracle(cost):
    data=fixture(3)
    target_e=generate_cohort_targets(data,'E0');target_r=generate_cohort_targets(data,'R0')
    assert target_e[-1].weights==target_r[-1].weights==dict.fromkeys(IDS[:3],1/3)
    assert list(target_r[-1].weights)==IDS[:3]
    assert target_e[-1].ranks==target_r[-1].ranks
    # Quantity comes from frozen100000 /3 /2 and100-unit lot, never actual fills.
    quantity=16600
    price=(Decimal('2')*(1+Decimal('.0003')*cost)/Decimal('.001')).to_integral_value(rounding=ROUND_CEILING)*Decimal('.001')
    notional=(quantity*price).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    fee=(max(Decimal('5'),notional*Decimal('.0003'))*cost).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    cash=Decimal('100000')-3*(notional+fee)
    holding=Decimal(3*quantity)*2
    a=run_backtest(data,target_e,100000,cost_multiplier=cost,slippage_multiplier=cost,start_date='2016-01-01')
    b=run_backtest(data,target_r,100000,cost_multiplier=cost,slippage_multiplier=cost,start_date='2016-01-01')
    for name in ['orders','fills','nav','positions']:pd.testing.assert_frame_equal(a[name],b[name])
    assert a['fills'].instrument_id.tolist()==IDS[:3]
    assert a['fills'].quantity.tolist()==[quantity]*3
    assert a['fills'].price.tolist()==[float(price)]*3
    assert a['fills'].commission.tolist()==[float(fee)]*3
    for row in a['nav'].to_dict('records'):
        before=row['date']<'2016-02-02'
        assert row['cash_total']==pytest.approx(float(Decimal(100000) if before else cash),abs=1e-7)
        assert row['holdings_value']==pytest.approx(0 if before else float(holding),abs=1e-7)
        assert row['nav']==pytest.approx(float(Decimal(100000) if before else cash+holding),abs=1e-7)


def test_n2_cash_dependency_is_proved_but_missing_amount_is_not_cash():
    data=fixture(2)
    data.bars['total_return_index']=np.nan
    proof=cohort_dependencies(data)
    assert proof['required_full_history_instruments']==[]
    assert proof['no_ranking_or_holding_dependency']==IDS
    for variant in ['E0','R0','E1','R1']:
        assert all(d.weights=={} for d in generate_cohort_targets(data,variant))
    data.bars=data.bars.loc[~(data.bars.instrument_id.eq(IDS[-1]) & data.bars.date.eq('2016-01-28'))]
    with pytest.raises(StrategyBlockedError):generate_cohort_targets(data)


@pytest.mark.parametrize('field',['TR','TR_clock','state','permission'])
def test_missing_required_signal_or_identity_never_turns_into_cash(field):
    data=fixture(4)
    if field=='TR':data.bars.loc[data.bars.instrument_id.eq(IDS[0]),'total_return_index']=np.nan
    elif field=='TR_clock':
        data.bars['total_return_available_at']=data.bars.available_at
        data.bars.loc[data.bars.instrument_id.eq(IDS[0]),'total_return_available_at']='2016-02-02T21:00:00+08:00'
    elif field=='state':data.instruments.loc[0,'status']=None
    else:
        data.instruments['account_verified']=data.instruments.account_verified.astype(object)
        data.instruments.loc[0,'account_verified']=None
    with pytest.raises(StrategyBlockedError):generate_cohort_targets(data,'E0')


def test_release_updates_size_orders_without_changing_month_end_signal():
    data=fixture(4); expected=active(data,'R1')[0]
    mask=data.bars.date.eq('2016-02-01')
    data.bars.loc[mask,'close']=7.
    data.bars.loc[mask,'total_return_index']=1e20
    data.benchmark.loc[data.benchmark.date.eq('2016-02-01'),'total_return_index']=1e20
    actual=active(data,'R1')[0]
    assert actual.weights==expected.weights
    assert actual.diagnostics['momentum']==expected.diagnostics['momentum']
    assert actual.diagnostics['trend']==expected.diagnostics['trend']
    assert set(actual.reference_prices.values())=={7.}


def test_strict_trend_and_effective_identity_change_preserve_clock():
    data=fixture(4)
    data.benchmark['total_return_index']=100.
    assert active(data,'R1')[0].weights=={}
    row=data.instruments.iloc[0].to_dict()
    row.update(status='ECONOMIC_IDENTITY_CHANGED',effective_from='2016-02-02',
               available_at='2016-01-25T21:00:00+08:00',revision_id='transition',
               supersedes_id=row['revision_id'],revision_kind='TRANSITION')
    data.instruments=pd.concat([data.instruments,pd.DataFrame([row])],ignore_index=True)
    assert IDS[0] in active(data,'E0')[0].weights
