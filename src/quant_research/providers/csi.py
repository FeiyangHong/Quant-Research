"""Offline CSI H00300 observations; normalization never admits a PIT Dataset."""
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from .baostock import Query, validate_response, write_immutable
from ..real_data import audit_collection


START, END = "2019-01-01", "2024-12-31"
ENDPOINT = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
            "?indexCode=H00300&startDate=20190101&endDate=20241231")
ABSENT = ["available_at", "published_at", "vendor_first_seen_at", "revision_id", "historical_vintage"]


def _nonfinite(value):
    raise ValueError("Nonfinite JSON number: " + value)


def normalize_payload(content, sessions):
    """Preserve source decimal precision and reject incomplete session coverage."""
    payload = json.loads(content, parse_float=Decimal, parse_constant=_nonfinite)
    if payload.get("code") != "200" or payload.get("success") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("Successful CSI history response required")
    records, excluded, seen = [], [], set()
    for index, row in enumerate(payload["data"]):
        if row.get("indexCode") != "H00300" or row.get("indexNameEnAll") != "CSI 300 Total Return Index":
            raise ValueError("Wrong CSI benchmark identity")
        raw_day = row.get("tradeDate")
        if not isinstance(raw_day, str) or not re.fullmatch(r"[0-9]{8}", raw_day):
            raise ValueError("Invalid CSI tradeDate")
        day = date.fromisoformat(raw_day[:4] + "-" + raw_day[4:6] + "-" + raw_day[6:]).isoformat()
        if not START <= day <= END:
            raise ValueError("CSI observation outside requested window or in locked holdout")
        if day in seen:
            raise ValueError("Duplicate CSI benchmark date")
        seen.add(day)
        try:
            value = row.get("close")
            if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
                raise ValueError("Invalid CSI close")
            value = Decimal(value)
            if not value.is_finite() or value <= 0:
                raise ValueError("Positive finite CSI close required")
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Invalid CSI close") from exc
        observation = {"date": day, "benchmark_id": "H00300", "total_return_index": str(value),
                       "source_row_index": index}
        if day in sessions:
            records.append(observation)
        else:
            excluded.append(dict(observation, reason="NON_TRADING_DAY_IN_VERIFIED_CALENDAR"))
    missing = sessions - seen
    if missing:
        raise ValueError("Missing CSI trading days: " + ", ".join(sorted(missing)))
    if not records:
        raise ValueError("No verified CSI trading observations")
    return sorted(records, key=lambda r: r["date"]), sorted(excluded, key=lambda r: r["date"])


def _calendar_evidence(root):
    audit = audit_collection(root)
    if audit["integrity_status"] != "PASS":
        raise ValueError("Calendar collection integrity failed: " + "; ".join(audit["errors"]))
    evidence = {}

    def read(name, expected):
        path = (root / name).resolve()
        path.relative_to(root)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Calendar evidence hash mismatch: " + name)
        evidence[path.relative_to(root).as_posix()] = content
        return json.loads(content)

    collection = read("collection.json", audit["collection_sha256"])
    read("request_plan.json", audit["request_plan_sha256"])
    candidates = [item for item in collection["query_results"] if item["kind"] == "calendar"
                  and item["start"] <= START and item["end"] >= END]
    if len(candidates) != 1:
        raise ValueError("One verified calendar covering the full CSI request window required")
    item = candidates[0]
    manifest = read(item["manifest_path"], item["manifest_sha256"])
    for attempt in manifest["attempts"]:
        read(attempt["raw_path"], attempt["raw_sha256"])
    payload = read(item["raw_path"], item["raw_sha256"])
    query = Query(**payload["query"])
    query.validate()
    validate_response(query, payload)  # Includes every natural day, not just sessions.
    rows = [dict(zip(payload["fields"], row)) for row in payload["rows"]]
    sessions = {row["calendar_date"] for row in rows if row["is_trading_day"] == "1"
                and START <= row["calendar_date"] <= END}
    return sessions, evidence, audit


def normalize_benchmark(raw, calendar_collection, output, expected_sha256=None):
    """Write a new immutable staging directory only after every check passes."""
    raw, root, output = Path(raw).resolve(), Path(calendar_collection).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Output already exists; use a new immutable staging directory")
    content = raw.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("CSI raw SHA256 mismatch")
    sessions, evidence, audit = _calendar_evidence(root)
    records, excluded = normalize_payload(content, sessions)
    manifest = {"schema_version": "csi-benchmark-staging-1.0", "status": "STAGING_ONLY",
        "synthetic": False, "research_admission": "NOT_DATASET_GATE", "performance_evidence": False,
        "strategy_runs_permitted": False, "pit_eligible": False, "benchmark_id": "H00300",
        "source_endpoint": ENDPOINT, "request_window": {"start": START, "end": END},
        "raw_acquisition": "Previously downloaded HTTP response body; this utility performs no network requests",
        "absent_not_inferred": ABSENT, "record_count": len(records), "excluded_non_session_count": len(excluded),
        "calendar_integrity_status": audit["integrity_status"], "source_files": [], "files": {}}
    snapshots = [("raw/csi_h00300.payload", raw, content)] + [
        ("calendar_evidence/" + name, root / name, value) for name, value in evidence.items()]
    output.mkdir(parents=True)
    for name, source, value in snapshots:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(value)
        sha256 = hashlib.sha256(value).hexdigest()
        manifest["source_files"].append({"source_path": str(source), "snapshot_path": name, "sha256": sha256})
        manifest["files"][name] = sha256
    documents = {"observations.json": {"status": "STAGING_ONLY", "units": "index_points",
        "decimal_encoding": "strings preserve exact source close precision", "records": records},
        "excluded_non_sessions.json": {"records": excluded}, "calendar_audit.json": audit}
    for name, value in documents.items():
        manifest["files"][name] = write_immutable(output / name, value)
    write_immutable(output / "manifest.json", manifest)
    return manifest
