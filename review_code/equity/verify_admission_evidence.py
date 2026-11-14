"""Offline independent integrity and scope check; never imports a strategy runner."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports/m3_equity_admission"
ARCHIVE = (ROOT / "data/raw_equity_admission").resolve()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def archive_path(value):
    """Resolve immutable producer paths within this checkout, never at F:.

    Original manifests retain their capture-time absolute paths. Only the
    named archive suffix is portable; unrelated or traversing paths fail.
    """
    text = str(value).replace("\\", "/")
    prefix = "data/raw_equity_admission/"
    marker = "/" + prefix
    if text.startswith(prefix):
        relative = text
    elif text.count(marker) == 1:
        relative = prefix + text.split(marker, 1)[1]
    else:
        raise ValueError("Source path is outside the expected equity archive")
    if ".." in relative.split("/") or ":" in relative:
        raise ValueError("Invalid archive path")
    resolved = (ROOT / relative).resolve()
    resolved.relative_to(ARCHIVE)  # Reject escapes, including symlinks.
    return resolved


def main():
    manifest = read(REPORTS / "source_manifest.json")
    hash_errors = []
    manifest_paths = {}
    for obj in manifest["objects"]:
        path = archive_path(obj["path"])
        assert path not in manifest_paths, "Duplicate manifest path"
        manifest_paths[path] = obj["sha256"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != obj["sha256"] or len(raw) != obj["byte_count"]:
            hash_errors.append(obj["path"])
    assert not hash_errors, hash_errors
    calls = []
    for name in ["sdk_probe_manifest.json", "sdk_extra_manifest.json"]:
        calls.extend(read(ROOT / "data/raw_equity_admission" / name)["queries"])
    assert len(calls) == 35
    assert Counter(c["status"] for c in calls) == {"SUCCESS": 34, "TIMEOUT": 1}
    snapshots = []
    for call in calls:
        query = call["query"]
        for key in ["date", "day", "end_date", "start_date"]:
            if key in query:
                assert query[key] <= "2024-12-31"
        if "year" in query:
            assert query["year"] <= 2023
        local_raw = archive_path(call["raw_path"])
        assert manifest_paths.get(local_raw) == call["sha256"], "Unregistered raw object"
        envelope = read(local_raw)
        assert hashlib.sha256(local_raw.read_bytes()).hexdigest() == call["sha256"]
        assert envelope.get("performance_evidence") is False
        assert envelope.get("vendor_first_seen_at") is None
        assert envelope.get("available_at") is None
        if call["status"] != "SUCCESS":
            continue
        rows = [dict(zip(envelope["fields"], row)) for row in envelope["rows"]]
        assert len(rows) == call["row_count"]
        snapshots.append((query, rows))
    histories = [(q, rows) for q, rows in snapshots if q["kind"] == "history"]
    for query, rows in histories:
        assert all(query["start_date"] <= r["date"] <= query["end_date"] for r in rows)
        assert all(r["adjustflag"] == "3" and r["code"] == query["code"] for r in rows)
    leshi = next(rows for q, rows in histories if q["code"] == "sz.300104" and q["start_date"] == "2020-06-01")
    assert len(leshi) == 35 and {r["isST"] for r in leshi} == {"0"}
    assert sum(r["tradestatus"] == "1" for r in leshi) == 30
    zhonghong = next(rows for q, rows in histories if q["code"] == "sz.000979")
    assert zhonghong[-1]["date"] == "2018-12-28" and zhonghong[-1]["tradestatus"] == "0"
    old_pool = next(rows for q, rows in snapshots if q == {"kind": "universe", "day": "2016-01-04"})
    future_names = {r["code"]: r["code_name"] for r in old_pool if r["code"] in {"sz.000979", "sz.300104"}}
    assert all("退" in name for name in future_names.values())
    dividends = next(rows for q, rows in snapshots if q == {"kind": "dividend", "code": "sh.600519", "year": 2023, "yearType": "operate"})
    assert len(dividends) == 1 and dividends[0]["dividCashPsBeforeTax"] == "25.911"
    assert dividends[0]["dividOperateDate"] == "2023-06-30"
    cases = read(REPORTS / "corporate_action_cases.json")
    assert len(cases["events"]) == 2 and cases["events"][1]["cash_per_share_gross"] == "19.106"
    financial = read(REPORTS / "financial_vintage_case.json")
    assert financial["gate_count"] == 1 and financial["validation"]["independent_human_signoff"] is False
    assert financial["original"]["available_at"] < financial["revision"]["available_at"]
    assert financial["revision"]["supersedes_id"] == financial["original"]["revision_id"]
    assert financial["vendor_first_seen_at"] is None
    calendar_root = ROOT / "data/raw_equity_admission/calendars"
    calendars = read(calendar_root / "summary.json")
    assert len(calendars) == 2
    trading_days = []
    for item in calendars:
        assert item["status"] == "SUCCESS" and item["end"] <= "2024-12-31"
        local_raw = archive_path("data/raw_equity_admission/calendars/" + item["raw_path"])
        assert manifest_paths.get(local_raw) == item["raw_sha256"]
        raw = local_raw.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
        envelope = json.loads(raw)
        assert envelope["status"] == "SUCCESS" and len(envelope["rows"]) == item["row_count"]
        trading_days.extend(row[0] for row in envelope["rows"] if row[1] == "1")
    for version in (financial["original"], financial["revision"]):
        next_days = sorted(day for day in trading_days if day > version["published_date"])
        assert version["available_at"] == next_days[0] + "T21:00:00+08:00"
        assert version["earliest_execution"] == next_days[1]
    queue = read(REPORTS / "revision_candidate_queue.json")
    assert len(queue["cases"]) == 20 and queue["passed_case_count"] == 0
    assert all(not c["counts_toward_20_case_gate"] and c["publication_date"] <= "2024-12-31"
               for c in queue["cases"])
    assert len({(c["instrument_id"], c["publication_date"]) for c in queue["cases"]}) == 20
    audit = read(REPORTS / "data_audit.json")
    assert audit["R2_admission"] == audit["R3_admission"] == "BLOCKED"
    assert audit["original_vintage_reconciliation_case_count"] == 1
    assert audit["independently_human_signed_cases"] == 0
    assert audit["matrix"][5]["R3"] == "NOT_REQUIRED_F01_F06"
    http = Counter(r["status"] for r in manifest["http_requests"])
    assert http == {"FETCHED": 49, "FAILED": 2}
    result = dict(status="INTEGRITY_AND_BLOCKED_SCOPE_VERIFIED_NOT_DATA_ADMISSION",
        checked_manifest_objects=len(manifest["objects"]), hash_mismatches=hash_errors,
        stock_calls=dict(Counter(c["status"] for c in calls)), calendar_calls=len(calendars),
        http_calls=dict(http), history_segments=len(histories), history_rows=sum(len(rows) for q, rows in histories),
        old_pool_future_names=future_names, leshi_delisting_period_is_st_values=sorted({r["isST"] for r in leshi}),
        completed_financial_case_count=1, independent_human_signed_cases=0, correction_queue_count=20,
        raw_api_data_cutoff="2024-12-31", real_strategy_runs=0,
        limitations=["Integrity proves bytes and reported scope, not complete issuer/event coverage.",
            "Document hash verification is not independent page-by-page financial signoff.",
            "No contemporaneous vendor first-seen timestamps reconstructed from present ingestion."])
    output = ROOT / "work/equity_independent_admission/evidence_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
