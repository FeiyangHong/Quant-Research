"""Offline non-author verification of the M6 collector incident repair."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]


def prepared(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('independent_m6_lease',ROOT/'scripts/m6_sources.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs/M6_PLAN.md').write_text('SYNTHETIC PLAN',encoding='utf-8')
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'OUT',tmp_path/'data/raw_m6')
    return mod


def test_external_lease_serializes_fetch_and_charges_actual_payload(tmp_path,monkeypatch):
    mod=prepared(tmp_path,monkeypatch)
    ticket=mod.begin_external('synthetic_external',scope='stock_execution',query='invented historical rule',
                              dates='2019-01-01~2019-12-31')
    class Response:
        status=200
        headers={'Content-Type':'text/plain'}
        def __enter__(self): self.remaining=b'next';return self
        def __exit__(self,*args): return None
        def read(self,n): result=self.remaining[:n];self.remaining=self.remaining[n:];return result
    sent=threading.Event()
    class Opener:
        def open(self,*args,**kwargs): sent.set();return Response()
    monkeypatch.setattr(mod,'build_opener',lambda *_:Opener())
    entered=threading.Event()
    result=[]
    def competing():
        entered.set()
        try:
            result.append(mod.fetch('synthetic_next','https://www.sse.com.cn/invented',
                         dates='2019-01-01~2019-12-31',scope='r1i'))
        except BaseException as exc:
            result.append(exc)
    thread=threading.Thread(target=competing,daemon=True)
    thread.start()
    assert entered.wait(1)
    time.sleep(.08)
    state=mod.ledger().read()
    assert len(state['attempts'])==1 and state['stopped'] is False
    assert sent.is_set() is False
    response='虚构工具响应'.encode('utf-8')
    rec=mod.finish_external(ticket,response)
    thread.join(3)
    assert not thread.is_alive() and isinstance(result[0],dict)
    assert rec['byte_count']==len(response)==18
    assert rec['elapsed_seconds']>=.08
    assert Path(rec['raw_path']).read_bytes()==response
    state=mod.ledger().read()
    assert state['used']['http_attempts']==2
    assert state['used']['new_body_bytes']==22
    assert state['stopped'] is False and all(r['terminal'] is True for r in state['attempts'])


def test_wrong_token_and_abandoned_lock_do_not_auto_resume(tmp_path,monkeypatch):
    mod=prepared(tmp_path,monkeypatch)
    ticket=mod.begin_external('abandoned',scope='stock_execution',query='invented',dates='2019-01-01~2019-12-31')
    bad=dict(ticket,lease_token='unowned-token')
    with pytest.raises(RuntimeError,match='own active network lease'):
        mod.finish_external(bad,b'untrusted')
    assert (mod.OUT/'network.lock').read_text()==ticket['lease_token']
    calls=iter([0,100])
    monkeypatch.setattr(mod,'time',SimpleNamespace(monotonic=lambda:next(calls),sleep=lambda _:None,
                                                   perf_counter=time.perf_counter))
    with pytest.raises(RuntimeError,match='no request reserved'):
        mod.begin_external('cannot_renew',scope='r1i',query='invented',dates='2019-01-01~2019-12-31')
    state=mod.ledger().read()
    assert len(state['attempts'])==1 and state['attempts'][0]['terminal'] is False
    assert state['used']['new_body_bytes']==0
    rec=mod.finish_external(ticket,b'failure body',failed=True)
    assert rec['status']=='FAILED' and rec['byte_count']==12
    assert not (mod.OUT/'network.lock').exists()


@pytest.mark.archived_source
def test_recovery_preserved_original_consumption_and_terminal_records():
    before_path=ROOT/'reports/m6_review/incidents/budget_after_concurrent_stop.json'
    after_path=ROOT/'data/raw_m6/budget.json'
    if not before_path.exists() or not after_path.exists():
        pytest.skip('Original incident/shared collection ledger unavailable; no real-incident PASS')
    before=json.loads(before_path.read_text('utf-8'))
    after=json.loads(after_path.read_text('utf-8'))
    event=after['recovery_events'][0]
    assert before['stopped'] is True and before['stop_reason']=='UNRESOLVED_INFLIGHT_REQUEST'
    assert len(before['attempts'])==7 and all(r['terminal'] is True for r in before['attempts'])
    assert event['previous_sha256']==hashlib.sha256(before_path.read_bytes()).hexdigest()
    assert before['attempts']==after['attempts'][:7]
    assert before['limits']==after['limits'] and before['scope_limits']==after['scope_limits']
    assert before['used']==event['used_unchanged']==dict(http_attempts=7,baostock_wire_attempts=0,new_body_bytes=199093)
    assert sum(r['byte_count'] for r in before['attempts'])==199093
    row=before['attempts'][6]
    assert row['byte_count']==27803
    elapsed=(datetime.fromisoformat(row['ingested_at'])-datetime.fromisoformat(row['started_at'])).total_seconds()
    assert elapsed==pytest.approx(39.610676)
    assert row['elapsed_seconds']<1  # original faulty timing retained, not silently overwritten
