"""Provider boundary tests: no network and no optional SDK dependency."""
from dataclasses import asdict
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from quant_research.providers import baostock as provider
from quant_research.providers.baostock import BaoStockAdapter, Query, normalize_history, validate_response, write_immutable


def response(day="2023-12-01", code="sh.510300"):
    fields = provider.HISTORY_FIELDS.split(",")
    row = {"date": day, "code": code, "open": "3.5610", "high": "3.5670", "low": "3.5190",
           "close": "3.5480", "preclose": "3.5620", "volume": "860468131", "amount": "3046328676.0000",
           "adjustflag": "3", "turn": "1.88", "tradestatus": "1", "pctChg": "-0.39", "isST": "0"}
    return {"status": "SUCCESS", "retryable": False, "fields": fields, "rows": [[row[f] for f in fields]],
            "error_code": "0", "query": asdict(Query("history", code=code, start="2023-12-01", end="2023-12-08")),
            "ingested_at": "2026-11-14T16:00:00+00:00"}


@pytest.mark.parametrize("query", [
    Query("history", "sh.510300", "2023-01-01", "2025-01-01"),
    Query("universe", date="2025-01-01"),
    Query("history", "sh.510300", "2024-01-01", None),
    Query("history", "sh.510300", "2024-01-02", "2024-01-01"),
    Query("history", "510300", "2024-01-01", "2024-01-02"),
    Query("universe"), Query("master", "sh.510300", end="2024-12-31"),
])
def test_invalid_or_holdout_query_never_reaches_worker(tmp_path, query):
    called = []
    adapter = BaoStockAdapter(tmp_path, worker=lambda *args: called.append(args))
    with pytest.raises(ValueError):
        adapter.collect(query)
    assert called == []


def test_exact_volume_decimal_precision_and_no_invented_fields():
    normalized = normalize_history(response())
    row = normalized["records"][0]
    assert row["volume"] == 860468131
    assert type(row["volume"]) is int
    assert row["amount"] == "3046328676.0000"
    assert row["open"] == "3.5610"
    assert row["suspended"] is False and row["observation_state"] == "NORMAL"
    assert not {"available_at", "total_return_index", "upper_limit", "lower_limit"}.intersection(row)


@pytest.mark.parametrize("status,volume,amount,expected_suspended,expected_state", [
    ("0", "0", "0.0000", True, "SUSPENDED"),
    ("1", "0", "0.0000", False, "ZERO_TURNOVER"),
    ("", "", "", None, "UNKNOWN"),
])
def test_suspension_zero_turnover_and_missing_remain_distinct(status, volume, amount, expected_suspended, expected_state):
    payload = response()
    for key, value in {"tradestatus": status, "volume": volume, "amount": amount}.items():
        payload["rows"][0][payload["fields"].index(key)] = value
    row = normalize_history(payload)["records"][0]
    assert row["suspended"] is expected_suspended
    assert row["observation_state"] == expected_state
    if status == "":
        assert row["volume"] is None and row["amount"] is None
        assert row["normalization_status"] == "QUARANTINED"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0.5", "not-a-number"])
def test_invalid_volume_is_retained_and_flagged(bad):
    payload = response()
    payload["rows"][0][payload["fields"].index("volume")] = bad
    normalized = normalize_history(payload)
    assert len(normalized["records"]) == 1
    row = normalized["records"][0]
    assert row["volume"] is None
    assert row["raw_row"]["volume"] == bad
    assert row["normalization_status"] == "QUARANTINED"


@pytest.mark.parametrize("mutate", [
    lambda p: p["rows"][0].__setitem__(0, "2025-01-01"),
    lambda p: p["rows"][0].__setitem__(0, "2023-12-09"),
    lambda p: p["rows"][0].__setitem__(1, "sh.512320"),
    lambda p: p["rows"][0].__setitem__(p["fields"].index("adjustflag"), "2"),
    lambda p: p["rows"].append(list(p["rows"][0])),
    lambda p: p["rows"][0].pop(),
])
def test_bad_provider_response_saved_but_never_admitted(tmp_path, mutate):
    payload = response()
    mutate(payload)
    adapter = BaoStockAdapter(tmp_path, worker=lambda *_: copy.deepcopy(payload))
    result = adapter.collect(Query(**response()["query"]))
    assert result["status"] == "RESPONSE_REJECTED"
    assert result["attempt_count"] == 1
    raw = (tmp_path / result["raw_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result["raw_sha256"]
    assert json.loads(raw)["rows"] == payload["rows"]
    with pytest.raises(ValueError):
        normalize_history(json.loads(raw))


def test_transient_retry_preserves_failed_attempt_and_success(tmp_path):
    answers = iter([{"status": "TIMEOUT", "retryable": True, "fields": [], "rows": []}, response()])
    sleeps = []
    adapter = BaoStockAdapter(tmp_path, worker=lambda *_: copy.deepcopy(next(answers)), sleeper=sleeps.append,
                             clock=lambda: 0.0, max_retries=1, min_interval=1)
    result = adapter.collect(Query(**response()["query"]))
    assert result["status"] == "SUCCESS" and result["attempt_count"] == 2
    manifest = json.loads((tmp_path / result["manifest_path"]).read_bytes())
    assert [row["status"] for row in manifest["attempts"]] == ["TIMEOUT", "SUCCESS"]
    assert sleeps and all(value >= 1 for value in sleeps)


def test_unknown_or_rate_limit_failure_is_not_retried(tmp_path):
    calls = []
    def worker(*args):
        calls.append(args)
        return {"status": "FAILED", "retryable": False, "error_code": "10001005", "fields": [], "rows": []}
    result = BaoStockAdapter(tmp_path, worker=worker, max_retries=2).collect(Query(**response()["query"]))
    assert result["status"] == "FAILED" and len(calls) == 1


def test_immutable_snapshots_cannot_be_replaced(tmp_path):
    path = tmp_path / "snapshot.json"
    first = write_immutable(path, {"code": "sh.512320", "status": "retired"})
    assert first == write_immutable(path, {"code": "sh.512320", "status": "retired"})
    with pytest.raises(FileExistsError):
        write_immutable(path, {"code": "sh.512320", "status": "removed"})


def test_parent_deadline_kills_worker_even_if_socket_layer_hangs(monkeypatch):
    real_run = subprocess.run
    def run_hanging_child(command, **kwargs):
        # Real subprocess deadline, without contacting a provider or importing SDK.
        return real_run([sys.executable, "-c", "import time; time.sleep(5)"], **kwargs)
    monkeypatch.setattr(provider.subprocess, "run", run_hanging_child)
    started = time.monotonic()
    result = provider.run_worker({}, timeout=0.1)
    assert time.monotonic() - started < 3
    assert result["status"] == "TIMEOUT"
    assert result["error_type"] == "WorkerWallTimeout"
    assert result["rows"] == []
