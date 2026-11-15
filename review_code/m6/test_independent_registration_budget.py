"""Independent fixed-matrix checks and offline bounded-collector probes."""
import importlib.util
import itertools
import json
from pathlib import Path
import time

import pytest
from quant_research.budget import BudgetLedger, BudgetExceeded

ROOT = Path(__file__).resolve().parents[2]


def collector():
    spec = importlib.util.spec_from_file_location('independent_m6_sources', ROOT / 'scripts/m6_sources.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registered_matrix_is_exact_cartesian_product_without_search():
    registry = json.loads((ROOT/'reports/m6_r1i/EXPERIMENT_REGISTRY.json').read_text('utf-8'))
    rows = registry['trials']
    expected = set(itertools.product([100000], ['E0','R0','E1','R1'],
                                    ['development','validation'], ['base','cost2','cost3','delay1']))
    expected |= set(itertools.product([10000,500000,1000000], ['E0','R0','E1','R1'],
                                     ['development','validation'], ['base']))
    actual = {(r['initial_cash'],r['variant'],r['period'],r['path']) for r in rows}
    assert len(rows) == len(actual) == 56
    assert actual == expected
    for row in rows:
        assert row['risk_scaling'] is False
        assert row['statutory_tax_multiplier'] == 1
        assert row['signal_release_delay'] == 1
        assert row['execution_delay'] == (2 if row['path']=='delay1' else 1)
        expected_cost = {'cost2':2,'cost3':3}.get(row['path'],1)
        assert row['cost_multiplier'] == row['slippage_multiplier'] == expected_cost
    assert registry['periods'] == {'development':['2016-01-01','2021-12-31'],
                                   'validation':['2022-01-01','2024-12-31']}
    assert registry['primary_comparison']['annual_incremental_fixed_cost'] is None
    assert registry['primary_comparison']['economic_status'] == 'BLOCKED_HURDLE'
    assert registry['bootstrap'] == dict(synchronous_across_strategies=True,separate_periods=True,
        primary_block=60,sensitivity_blocks=[20,120],repetitions=5000,seed=20261114,final_holm=False)


def test_budget_allocations_fit_global_registered_caps():
    mod = collector()
    assert mod.LIMITS == dict(http_attempts=1024,baostock_wire_attempts=1024,new_body_bytes=1024**3)
    for metric, limit in mod.LIMITS.items():
        assert sum(scope[metric] for scope in mod.SCOPES.values()) == limit
    assert mod.SCOPES['stock_execution']['http_attempts'] == 40
    assert mod.SCOPES['stock_source']['http_attempts'] == 20
    assert mod.SCOPES['stock_execution']['new_body_bytes'] == 40*1024**2
    assert mod.SCOPES['stock_source']['new_body_bytes'] == 20*1024**2


def test_exhausted_stock_attempt_scope_leaves_independent_r1i_scope(tmp_path):
    limits = dict(http_attempts=3, baostock_wire_attempts=0, new_body_bytes=20)
    scopes = {'stock':dict(http_attempts=1,baostock_wire_attempts=0,new_body_bytes=5),
              'r1i':dict(http_attempts=2,baostock_wire_attempts=0,new_body_bytes=15)}
    book = BudgetLedger(tmp_path,limits,scope_limits=scopes)
    first=book.begin('http_attempts','stock attempt',scope='stock')
    book.finish(first,b'FAIL',time.perf_counter(),status='FAILED')
    with pytest.raises(BudgetExceeded):
        book.begin('http_attempts','stock retry',scope='stock')
    second=book.begin('http_attempts','r1i allowed',scope='r1i')
    book.finish(second,b'OK',time.perf_counter(),status='FETCHED')
    state=book.read()
    assert state['used'] == dict(http_attempts=2,baostock_wire_attempts=0,new_body_bytes=6)
    assert state['stopped'] is False


def test_oversized_sdk_body_is_durable_and_restart_stops(tmp_path):
    limits=dict(http_attempts=2,baostock_wire_attempts=2,new_body_bytes=5)
    book=BudgetLedger(tmp_path,limits)
    idx=book.begin('baostock_wire_attempts','invented oversized body')
    with pytest.raises(BudgetExceeded):
        book.finish(idx,b'123456',time.perf_counter(),status='RETURNED')
    disk=json.loads((tmp_path/'budget.json').read_text('utf-8'))
    assert disk['used']['new_body_bytes']==6
    assert disk['attempts'][0]['terminal'] is True
    assert Path(disk['attempts'][0]['raw_path']).read_bytes()==b'123456'
    assert disk['stopped'] is True
    reopened=BudgetLedger(tmp_path,limits)
    with pytest.raises(BudgetExceeded):
        reopened.begin('http_attempts','restart cannot erase overshoot')
    reopened.finish(idx,b'123456',time.perf_counter(),status='RETURNED')
    assert reopened.read()['used']['new_body_bytes']==6


def test_offline_fetch_failure_is_charged_and_original_ledgers_untouched(tmp_path,monkeypatch):
    mod=collector()
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs/M6_PLAN.md').write_text('INVENTED TEST PLAN',encoding='utf-8')
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'OUT',tmp_path/'data/raw_m6')
    class OfflineFailure:
        def open(self,*args,**kwargs):
            raise OSError('Synthetic transport failure; no network attempted')
    monkeypatch.setattr(mod,'build_opener',lambda *_: OfflineFailure())
    result=mod.fetch('synthetic_failure','https://www.sse.com.cn/invented',
                     dates='2019-01-01~2019-12-31',scope='stock_execution')
    assert result['status']=='FAILED' and result['terminal'] is True
    state=json.loads((tmp_path/'data/raw_m6/budget.json').read_text('utf-8'))
    assert state['used']['http_attempts']==1 and state['used']['new_body_bytes']==0
    assert not (tmp_path/'data/raw_m5_equity').exists()


def test_holdout_request_rejected_before_any_collector_call():
    mod=collector()
    with pytest.raises(ValueError):
        mod.validate_dates('2024-12-31~2025-01-01')
    with pytest.raises(ValueError):
        mod.validate_url('https://www.sse.com.cn/invented?date=2025-01-01',
                         dates='2019-01-01~2019-12-31')
