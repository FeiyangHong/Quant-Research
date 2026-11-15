"""Offline counterexamples for the durable, shared source budget."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
from types import ModuleType
import pytest
from quant_research.budget import BudgetLedger, BudgetExceeded, exclusive_lock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import m5_sources as sources

def book(path, size=5):
    return BudgetLedger(path,dict(http_attempts=10,baostock_wire_attempts=10,new_body_bytes=size))

def test_six_bytes_for_five_are_persisted_before_raising_and_restart_closed(tmp_path):
    b=book(tmp_path);idx=b.begin('http_attempts','overflow')
    with pytest.raises(BudgetExceeded,match='persisted'):
        b.finish(idx,b'123456',time.perf_counter(),status='FETCHED')
    raw=json.loads((tmp_path/'budget.json').read_text())
    assert raw['used']['new_body_bytes']==6 and raw['stopped']
    assert raw['attempts'][0]['terminal'] and raw['attempts'][0]['byte_count']==6
    assert Path(raw['attempts'][0]['raw_path']).read_bytes()==b'123456'
    with pytest.raises(BudgetExceeded):book(tmp_path).begin('http_attempts','restart')
    # Duplicate completion after the cap exception is idempotent.
    b.finish(idx,b'123456',0,status='FETCHED')
    assert b.read()['used']['new_body_bytes']==6

def test_duplicate_and_conflicting_duplicate_never_double_count(tmp_path):
    b=book(tmp_path);i=b.begin('http_attempts','one');b.finish(i,b'abc',0,status='FETCHED')
    b.finish(i,b'abc',0,status='FETCHED')
    assert b.read()['used']['new_body_bytes']==3
    with pytest.raises(RuntimeError,match='Conflicting'):b.finish(i,b'xyz',0,status='FAILED')
    assert b.read()['used']['new_body_bytes']==3 and b.read()['stopped']

def test_unresolved_inflight_restart_fails_closed(tmp_path):
    book(tmp_path).begin('http_attempts','interrupted')
    with pytest.raises(BudgetExceeded,match='inflight'):book(tmp_path).begin('http_attempts','restart')
    assert book(tmp_path).read()['stop_reason']=='UNRESOLVED_INFLIGHT_REQUEST'

def test_parallel_collectors_serialize_and_do_not_lose_updates(tmp_path):
    def work(n):
        with exclusive_lock(tmp_path/'network.lock'):
            b=book(tmp_path,20);i=b.begin('http_attempts',str(n));b.finish(i,b'xy',0,status='FETCHED')
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(work,range(9)))
    b=book(tmp_path,20).read()
    assert b['used']==dict(http_attempts=9,baostock_wire_attempts=0,new_body_bytes=18)
    assert len({a['id'] for a in b['attempts']})==9

def test_scope_limits_and_empty_failures(tmp_path):
    b=BudgetLedger(tmp_path,dict(http_attempts=3,baostock_wire_attempts=0,new_body_bytes=100),scope_limits={'a':dict(http_attempts=1,new_body_bytes=50),'b':dict(http_attempts=2,new_body_bytes=50)})
    i=b.begin('http_attempts','failed',scope='a');b.finish(i,b'',0,status='FAILED')
    with pytest.raises(BudgetExceeded,match='Scope'):b.begin('http_attempts','denied',scope='a')
    i=b.begin('http_attempts','other',scope='b');b.finish(i,b'xx',0,status='FETCHED')
    assert b.read()['used']['http_attempts']==2

def test_http_failure_is_terminal_and_counted(tmp_path,monkeypatch):
    monkeypatch.setattr(sources,'OUT',tmp_path)
    class Broken:
        def open(self,*a,**k):raise OSError('deliberate offline failure')
    monkeypatch.setattr(sources,'build_opener',lambda *a:Broken())
    r=sources.fetch('offline_failure','https://static.cninfo.com.cn/finalpage/2020-01-01/a.PDF',dates='2020-01-01~2020-01-01',scope='financial')
    assert r['terminal'] and r['status']=='FAILED' and r['byte_count']==0
    assert sources.ledger().read()['used']['http_attempts']==1

@pytest.mark.parametrize('url',[
 'https://example.com/a',
 'https://static.cninfo.com.cn/finalpage/2025-01-01/a.PDF',
 'http://static.cninfo.com.cn/a',
 'https://push2.eastmoney.com/api/qt/stock/get'])
def test_source_guards_precede_budget_mutation(tmp_path,monkeypatch,url):
    monkeypatch.setattr(sources,'OUT',tmp_path)
    with pytest.raises(ValueError):sources.fetch('blocked',url,dates='2020-01-01~2020-01-01',scope='market_cap')
    assert not (tmp_path/'budget.json').exists()

def test_cninfo_body_cannot_override_declared_range():
    with pytest.raises(ValueError):sources.validate_url('https://www.cninfo.com.cn/new/hisAnnouncement/query',dates='2020-01-01~2020-07-31',body='seDate=2025-01-01~2026-01-01')

def test_unvalidated_redirect_is_refused():
    with pytest.raises(ValueError,match='Redirect'):
        sources.NoRedirects().redirect_request(None,None,302,'',{},'https://evil.example/file')

def test_corrupt_ledger_is_not_reset(tmp_path):
    (tmp_path/'budget.json').write_text('{bad')
    with pytest.raises(json.JSONDecodeError):book(tmp_path).begin('http_attempts','one')
    assert (tmp_path/'budget.json').read_text()=='{bad'


def test_finish_cannot_rewrite_reserved_identity_and_charges_received_bytes(tmp_path):
    b=book(tmp_path);i=b.begin('http_attempts','original')
    with pytest.raises(RuntimeError,match='charged'):
        b.finish(i,b'ab',0,status='FETCHED',kind='baostock_wire_attempts',scope='other')
    state=b.read();r=state['attempts'][0]
    assert r['kind']=='http_attempts' and r['scope'] is None
    assert r['terminal'] and state['stopped'] and state['used']['new_body_bytes']==2


def test_sdk_exception_terminal_and_actual_message_holdout_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(sources,'OUT',tmp_path)
    # Test the collector's wrapper contract without requiring an optional SDK
    # installed only in an ignored local work directory. No network transport.
    sdk=ModuleType('baostock');util=ModuleType('baostock.util');sock=ModuleType('baostock.util.socketutil')
    sdk.util=util;util.socketutil=sock
    def broken(msg):raise OSError('offline SDK failure')
    sock.send_msg=broken
    for name,module in [('baostock',sdk),('baostock.util',util),('baostock.util.socketutil',sock)]:
        monkeypatch.setitem(sys.modules,name,module)
    with sources.baostock_session(scope='execution',label='fake',dates='2020-01-01~2020-07-31'):
        with pytest.raises(ValueError,match='Post-2024'):sock.send_msg('2025-01-01')
        with pytest.raises(OSError):sock.send_msg('2020-07-31')
    state=sources.ledger().read()
    assert state['used']['baostock_wire_attempts']==1
    assert state['attempts'][0]['terminal'] and state['attempts'][0]['status']=='FAILED'
