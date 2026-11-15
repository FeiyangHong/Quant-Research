"""Hand-decided R1I cases, wholly synthetic, never real-source admission."""
from copy import deepcopy
import pandas as pd
import pytest

from quant_research.r1i import quarter_representatives, monthly_pool, rule_weights, identification_gate
from quant_research.strategy import StrategyBlockedError
from quant_research.temporal import master_record, TemporalStateError

AT='2021-05-31T21:00:00+08:00'


def fixture():
    calendar=pd.bdate_range('2019-01-01','2021-06-30').strftime('%Y-%m-%d').tolist()
    # A beats B within IX_A; A then beats C within TECH; D/E/F get other slots.
    specs=[('A','IX_A','TECH',200),('B','IX_A','TECH',180),('C','IX_C','TECH',190),
           ('D','IX_D','FINANCE',150),('E','IX_E','HEALTH',120),('F','IX_F','UTILITY',100)]
    masters=[dict(instrument_id=sid,asset_type='ETF',listed_on='2018-01-01',delisted_on=None,
              available_at='2018-01-01T00:00:00+08:00',effective_from='2018-01-01',effective_to=None,
              r1i_scope_status='INCLUDED',index_identity=index,benchmark_id=index,
              benchmark_source_available_at='2018-01-01T00:00:00+08:00',
              csi_level1_id=industry,csi_taxonomy_version='CSI_SYNTHETIC_V1',
              mapping_available_at='2018-01-01T00:00:00+08:00') for sid,index,industry,_ in specs]
    bars=[dict(instrument_id=sid,date=day,amount=amount*1e6,available_at=day+'T16:00:00+08:00')
          for sid,_,_,amount in specs for day in calendar]
    return pd.DataFrame(masters),pd.DataFrame(bars),calendar


def select(master,bars,calendar):
    return quarter_representatives(master,bars,calendar,'2021-04-01')


def qualify():
    return {sid:dict(qualified=True,reason='SYNTHETIC_ELIGIBLE') for sid in 'ADEF'}


def transition(master,changes=None,**overrides):
    updates=[]
    for row in master.iloc[:6].to_dict('records'):
        row.update(effective_from='2021-05-01',available_at='2021-04-20T20:00:00+08:00',
                   mapping_available_at='2021-04-20T20:00:00+08:00',csi_taxonomy_version='CSI_SYNTHETIC_V2')
        if changes and row['instrument_id'] in changes:row.update(changes[row['instrument_id']])
        row.update(overrides)
        updates.append(row)
    return pd.concat([master,pd.DataFrame(updates)],ignore_index=True)


def test_two_stage_selection_and_input_order_do_not_follow_return_quality():
    master,bars,calendar=fixture()
    reps=select(master,bars,calendar)
    assert [r['instrument_id'] for r in reps]==list('ADEF')
    assert reps[0]['mean_amount60']==200e6
    assert tuple(reps[0]['quarter_sort_key'])==(-200e6,'2018-01-01','A')
    # TR is deliberately missing for the winner and present for other funds.
    bars['total_return_index']=1.
    bars.loc[bars.instrument_id.eq('A'),'total_return_index']=None
    assert select(master.iloc[::-1],bars.iloc[::-1],calendar)==reps


def test_missing_losing_competitor_amount_blocks_instead_of_dropping_it():
    master,bars,calendar=fixture()
    bars=bars.loc[~(bars.instrument_id.eq('B') & bars.date.eq('2021-03-31'))]
    with pytest.raises(StrategyBlockedError,match='competitor amounts'):
        select(master,bars,calendar)


def test_quarter_tie_uses_listing_then_security_id():
    master,bars,calendar=fixture()
    bars.loc[bars.instrument_id.isin(['A','B','C']),'amount']=200e6
    master.loc[master.instrument_id.eq('B'),'listed_on']='2017-12-01'
    reps=select(master,bars,calendar)
    assert [r['instrument_id'] for r in reps]==list('BDEF')
    master.loc[master.instrument_id.eq('B'),'listed_on']='2018-01-01'
    assert [r['instrument_id'] for r in select(master,bars,calendar)]==list('ADEF')


