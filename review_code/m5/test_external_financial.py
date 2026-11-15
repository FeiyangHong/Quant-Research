"""Independent M5 finance review; constants transcribed from rendered PDF pages.

All amounts are CNY yuan. The two numerical cases confer no latest-report,
freshness, market-cap, human, full-pool, or strategy admission.
"""
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_research.data import DataValidationError
from quant_research.equity_features import financial_asof, r2_factors

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/m5_financial'
NP='net_profit_parent_ytd';CF='operating_cashflow_ytd';AS='total_assets'
KM='sh.600518';SH='sz.002857'

# Direct visual transcriptions, not factor_cases.json or author oracle output.
DOCUMENTS={
 '15b3b15df2df':[(6,'2017-12-31',NP,'4100926148.57'),(6,'2017-12-31',CF,'1842794237.84'),
                  (7,'2017-12-31',AS,'68722020630.61'),(7,'2016-12-31',AS,'54823896576.81')],
 '9f47aa0dc0a8':[(6,'2018-12-31',NP,'1135188498.44'),(6,'2018-12-31',CF,'-3191529576.31'),
                  (6,'2018-12-31',AS,'74627937566.57'),(6,'2017-12-31',NP,'2149836281.41'),
                  (6,'2017-12-31',CF,'-4840052606.46'),(6,'2017-12-31',AS,'65292951329.52'),
                  (6,'2016-12-31',AS,'53251762620.05')],
 '9b57ae1e21bc':[(2,'2023-09-30',NP,'-6354889.62'),(2,'2023-09-30',CF,'-9898689.75'),
                  (2,'2023-09-30',AS,'726007340.73')],
 '41d9370fd96d':[(3,'2023-09-30',NP,'-8587577.84'),(4,'2023-09-30',CF,'-9898689.75'),
                  (4,'2023-09-30',AS,'736593802.62')],
 '7028b0a1c7b8':[(1,'2022-09-30',NP,'100478.18'),(1,'2022-09-30',CF,'-20765136.43'),
                  (1,'2022-09-30',AS,'606916408.59')],
 '3ae8304f34e4':[(8,'2022-12-31',NP,'12944711.92'),(8,'2022-12-31',CF,'45404676.85')],
}


@pytest.fixture
def inputs():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    facts=pd.DataFrame(read(OUT/'canonical_facts.json'))
    cov=pd.DataFrame(read(OUT/'report_coverage.json'))
    cal=read(ROOT/'tests/fixtures/m5_verified_calendar_2015_2024.json')['trading_dates']
    return facts,cov,cal


def calculate(inputs,identity=SH,at='2023-10-27T21:00:00+08:00',market=None,coverage=True):
    facts,cov,cal=inputs
    market=market if market is not None else pd.DataFrame(columns=['instrument_id','date','available_at','market_cap','market_cap_scope'])
    contract=cov.loc[cov.instrument_id.eq(identity)&cov['asof'].eq(at)] if coverage else None
    return r2_factors(facts,market,at,cal,[identity],report_coverage=contract).iloc[0]


def precise(actual,expected):
    error=abs(D(str(actual))-expected)
    assert error <= D('1e-10') or error <= abs(expected)*D('1e-8')


@pytest.mark.parametrize('prefix',list(DOCUMENTS))
def test_twenty_two_facts_match_six_visually_reviewed_originals(inputs,prefix):
    facts,_,_=inputs
    rows=facts.loc[facts.source_document_hash.str.startswith(prefix)]
    assert len(rows)==len(DOCUMENTS[prefix])
    for page,period,field,value in DOCUMENTS[prefix]:
        match=rows.loc[rows.period_end.eq(period)&rows.field.eq(field)]
        assert len(match)==1
        row=match.iloc[0]
        assert row.source_page==page and row.report_scope=='consolidated' and row.currency=='CNY'
        assert row.source_unit==row.normalized_unit=='CNY_yuan'
        assert D(str(row.value))==D(value)==D(str(row.source_value))
        assert not row.independent_human_signoff


@pytest.mark.archived_source
@pytest.mark.parametrize('prefix',list(DOCUMENTS))
def test_local_original_pdf_matches_recorded_digest(inputs,prefix):
    facts,_,_=inputs
    row=facts.loc[facts.source_document_hash.str.startswith(prefix)].iloc[0]
    path=ROOT/row.source_document_path.replace('\\','/')
    if not path.is_file():
        pytest.skip('Archived original PDF unavailable; portable transcription and factor tests still run: '+prefix)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==row.source_document_hash


