"""Fixed economic oracle; no selector is used to derive expected membership."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from quant_research.data import Dataset, REQUIRED, audit_dataset, synthetic_dataset
from quant_research.dependencies import representative_dependencies
from quant_research.strategy import _prepare, _representatives, generate_targets
from quant_research.providers.universe import provisional_amount_representatives


def dependency_case():
    days = pd.bdate_range('2017-01-02', '2019-05-02').strftime('%Y-%m-%d').tolist()
    master, bars = [], []
    for code, family, amount in [('A','CSI300',200e6),('B','CSI300',100e6),('C','CSI500',80e6),('D','CSI1000',80e6)]:
        master.append(dict(instrument_id=code, asset_type='ETF', board='ETF', listed_on=days[0],
            delisted_on=None, available_at='2016-12-30T21:00:00+08:00', account_verified=True,
            benchmark_id=family, industry='BROAD_MARKET', lot_size=100, tick_size=.001, t_plus=1,
            revision_id=code+'_old', supersedes_id=None, strategy_universe='R1B',
            effective_from=days[0], effective_to=None))
        for day in days:
            bars.append(dict(date=day,instrument_id=code,open=2.,high=2.,low=2.,close=2.,volume=amount/2,
                amount=amount,upper_limit=2.2,lower_limit=1.8,suspended=False,
                available_at=day+'T16:00:00+08:00',revision_id=code+day,supersedes_id=None,
                total_return_index=100.,usage_scope='FULL_STRATEGY'))
    master.append(dict(master[0], revision_id='A_successor', supersedes_id='A_old',
        available_at='2017-12-29T21:00:00+08:00', effective_from='2018-01-01', effective_to='2019-01-01'))
    benchmark = [dict(date=d,total_return_index=100.,available_at=d+'T16:00:00+08:00',revision_id='BM'+d,supersedes_id=None) for d in days]
    manifest = deepcopy(synthetic_dataset().manifest)
    manifest.update(dataset_id='M5_DEPENDENCY_COUNTEREXAMPLE',coverage_start=days[0],coverage_end=days[-1],
                    tr_coverage_start=days[0])
    return Dataset(days,pd.DataFrame(master),pd.DataFrame(bars),pd.DataFrame(columns=REQUIRED['actions']),pd.DataFrame(benchmark),manifest)


def on_april_schedule(data):
    return next(r for r in representative_dependencies(data)['schedule'] if r['quarter_start']=='2019-04-01')


def provider_on_april(data):
    first=data.instruments.drop_duplicates('instrument_id')
    candidates=[dict(code=r.instrument_id,category=r.benchmark_id,documented_index_categories=[r.benchmark_id],
        documented_listing_dates=[r.listed_on],snapshot_dates=data.calendar) for r in first.itertuples()]
    histories={sid:[dict(date=r.date,amount=str(r.amount),suspended=r.suspended) for r in f.itertuples()]
        for sid,f in data.bars.groupby('instrument_id')}
    proof=provisional_amount_representatives(data.calendar,candidates,histories,data.instruments.to_dict('records'))
    return next(r for r in proof['schedule'] if r['quarter_start']=='2019-04-01')


def test_expired_successor_does_not_revive_old_amount_winner():
    data=dependency_case()
    # A's latest economic state expired Jan1. B is the ONLY live CSI300 member.
    expected=['B','C','D']
    assert on_april_schedule(data)['representatives']==expected
    assert _representatives(_prepare(data.instruments),_prepare(data.bars),data.calendar,data.calendar.index('2019-03-29'))==expected
    assert provider_on_april(data)['representatives']==expected
    assert set(expected)<=set(representative_dependencies(data)['required_full_history_instruments'])


def test_false_selection_only_declaration_is_rejected_before_cash_fallback():
    data=dependency_case()
    full=next(t for t in generate_targets(data,'R0') if t.decision_date=='2019-04-30')
    assert full.weights=={'B':1/3,'C':1/3,'D':1/3}
    data.bars.loc[data.bars.instrument_id.eq('B'),'usage_scope']='REPRESENTATIVE_SELECTION_ONLY'
    data.bars.loc[data.bars.instrument_id.eq('B'),'total_return_index']=np.nan
    # Even declaring the producer's own recomputed proof must not legitimize B's removal.
    data.manifest['representative_dependencies']=representative_dependencies(data)
    report=audit_dataset(data)
    assert not report['errors'],report
    assert any('selected representative lacks full TR/event coverage' in x and "'B'" in x for x in report['blockers']),report
    cut=next(t for t in generate_targets(data,'R0') if t.decision_date=='2019-04-30')
    assert cut.status=='BLOCKED_MOMENTUM_DATA' and cut.weights=={}


@pytest.mark.parametrize('case',['late_old_correction','future_transition','reverse_order'])
def test_economic_state_order_independent_of_publication_or_input_order(case):
    data=dependency_case()
    if case=='late_old_correction':
        row=dict(data.instruments.iloc[0],revision_id='A_old_fix',supersedes_id='A_old',revision_kind='CORRECTION',
                 available_at='2019-03-25T21:00:00+08:00')
        data.instruments=pd.concat([data.instruments,pd.DataFrame([row])],ignore_index=True)
    elif case=='future_transition':
        row=dict(data.instruments.iloc[1],revision_id='B_future',supersedes_id='B_old',revision_kind='TRANSITION',
                 strategy_universe='OUTSIDE',available_at='2019-03-25T21:00:00+08:00',effective_from='2019-04-02')
        data.instruments=pd.concat([data.instruments,pd.DataFrame([row])],ignore_index=True)
    else:
        data.instruments=data.instruments.iloc[::-1].reset_index(drop=True)
        data.bars=data.bars.iloc[::-1].reset_index(drop=True)
    assert on_april_schedule(data)['representatives']==['B','C','D']
    assert provider_on_april(data)['representatives']==['B','C','D']


def test_benchmark_source_clock_cannot_authorize_early_or_restore_predecessor():
    data=dependency_case()
    data.instruments.loc[data.instruments.instrument_id.eq('B'),'benchmark_source_available_at']='2019-04-02T21:00:00+08:00'
    assert on_april_schedule(data)['representatives']==['C','D']
    assert provider_on_april(data)['representatives']==['C','D']
    assert _representatives(_prepare(data.instruments),_prepare(data.bars),data.calendar,data.calendar.index('2019-03-29'))==['C','D']


def test_return_quality_does_not_choose_an_alternative_representative():
    data=dependency_case();data.bars.loc[data.bars.instrument_id.eq('B'),'total_return_index']=np.nan
    assert on_april_schedule(data)['representatives']==['B','C','D']
    assert provider_on_april(data)['representatives']==['B','C','D']