def test_merger_uses_frozen_key_then_qualification_without_replacement():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'csi_level1_id':'FINANCE'}})
    eligibility=qualify();eligibility['A']=dict(qualified=False,reason='LOW_LIQUIDITY')
    result=monthly_pool(reps,changed,AT,eligibility)
    assert result['eligible']==list('EF')
    assert result['exclusions']['D']=='MERGED_INDUSTRY_LOST_FROZEN_QUARTER_KEY'
    assert result['exclusions']['A']=='LOW_LIQUIDITY'
    assert result['risk_scaling'] is False


def test_split_does_not_add_nonrepresentatives_or_expand_industry_slots():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'csi_level1_id':'TECH_A'},'C':{'csi_level1_id':'TECH_C'}})
    result=monthly_pool(reps,changed,AT,qualify())
    assert result['eligible']==list('ADEF') and 'C' not in result['industries']


def test_midquarter_index_identity_change_and_cross_industry_exit():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'index_identity':'IX_REPLACED'},'D':{'r1i_scope_status':'EXCLUDED'}})
    result=monthly_pool(reps,changed,AT,qualify())
    assert result['eligible']==list('EF')
    assert result['exclusions']['A']=='INDEX_ECONOMIC_IDENTITY_CHANGED_UNTIL_NEXT_QUARTER'
    assert result['exclusions']['D']=='NO_LONGER_SINGLE_INDUSTRY_SCOPE'


def test_index_identity_roundtrip_cannot_reenter_before_next_quarter():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'index_identity':'IX_REPLACED'}})
    reverted=changed.loc[changed.instrument_id.eq('A')].iloc[-1].to_dict()
    reverted.update(index_identity='IX_A',effective_from='2021-05-20',available_at='2021-05-19T20:00:00+08:00')
    changed=pd.concat([changed,pd.DataFrame([reverted])],ignore_index=True)
    result=monthly_pool(reps,changed,AT,qualify())
    assert result['eligible']==list('DEF')
    assert result['exclusions']['A']=='INDEX_ECONOMIC_IDENTITY_CHANGED_UNTIL_NEXT_QUARTER'


def test_announced_future_index_transition_does_not_disable_current_index_early():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'index_identity':'IX_FUTURE'}},effective_from='2021-06-15')
    assert monthly_pool(reps,changed,AT,qualify())['eligible']==list('ADEF')


def test_explicit_correction_removes_a_false_index_transition():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':{'index_identity':'FALSE_INDEX','revision_id':'FALSE'}})
    corrected=changed.loc[changed.instrument_id.eq('A')].iloc[-1].to_dict()
    corrected.update(index_identity='IX_A',revision_id='CORRECTED',supersedes_id='FALSE',
                     revision_kind='CORRECTION',available_at='2021-05-20T20:00:00+08:00')
    changed=pd.concat([changed,pd.DataFrame([corrected])],ignore_index=True)
    assert monthly_pool(reps,changed,AT,qualify())['eligible']==list('ADEF')


def test_shared_historical_effective_date_keeps_publication_and_expiry_contracts():
    rows=[dict(available_at='2021-01-01T00:00:00+08:00',effective_from='2021-01-01',
               effective_to=None,value='old'),
          dict(available_at='2021-04-01T00:00:00+08:00',effective_from='2021-05-01',
               effective_to='2021-05-15',value='new')]
    assert master_record(rows,AT,effective_date='2021-04-30')['value']=='old'
    assert master_record(rows,AT,effective_date='2021-05-01')['value']=='new'
    assert master_record(rows,AT,effective_date='2021-05-15') is None
    assert master_record(rows,AT) is None
    with pytest.raises(TemporalStateError):master_record(rows,AT,effective_date='2021-06-01')
    with pytest.raises(TemporalStateError):master_record(rows,AT,effective_date='not-a-date')
    future=[dict(rows[1],available_at='2021-06-01T00:00:00+08:00')]
    assert master_record([rows[0]]+future,AT,effective_date='2021-05-02')['value']=='old'


