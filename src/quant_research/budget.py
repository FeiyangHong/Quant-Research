"""Durable bounded source collection; never estimates unobserved transport bytes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(obj, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_lock(path, timeout=50):
    """An abandoned lock fails closed. Never steals another process's lease."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Collection lock unavailable; fail closed: ' + str(path))
            time.sleep(.05)
    try:
        os.write(descriptor, (str(os.getpid()) + ' ' + now()).encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink()


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    @staticmethod
    def is_terminal(rec):
        return rec.get('terminal') is True or ('terminal' not in rec and
            rec.get('status') not in (None, 'INFLIGHT') and
            'sha256' in rec and 'byte_count' in rec)

    def __init__(self, root, limits, *, scope_limits=None):
        self.root = Path(root)
        self.path = self.root / 'budget.json'
        self.limits = dict(limits)
        self.scope_limits = scope_limits or {}

    @contextmanager
    def transaction(self):
        with exclusive_lock(self.root / 'budget.lock'):
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data['limits'] != self.limits:
                    raise RuntimeError('Registered budget limits differ; fail closed')
                if data.get('scope_limits', {}) != self.scope_limits:
                    raise RuntimeError('Registered scope budgets differ; fail closed')
            else:
                data = dict(registered_at=now(), limits=self.limits,
                            scope_limits=self.scope_limits, used=dict.fromkeys(self.limits, 0),
                            attempts=[], stopped=False, stop_reason=None,
                            byte_semantics='HTTP bodies and decoded UTF-8 SDK responses, not wire transport bytes')
                atomic_json(self.path, data)
            yield data

    def read(self):
        with self.transaction() as data:
            return data

    def _stop(self, data, reason):
        data.update(stopped=True, stop_reason=reason, stopped_at=now())
        atomic_json(self.path, data)

    def begin(self, kind, label, *, scope=None, **extra):
        if kind not in ('http_attempts', 'baostock_wire_attempts'):
            raise ValueError('Unknown attempt kind')
        if self.scope_limits and scope not in self.scope_limits:
            raise ValueError('Registered collector scope required')
        with self.transaction() as data:
            if data.get('stopped'):
                raise BudgetExceeded('Budget exhausted/stopped: ' + str(data.get('stop_reason')))
            if data['used'][kind] >= self.limits[kind] or data['used']['new_body_bytes'] >= self.limits['new_body_bytes']:
                self._stop(data, 'GLOBAL_LIMIT_EXHAUSTED')
                raise BudgetExceeded('Budget exhausted before request')
            if any(not self.is_terminal(a) for a in data['attempts']):
                self._stop(data, 'UNRESOLVED_INFLIGHT_REQUEST')
                raise BudgetExceeded('Budget exhausted/stopped: unresolved inflight request')
            if scope:
                rows = [a for a in data['attempts'] if a.get('scope') == scope]
                used = sum(a['kind'] == kind for a in rows)
                byte_count = sum(a.get('byte_count', 0) for a in rows)
                cap = self.scope_limits[scope]
                if used >= cap.get(kind, 0) or byte_count >= cap['new_body_bytes']:
                    raise BudgetExceeded('Scope budget exhausted before request: ' + scope)
            rec = dict(extra, id=len(data['attempts']) + 1, kind=kind, label=label,
                       scope=scope, started_at=now(), terminal=False, status='INFLIGHT')
            data['used'][kind] += 1
            data['attempts'].append(rec)
            atomic_json(self.path, data)
            return rec['id']

    def remaining(self, scope=None):
        data = self.read()
        result = self.limits['new_body_bytes'] - data['used']['new_body_bytes']
        if scope:
            result = min(result, self.scope_limits[scope]['new_body_bytes'] - sum(
                a.get('byte_count', 0) for a in data['attempts'] if a.get('scope') == scope))
        return max(0, result)

    def finish(self, idx, payload, started, *, status, **extra):
        payload = bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        with self.transaction() as data:
            if not isinstance(idx, int) or idx < 1 or idx > len(data['attempts']):
                raise ValueError('Unknown request identity')
            rec = data['attempts'][idx - 1]
            if self.is_terminal(rec):
                if rec['sha256'] == digest and rec.get('response_status',rec['status']) == status:
                    return rec
                self._stop(data, 'CONFLICTING_DUPLICATE_FINISH')
                raise RuntimeError('Conflicting duplicate finish; original accounting retained')
            path = self.root / 'objects' / (digest + '.bin')
            failure=None
            reserved={'id','kind','scope','label','started_at','terminal','byte_count','sha256',
                      'raw_path','ingested_at','elapsed_seconds','response_status'}
            if reserved.intersection(extra) or status not in {'FETCHED','FAILED','RETURNED','TRUNCATED_BUDGET'}:
                failure=ValueError('Reserved request identity or invalid terminal status')
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    with path.open('xb') as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise RuntimeError('Existing object hash conflict')
            except Exception as error:
                failure=error
            rec.update({k:v for k,v in extra.items() if k not in reserved})
            rec.update(terminal=True, status='FAILED_STORAGE_OR_METADATA' if failure else status,
                       response_status=status, byte_count=len(payload), sha256=digest,
                       raw_path=None if failure else str(path.resolve()), ingested_at=now(),
                       elapsed_seconds=round(max(0, time.perf_counter()-started), 6))
            if failure:rec.update(terminal_error=type(failure).__name__+': '+str(failure),attempted_raw_path=str(path.resolve()))
            data['used']['new_body_bytes'] += len(payload)
            over = data['used']['new_body_bytes'] > self.limits['new_body_bytes']
            if rec.get('scope'):
                scoped = sum(a.get('byte_count', 0) for a in data['attempts'] if a.get('scope') == rec['scope'])
                over = over or scoped > self.scope_limits[rec['scope']]['new_body_bytes']
            if over or status == 'TRUNCATED_BUDGET' or data['used']['new_body_bytes'] >= self.limits['new_body_bytes']:
                data.update(stopped=True, stop_reason='BODY_BYTE_LIMIT_REACHED', stopped_at=now())
            if failure:
                data.update(stopped=True,stop_reason='RESPONSE_STORAGE_OR_METADATA_FAILURE',stopped_at=now())
            atomic_json(self.path, data)  # actual consumption and terminal status BEFORE raising
            if failure:raise RuntimeError('Response received and charged, but terminal storage/metadata failure: '+str(failure)) from failure
            if over:
                raise BudgetExceeded('Body byte cap breached; actual bytes and terminal state persisted')
            return rec