def test_committed_calendar_keeps_real_provenance_and_pre2025_sessions():
    fixture=json.loads((ROOT/'tests/fixtures/m5_verified_calendar_2015_2024.json').read_text(encoding='utf-8'))
    dates=fixture['trading_dates']
    assert fixture['synthetic'] is False and fixture['data_origin'].startswith('REAL_')
    assert dates==sorted(set(dates)) and dates[0]=='2015-01-05' and dates[-1]=='2024-12-31'
    assert len(dates)==2431
    assert hashlib.sha256(json.dumps(dates,separators=(',',':')).encode()).hexdigest()==fixture['trading_dates_sha256']
    assert [s['sha256'] for s in fixture['source_calendars']]==[
        '8200cca2c04cc847ebddf43c0783ff1b8d15b28a9d11e48a3b3f51661c4e52ae',
        'be8124db8fbc33b9162df4948f6669c0e17fc89f3251b0027ce41687e28c3526']


def test_annual_and_ttm_hand_arithmetic_through_existing_main_chain(inputs):
    annual=calculate(inputs,KM,'2018-04-27T21:00:00+08:00')
    q3=calculate(inputs)
    with localcontext() as ctx:
        ctx.prec=40
        annual_assets=(D('68722020630.61')+D('54823896576.81'))/2
        quarter_assets=(D('726007340.73')+D('606916408.59'))/2
        quarter_np=D('-6354889.62')+D('12944711.92')-D('100478.18')
        quarter_cfo=D('-9898689.75')+D('45404676.85')-D('-20765136.43')
        assert annual_assets==D('61772958603.71') and quarter_assets==D('666461874.66')
        assert quarter_np==D('6489344.12') and quarter_cfo==D('56271123.53')
        precise(annual.F02,D('4100926148.57')/annual_assets)
        precise(annual.F03,D('1842794237.84')/annual_assets)
        precise(q3.F02,quarter_np/quarter_assets)
        precise(q3.F03,quarter_cfo/quarter_assets)
    assert annual.report_age_days==117 and q3.report_age_days==27
    for row in [annual,q3]:
        assert row.F01 is None and not row.all_three_valid and not row.formal_eligible
        assert row.freshness_policy is None
        assert row.freshness_status=='UNASSESSED_NO_REGISTERED_POLICY'
        assert row.report_coverage_status=='PARTIAL' and row.latest_period_status=='UNVERIFIED'


@pytest.mark.parametrize('identity,first,later,period,corrected',[
    (KM,'2018-04-27T21:00:00+08:00','2019-05-06T21:00:00+08:00','2017-12-31','2149836281.41'),
    (SH,'2023-10-27T21:00:00+08:00','2024-12-26T21:00:00+08:00','2023-09-30','-8587577.84')])
def test_later_revisions_preserve_prefix_without_hiding_newer_reports(inputs,identity,first,later,period,corrected):
    facts,cov,cal=inputs
    prefix=facts.loc[pd.to_datetime(facts.available_at,utc=True)<=pd.Timestamp(first)]
    pd.testing.assert_series_equal(calculate(inputs,identity,first),calculate((prefix,cov,cal),identity,first))
    pd.testing.assert_series_equal(calculate(inputs,identity,first),calculate((facts.iloc[::-1],cov,cal),identity,first))
    selected=financial_asof(facts,later,cal)
    row=selected.loc[selected.instrument_id.eq(identity)&selected.period_end.eq(period)&selected.field.eq(NP)].iloc[0]
    assert D(row.value)==D(corrected) and row.version_basis=='CORRECTION_FILING'
    later_factors=calculate(inputs,identity,later)
    assert later_factors.period_end==('2019-03-31' if identity==KM else '2024-09-30')
    assert later_factors.F01 is None and later_factors.F02 is None and later_factors.F03 is None
    assert not later_factors.formal_eligible


@pytest.mark.parametrize('field,period,blocked',[ (NP,'2022-09-30','F02'),(CF,'2022-12-31','F03'),
    (AS,'2022-09-30','BOTH'),(AS,'2023-09-30','BOTH')])
