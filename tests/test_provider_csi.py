"""CSI staging normalization uses only local fixture bytes and verified calendars."""
import copy
from datetime import date, timedelta
import hashlib
import json

import pytest

from quant_research.providers.baostock import BaoStockAdapter, Query, write_immutable
from quant_research.providers.csi import END, ENDPOINT, START, normalize_benchmark, normalize_payload


SESSIONS = {"2019-01-02", "2019-01-03"}


def response():
    return {"code": "200", "success": True, "data": [
        {"tradeDate": day, "indexCode": "H00300", "indexNameEnAll": "CSI 300 Total Return Index",
         "close": "3704.620000000000000001"} for day in ("20190101", "20190102", "20190103")]}


def raw_bytes(payload=None):
    # Numeric JSON, deliberately more precise than a binary float can retain.
    return json.dumps(response() if payload is None else payload).replace(
        '"3704.620000000000000001"', "3704.620000000000000001").encode()


def calendar_collection(root, end=END, omit_day=None):
    first, last = date.fromisoformat(START), date.fromisoformat(end)
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    payload = {"status": "SUCCESS", "fields": ["calendar_date", "is_trading_day"],
               "rows": [[day, "1" if day in SESSIONS else "0"] for day in days if day != omit_day]}
    query = Query("calendar", start=START, end=end)
    adapter = BaoStockAdapter(root, worker=lambda *_: copy.deepcopy(payload), min_interval=0)
    item = adapter.collect(query)
    plan_hash = write_immutable(root / "request_plan.json", {"queries": [query.__dict__]})
    write_immutable(root / "collection.json", {"schema_version": "baostock-collection-1.0",
        "synthetic": False, "history_end_cap": END, "request_plan_sha256": plan_hash, "query_results": [item]})
    return item


def test_decimal_exact_observations_exclude_but_log_verified_non_session():
    records, excluded = normalize_payload(raw_bytes(), SESSIONS)
    assert [record["date"] for record in records] == sorted(SESSIONS)
    assert all(record["total_return_index"] == "3704.620000000000000001" for record in records)
    assert excluded == [{"date": "2019-01-01", "benchmark_id": "H00300",
        "total_return_index": "3704.620000000000000001", "source_row_index": 0,
        "reason": "NON_TRADING_DAY_IN_VERIFIED_CALENDAR"}]
    assert all("available_at" not in record and "revision_id" not in record for record in records)


@pytest.mark.parametrize("field,value,reason", [
    ("indexCode", "000300", "identity"),
    ("indexNameEnAll", "CSI 300 Price Index", "identity"),
    ("tradeDate", "20250101", "locked holdout"),
    ("tradeDate", "20181231", "outside requested window"),
    ("tradeDate", "20190230", "day is out of range"),
    ("close", "NaN", "finite"), ("close", "Infinity", "finite"),
    ("close", 0, "finite"), ("close", -1, "finite"),
    ("close", None, "Invalid CSI close"), ("close", True, "Invalid CSI close"),
])
def test_invalid_csi_identity_dates_or_prices_rejected(field, value, reason):
    payload = response()
    payload["data"][1][field] = value
    with pytest.raises(ValueError, match=reason):
        normalize_payload(raw_bytes(payload), SESSIONS)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_constants_rejected(literal):
    content = raw_bytes().replace(b"3704.620000000000000001", literal.encode(), 1)
    with pytest.raises(ValueError, match="Nonfinite JSON number"):
        normalize_payload(content, SESSIONS)


def test_duplicate_non_session_rows_also_rejected():
    payload = response()
    payload["data"].append(copy.deepcopy(payload["data"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_payload(raw_bytes(payload), SESSIONS)


def test_missing_trading_day_rejected():
    payload = response()
    payload["data"].pop()
    with pytest.raises(ValueError, match="Missing CSI trading days: 2019-01-03"):
        normalize_payload(raw_bytes(payload), SESSIONS)


def test_normalization_preserves_raw_and_hashed_calendar_subset_without_admission(tmp_path):
    collection = tmp_path / "calendar"
    item = calendar_collection(collection)
    raw = tmp_path / "csi.payload"
    content = raw_bytes()
    raw.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    output = tmp_path / "staging"
    manifest = normalize_benchmark(raw, collection, output, digest)
    assert manifest["record_count"] == 2 and manifest["excluded_non_session_count"] == 1
    assert manifest["status"] == "STAGING_ONLY" and manifest["calendar_integrity_status"] == "PASS"
    assert manifest["source_endpoint"] == ENDPOINT
    assert manifest["pit_eligible"] is manifest["performance_evidence"] is manifest["strategy_runs_permitted"] is False
    assert {"available_at", "historical_vintage"} <= set(manifest["absent_not_inferred"])
    assert raw.read_bytes() == (output / "raw/csi_h00300.payload").read_bytes() == content
    assert (output / "calendar_evidence" / item["raw_path"]).read_bytes() == (collection / item["raw_path"]).read_bytes()
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    excluded = json.loads((output / "excluded_non_sessions.json").read_bytes())
    assert excluded["records"][0]["source_row_index"] == 0
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError, match="Output already exists"):
        normalize_benchmark(raw, collection, output, digest)
    assert (output / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("problem,reason", [
    ("tampered", "integrity failed"),
    ("omitted-natural-day", "integrity failed"),
    ("short-calendar", "full CSI request window"),
    ("wrong-csi-hash", "CSI raw SHA256 mismatch"),
])
def test_calendar_or_raw_verification_failure_creates_no_output(tmp_path, problem, reason):
    collection = tmp_path / "calendar"
    item = calendar_collection(collection, end="2019-01-03" if problem == "short-calendar" else END,
                               omit_day="2019-01-04" if problem == "omitted-natural-day" else None)
    if problem == "tampered":
        path = collection / item["raw_path"]
        path.write_bytes(path.read_bytes() + b" ")
    raw = tmp_path / "csi.payload"
    raw.write_bytes(raw_bytes())
    output = tmp_path / "staging"
    with pytest.raises(ValueError, match=reason):
        normalize_benchmark(raw, collection, output, "0" * 64 if problem == "wrong-csi-hash" else None)
    assert not output.exists()


def test_standalone_calendar_retains_attempt_lineage_and_validates_raw(tmp_path):
    collection = tmp_path / "calendar"
    item = calendar_collection(collection)
    write_immutable(collection / "calendar_query.json", item)
    raw = tmp_path / "csi.payload"
    raw.write_bytes(raw_bytes())
    output = tmp_path / "standalone"
    manifest = normalize_benchmark(raw, collection, output)
    audit = json.loads((output / "calendar_audit.json").read_bytes())
    assert audit["scope"] == "STANDALONE_CALENDAR_QUERY"
    assert manifest["record_count"] == 2
    # A successful label cannot hide changed original bytes.
    path = collection / item["raw_path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        normalize_benchmark(raw, collection, tmp_path / "tampered")


def test_explicit_earlier_window_preserves_holdout_lock():
    payload = response()
    for row in payload["data"]:
        row["tradeDate"] = row["tradeDate"].replace("2019", "2010")
    sessions = {"2010-01-02", "2010-01-03"}
    records, _ = normalize_payload(raw_bytes(payload), sessions, "2010-01-01", END)
    assert records[0]["date"] == "2010-01-02"
    with pytest.raises(ValueError, match="pre-2025"):
        normalize_payload(raw_bytes(payload), sessions, "2010-01-01", "2025-01-01")