@pytest.mark.parametrize('changes',[
    {'effective_to':'2021-05-15'},
    {'mapping_available_at':'2021-06-01T00:00:00+08:00'},
    {'mapping_available_at':None},
    {'r1i_scope_status':'UNKNOWN'},
    {'benchmark_source_available_at':'2021-06-01T00:00:00+08:00'},
])
def test_expired_or_unavailable_latest_mapping_never_revives_old_state(changes):
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    changed=transition(master,{'A':changes})
    with pytest.raises(StrategyBlockedError):
        monthly_pool(reps,changed,AT,qualify())


def test_mixed_contemporary_taxonomy_versions_are_not_one_historical_classification():
    master,bars,calendar=fixture()
    master.loc[master.instrument_id.eq('D'),'csi_taxonomy_version']='CSI_SYNTHETIC_V2'
    with pytest.raises(StrategyBlockedError):
        select(master,bars,calendar)


def test_unknown_monthly_qualification_is_blocked_not_cash():
    master,bars,calendar=fixture();reps=select(master,bars,calendar)
    incomplete=qualify();del incomplete['A']
    with pytest.raises(StrategyBlockedError):
        monthly_pool(reps,master,AT,incomplete)


@pytest.mark.parametrize('count',[0,1,2,3])
def test_complete_small_pool_cash_and_n3_no_ranking_freedom(count):
    ids=list('ABC')[:count];mom={sid:-i-1 for i,sid in enumerate(ids)}
    results=[rule_weights(ids,mom,True,v) for v in ['E0','R0','E1','R1']]
    expected={} if count<3 else {sid:1/3 for sid in 'ABC'}
    assert all(r['weights']==expected and r['risk_scaling'] is False for r in results)
    if count==3:assert all('NO_RANKING_FREEDOM' in r['status'] for r in results)


def test_all_negative_momentum_still_ranks_and_missing_required_inputs_block():
    ids=list('ABCD');momentum={'A':-4,'B':-2,'C':-2,'D':-3}
    assert rule_weights(ids,momentum,True,'R0')['weights']=={'B':1/3,'C':1/3,'D':1/3}
    assert rule_weights(ids,momentum,False,'R1')['weights']=={}
    with pytest.raises(StrategyBlockedError):rule_weights(ids,{'A':1},True,'R0')
    with pytest.raises(StrategyBlockedError):rule_weights(ids,momentum,None,'E1')


def test_identification_uses_execution_period_and_unknowns_never_zero():
    rows=[]
    for year,months in [(2019,range(1,13)),(2020,range(1,13)),(2021,range(1,13)),
                        (2022,range(1,9)),(2023,range(1,9)),(2024,range(1,9))]:
        rows.extend(dict(execution_date=f'{year}-{month:02d}-05',data_complete=True,eligible_count=4,trend_on=True)
                    for month in months)
    expected=[r['execution_date'] for r in rows]
    # Execution is in validation despite its signal anchor being in development.
    rows[36]['signal_anchor_date']='2021-12-31'
    result=identification_gate(rows,expected)
    assert result['status']=='PASS'
    assert result['n_ge4_by_period']==dict(development=36,validation=24)
    assert result['n_ge4_by_validation_year']=={2022:8,2023:8,2024:8}
    assert result['n_ge4_and_trend_on']==60
    changed=deepcopy(rows);changed[-1]['eligible_count']=3
    assert identification_gate(changed,expected)['status']=='LIMITED_IDENTIFICATION'
    changed=deepcopy(rows);changed[-1]['data_complete']=False
    assert identification_gate(changed,expected)['status']=='DATA_BLOCKED'
    assert identification_gate(rows[:-1],expected)['status']=='DATA_BLOCKED'
    # Preserve total24 validation opportunities but leave2022 with only5.
    changed=deepcopy(rows)
    for position,month in zip([36,37,38],[9,10,11]):
        changed[position]['execution_date']=f'2024-{month:02d}-05'
    assert identification_gate(changed,[r['execution_date'] for r in changed])['status']=='LIMITED_IDENTIFICATION'
