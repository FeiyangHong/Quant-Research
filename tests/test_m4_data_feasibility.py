"""M4 safety checks: budgets, conservative clocks and unshrunk coverage."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import m4_data_feasibility as probe
import m4_data_build as build

def test_attempt_budget_reserves_before_network_and_includes_failed_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'OUT',tmp_path)
    monkeypatch.setattr(probe,'LIMITS',{'http_attempts':1,'baostock_wire_attempts':1,'new_body_bytes':100})
    probe.begin('http_attempts','failed_call')
    with pytest.raises(RuntimeError,match='exhausted'):
        probe.begin('http_attempts','would_exceed')
    assert probe.budget()['used']['http_attempts']==1

def test_download_byte_budget_blocks_subsequent_request(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'OUT',tmp_path)
    monkeypatch.setattr(probe,'LIMITS',{'http_attempts':10,'baostock_wire_attempts':10,'new_body_bytes':3})
    index=probe.begin('http_attempts','one')
    probe.finish(index,b'abc',0,status='TRUNCATED_BUDGET')
    with pytest.raises(RuntimeError,match='exhausted'):
        probe.begin('http_attempts','two')

@pytest.mark.parametrize('url',[
  'https://static.cninfo.com.cn/finalpage/2025-01-01/secret.PDF',
  'https://example.com/finalpage/2020-01-01/document.PDF',
  'http://static.cninfo.com.cn/finalpage/2020-01-01/document.PDF'])
def test_unknown_source_and_holdout_documents_rejected_before_request(url):
    with pytest.raises(ValueError):probe.validate_document_url(url)

def test_date_only_clock_uses_real_holiday_and_requires_execution_calendar():
    assert probe.date_only_clock('2020-04-30',['2020-04-30','2020-05-06','2020-05-07'])=={'available_at':'2020-05-06T21:00:00+08:00','earliest_execution':'2020-05-07'}
    with pytest.raises(ValueError):probe.date_only_clock('2024-12-31',['2024-12-31'])

def test_missing_data_and_retrospective_name_never_shrink_pool_or_infer_status():
    uni=[{'code':'sz.000979','code_name':'CURRENT_RETIREMENT_NAME','tradeStatus':'0'},
         {'code':'sh.600519','code_name':'normal','tradeStatus':'1'},
         {'code':'sh.688001','code_name':'outside account scope','tradeStatus':'1'}]
    result=build.join_full_pool(uni,{}, {},{})
    assert [r['instrument_id'] for r in result]==['sz.000979','sh.600519']
    assert all(r['isST_vendor_history'] is None and r['risk_state_complete'] is None and r['r2_qualified'] is None for r in result)
    assert all(r['historical_total_shares'] is None for r in result)

def test_industry_classification_headers_and_conflicts_fail_closed():
    assert build.official_industry('制造业(C) 27 医药 600518 康美\n 600519 示例')=={'600518':'27','600519':'27'}
    with pytest.raises(ValueError):build.official_industry('600518 missing header')
    with pytest.raises(ValueError):build.official_industry('27 医药 600518 a\n 28 制造 600518 a')

def test_delivered_cases_keep_source_disputes_and_human_gate_closed():
    data=json.loads((ROOT/'reports/m4_data/financial_vintage_cases.json').read_text(encoding='utf-8'))
    assert data['attempted_issuer_period_cases']==8
    assert data['complete_documentary_pairs']==5
    assert data['independent_human_accepted_cases']==0
    assert len({(c['instrument_id'],c['period_end']) for c in data['cases']})==8
    for case in data['cases']:
        assert not case['counts_toward_human_admission_gate']
        if case['case_status']=='QUARANTINED_SOURCE_CONFLICT':
            assert any(v is None for v in case['revision']['values'].values())
            assert case['conflicts']

def test_actual_snapshot_coverage_denominator_is_never_financial_complete_subset():
    coverage=json.loads((ROOT/'reports/m4_data/coverage_summary.json').read_text(encoding='utf-8'))
    assert coverage['main_chinext_denominator']==3779
    assert {v['denominator'] for v in coverage['coverage'].values()}=={3779}
    assert coverage['coverage']['historical_total_shares']['observed']==0
    assert coverage['coverage']['r2_qualification_known']['observed']==0
    assert coverage['nonST_size_percentile_denominator'] is None
