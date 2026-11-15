"""Non-author durability probes using independent persisted-state assertions."""
import hashlib
import json
import time
import pytest
from quant_research.budget import BudgetLedger, BudgetExceeded

LIMITS={'http_attempts':4,'baostock_wire_attempts':2,'new_body_bytes':5}


def test_actual_overshoot_persisted_and_restart_cannot_continue(tmp_path):
    book=BudgetLedger(tmp_path,LIMITS)
    request=book.begin('http_attempts','six_bytes')
    with pytest.raises(BudgetExceeded):book.finish(request,b'123456',time.perf_counter(),status='RETURNED')
    raw=json.loads((tmp_path/'budget.json').read_text())
    assert raw['used']['new_body_bytes']==6
    assert raw['attempts'][0]['terminal'] is True
    assert raw['attempts'][0]['byte_count']==6 and raw['stopped'] is True
    with pytest.raises(BudgetExceeded):BudgetLedger(tmp_path,LIMITS).begin('http_attempts','restart')
    book.finish(request,b'123456',time.perf_counter(),status='RETURNED')
    assert book.read()['used']['new_body_bytes']==6


def test_legacy_completed_record_is_not_charged_a_second_time(tmp_path):
    payload=b'abc';digest=hashlib.sha256(payload).hexdigest()
    legacy=dict(limits=LIMITS,used={'http_attempts':1,'baostock_wire_attempts':0,'new_body_bytes':3},
        attempts=[dict(id=1,kind='http_attempts',label='old_completed',status='FETCHED',byte_count=3,sha256=digest)])
    (tmp_path/'budget.json').write_text(json.dumps(legacy))
    book=BudgetLedger(tmp_path,LIMITS)
    book.finish(1,payload,time.perf_counter(),status='FETCHED')
    assert book.read()['used']['new_body_bytes']==3


def test_received_bytes_remain_charged_when_object_archive_is_corrupt(tmp_path):
    payload=b'abc';book=BudgetLedger(tmp_path,LIMITS)
    request=book.begin('http_attempts','received_but_unarchivable')
    objects=tmp_path/'objects';objects.mkdir()
    (objects/(hashlib.sha256(payload).hexdigest()+'.bin')).write_bytes(b'wrong')
    with pytest.raises(RuntimeError):book.finish(request,payload,time.perf_counter(),status='FETCHED')
    raw=json.loads((tmp_path/'budget.json').read_text())
    assert raw['used']['new_body_bytes']==3
    assert raw['attempts'][0]['terminal'] is True
    assert raw['stopped'] is True
    with pytest.raises(BudgetExceeded):BudgetLedger(tmp_path,LIMITS).begin('http_attempts','restart')


def test_failed_response_bytes_are_charged_once_and_conflict_stops(tmp_path):
    book=BudgetLedger(tmp_path,LIMITS)
    request=book.begin('http_attempts','partial_response_then_failure')
    book.finish(request,b'ab',time.perf_counter(),status='FAILED',error='socket cut')
    book.finish(request,b'ab',time.perf_counter(),status='FAILED',error='socket cut')
    assert book.read()['used']['new_body_bytes']==2
    with pytest.raises(RuntimeError):book.finish(request,b'abc',time.perf_counter(),status='FAILED')
    assert book.read()['used']['new_body_bytes']==2 and book.read()['stopped']
