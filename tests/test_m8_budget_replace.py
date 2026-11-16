"""Transient Windows sharing failures must not resend or double-charge requests."""
import json
import time

import pytest

from quant_research import budget


def sharing_error():
    error = PermissionError('simulated Windows replacement sharing conflict')
    error.winerror = 5
    return error


def test_transient_replace_retries_same_snapshot_without_double_charge(tmp_path, monkeypatch):
    book = budget.BudgetLedger(tmp_path, dict(http_attempts=3, baostock_wire_attempts=2, new_body_bytes=100))
    idx = book.begin('http_attempts', 'invented_request')
    original, calls, sleeps = budget.os.replace, [], []
    def flaky(source, destination):
        calls.append(str(source))
        if len(calls) <= 2:
            raise sharing_error()
        return original(source, destination)
    monkeypatch.setattr(budget.os, 'replace', flaky)
    monkeypatch.setattr(budget.time, 'sleep', sleeps.append)
    book.finish(idx, b'abcdef', time.perf_counter(), status='FETCHED')
    snapshot = book.read()
    assert len(calls) == 3 and len(set(calls)) == 1 and sleeps == [.05, .05]
    assert snapshot['used']['http_attempts'] == 1 and snapshot['used']['new_body_bytes'] == 6
    assert snapshot['attempts'][0]['terminal'] is True
    book.finish(idx, b'abcdef', time.perf_counter(), status='FETCHED')
    assert book.read()['used']['new_body_bytes'] == 6


def test_persistent_replace_failure_is_bounded_and_keeps_request_inflight(tmp_path, monkeypatch):
    book = budget.BudgetLedger(tmp_path, dict(http_attempts=3, baostock_wire_attempts=2, new_body_bytes=100))
    idx = book.begin('http_attempts', 'invented_request')
    calls, sleeps = [], []
    def fail(source, destination):
        calls.append(1)
        raise sharing_error()
    monkeypatch.setattr(budget.os, 'replace', fail)
    monkeypatch.setattr(budget.time, 'sleep', sleeps.append)
    with pytest.raises(PermissionError):
        book.finish(idx, b'abcdef', time.perf_counter(), status='FETCHED')
    assert len(calls) == 21 and len(sleeps) == 20
    snapshot = json.loads((tmp_path / 'budget.json').read_bytes())
    assert snapshot['attempts'][0]['status'] == 'INFLIGHT'
    # A new collector cannot silently continue past this unresolved response.
    monkeypatch.undo()
    with pytest.raises(budget.BudgetExceeded, match='unresolved inflight'):
        budget.BudgetLedger(tmp_path, book.limits).begin('http_attempts', 'must_not_send')