def test_missing_dependency_never_falls_back_or_cross_disables_factor(inputs,field,period,blocked):
    facts,cov,cal=inputs
    facts=facts.loc[~(facts.instrument_id.eq(SH)&facts.period_end.eq(period)&facts.field.eq(field))]
    row=calculate((facts,cov,cal))
    assert 'MISSING:'+field+':'+period in row.missing_reasons
    if blocked in ('F02','BOTH'):assert row.F02 is None
    else:precise(row.F02,D('6489344.12')/D('666461874.66'))
    if blocked in ('F03','BOTH'):assert row.F03 is None
    else:precise(row.F03,D('56271123.53')/D('666461874.66'))


def cap(**changes):
    row=dict(instrument_id=SH,date='2023-10-27',available_at='2023-10-27T21:00:00+08:00',
        market_cap=1e9,market_cap_scope='TOTAL_EQUITY',share_class_consistent=True,
        price_share_class='A_ORDINARY',capital_share_class='A_ORDINARY',
        price_source_sha256='a'*64,shares_source_sha256='b'*64,
        provenance='INVENTED_CAP_FOR_REJECTION_TEST_ONLY')
    row.update(changes);return pd.DataFrame([row])


@pytest.mark.parametrize('changes',[
    {'date':'2023-10-26'},{'available_at':'2023-10-30T21:00:00+08:00'},
    {'market_cap_scope':'FLOAT'},{'capital_share_class':'A_PLUS_H'},
    {'share_class_consistent':False},{'price_source_sha256':''},{'shares_source_sha256':''}])
def test_cap_date_availability_and_class_failures_only_block_f01(inputs,changes):
    row=calculate(inputs,market=cap(**changes))
    assert row.F01 is None
    precise(row.F02,D('6489344.12')/D('666461874.66'))
    precise(row.F03,D('56271123.53')/D('666461874.66'))


def test_total_equity_string_alone_is_not_share_class_evidence(inputs):
    market=cap().drop(columns=['share_class_consistent','price_share_class','capital_share_class',
                              'price_source_sha256','shares_source_sha256'])
    row=calculate(inputs,market=market)
    assert row.F01 is None and 'UNVERIFIED_MARKET_CAP_SHARE_CLASS' in row.missing_reasons


def test_even_complete_coverage_and_three_calculable_numbers_do_not_admit(inputs):
    facts,cov,cal=inputs;cov=cov.copy();cov['coverage_status']='COMPLETE_THROUGH_CUTOFF'
    row=calculate((facts,cov,cal),market=cap())
    precise(row.F01,D('6489344.12')/D('1000000000'))
    assert row.all_three_valid and not row.formal_eligible
    assert row.freshness_policy is None and 'FRESHNESS_POLICY_UNREGISTERED' in row.formal_blockers


def test_missing_latest_coverage_cannot_grant_formal_eligibility(inputs):
    row=calculate(inputs,market=cap(),coverage=False)
    assert row.all_three_valid and not row.formal_eligible
    assert row.latest_period_status=='UNVERIFIED'
    assert 'LATEST_REPORT_COVERAGE_UNVERIFIED' in row.formal_blockers


def test_backdated_date_only_availability_rejected(inputs):
    facts,cov,cal=inputs;facts=facts.copy()
    ix=facts.index[facts.revision_id.str.startswith('KM2017_AS_PUBLISHED')][0]
    facts.loc[ix,'available_at']='2018-04-26T21:00:00+08:00'
    with pytest.raises(DataValidationError,match='precedes'):
        financial_asof(facts,'2018-04-27T21:00:00+08:00',cal)


def test_late_2024_document_available_2025_cannot_enter_old_snapshot(inputs):
    facts,cov,cal=inputs
    added=facts.loc[facts.instrument_id.eq(SH)&facts.field.eq(NP)&facts.version_basis.eq('CORRECTION_FILING')].iloc[0].to_dict()
    added.update(revision_id='INVENTED_2025_BOUNDARY',supersedes_id=added['revision_id'],
        value='99999999',published_at='2024-12-31T00:00:00+08:00',available_at='2025-01-02T21:00:00+08:00')
    future=pd.concat([facts,pd.DataFrame([added])],ignore_index=True)
    pd.testing.assert_frame_equal(financial_asof(facts,'2024-12-31T21:00:00+08:00',cal),
                                  financial_asof(future,'2024-12-31T21:00:00+08:00',cal))
