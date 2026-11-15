"""Bounded, append-only BaoStock collection without a mandatory SDK dependency.

Every attempt runs in a separate process: a socket timeout alone cannot stop
the upstream SDK's receive loop if a peer closes without a terminator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date as Date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Optional
import uuid


SDK_VERSION = "0.9.4"
HISTORY_END = "2024-12-31"
HISTORY_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"
NETWORK_CODES = {"10002001", "10002002", "10002003", "10002004", "10002005", "10002006", "10002007", "10002008"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_immutable(path: Path, value: Any) -> str:
    payload = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError("Immutable snapshot path already contains different bytes: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Query:
    kind: str
    code: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    date: Optional[str] = None

    def validate(self) -> None:
        if self.kind not in {"history", "calendar", "universe", "master"}:
            raise ValueError("Unsupported query kind")
        for value in (self.start, self.end, self.date):
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("Explicit ISO dates required")
                Date.fromisoformat(value)
                if value > HISTORY_END:
                    raise ValueError("Final holdout is locked: query dates must be <=2024-12-31")
        if self.kind in {"history", "calendar"} and (not self.start or not self.end or self.start > self.end):
            raise ValueError("Explicit ordered start/end required")
        if self.kind == "universe" and not self.date:
            raise ValueError("Explicit universe snapshot date required")
        if self.kind in {"history", "master"} and (not self.code or not re.fullmatch(r"(?:sh|sz)\.\d{6}", self.code)):
            raise ValueError("Explicit exchange-prefixed security code required")
        allowed = {"history": {"code", "start", "end"}, "calendar": {"start", "end"},
                   "universe": {"date"}, "master": {"code"}}[self.kind]
        if any(value is not None and key not in allowed for key, value in asdict(self).items() if key != "kind"):
            raise ValueError("Unexpected parameter for query kind")


def validate_response(query: Query, payload: dict) -> None:
    """Fail closed on a partial, mis-keyed, duplicated or out-of-range response."""
    fields, rows = payload["fields"], payload["rows"]
    if len(fields) != len(set(fields)):
        raise ValueError("Duplicate response fields")
    if any(len(row) != len(fields) for row in rows):
        raise ValueError("Response row width mismatch")
    required = {"history": set(HISTORY_FIELDS.split(",")), "calendar": {"calendar_date", "is_trading_day"},
                "universe": {"date", "code", "open", "high", "low", "close", "volume", "amount", "tradestatus"},
                "master": {"code", "code_name", "ipoDate", "outDate", "type", "status"}}[query.kind]
    if not required.issubset(fields):
        raise ValueError("Missing required response fields: " + str(sorted(required - set(fields))))
    keys = set()
    for row in rows:
        record = dict(zip(fields, row))
        if query.kind != "master":
            day = record["calendar_date" if query.kind == "calendar" else "date"]
            if Date.fromisoformat(day).isoformat() != day or day > HISTORY_END:
                raise ValueError("Response contains invalid/holdout date")
            lower, upper = (query.date, query.date) if query.kind == "universe" else (query.start, query.end)
            if not lower <= day <= upper:
                raise ValueError("Response outside requested dates")
        else:
            day = "current_metadata_not_PIT"
        if query.code and record.get("code") != query.code:
            raise ValueError("Response has a different security code")
        if query.kind == "history" and record["adjustflag"] != "3":
            raise ValueError("Adjusted observations returned for raw-price request")
        key = (day, record.get("code", "calendar"))
        if key in keys:
            raise ValueError("Duplicate response economic key")
        keys.add(key)
    if query.kind == "calendar":
        start, end = Date.fromisoformat(query.start), Date.fromisoformat(query.end)
        expected = {(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)}
        if {key[0] for key in keys} != expected:
            raise ValueError("Calendar response omits requested natural days")
        if any(dict(zip(fields, row))["is_trading_day"] not in {"0", "1"} for row in rows):
            raise ValueError("Unknown calendar trading flag")


def run_worker(config: dict, timeout: float) -> dict:
    command = [sys.executable, str(Path(__file__).with_name("_baostock_worker.py"))]
    options = {"input": canonical(config), "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
               "timeout": timeout, "check": False}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.run(command, **options)
    except subprocess.TimeoutExpired as exc:
        return {"status": "TIMEOUT", "retryable": True, "error_type": "WorkerWallTimeout",
                "error": f"Worker exceeded {timeout:g} seconds and was killed; no response accepted",
                "stdout_bytes": len(exc.stdout or b""), "stderr_bytes": len(exc.stderr or b""), "fields": [], "rows": []}
    try:
        response = json.loads(process.stdout)
        if process.returncode != 0 and response.get("status") == "SUCCESS":
            raise ValueError("Worker exited nonzero after reporting success")
        return response
    except (ValueError, TypeError):
        return {"status": "FAILED", "retryable": False, "error_type": "InvalidWorkerResponse",
                "error": "Worker did not return valid JSON", "returncode": process.returncode,
                "stderr": process.stderr.decode("utf-8", errors="replace")[-4000:], "fields": [], "rows": []}


class BaoStockAdapter:
    def __init__(self, output_dir, sdk_path=None, timeout=20.0, max_retries=1, min_interval=1.0,
                 worker=None, sleeper=time.sleep, clock=time.monotonic):
        if not 0 < timeout <= 60 or max_retries not in {0, 1, 2} or not 0 <= min_interval <= 30:
            raise ValueError("Invalid timeout/retry/interval limits")
        self.output_dir = Path(output_dir).resolve()
        self.sdk_path = str(Path(sdk_path).resolve()) if sdk_path else None
        self.timeout, self.max_retries, self.min_interval = timeout, max_retries, min_interval
        self.worker, self.sleeper, self.clock = worker or run_worker, sleeper, clock
        self.last_request = None
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def collect(self, query: Query) -> dict:
        query.validate()  # Before worker creation and therefore before login/network.
        request_id = hashlib.sha256(canonical(asdict(query))).hexdigest()[:16] + "_" + uuid.uuid4().hex[:10]
        attempts, selected = [], None
        for attempt in range(self.max_retries + 1):
            if self.last_request is not None:
                delay = self.min_interval - (self.clock() - self.last_request)
                if delay > 0:
                    self.sleeper(delay)
            self.last_request = self.clock()
            started = utc_now()
            payload = self.worker({"query": asdict(query), "sdk_path": self.sdk_path,
                                   "socket_timeout": min(12, self.timeout), "min_interval": self.min_interval}, self.timeout)
            payload.update(query=asdict(query), requested_at=started, ingested_at=utc_now(),
                           source="BaoStock", expected_sdk_version=SDK_VERSION,
                           snapshot_format="Decoded SDK records and diagnostics, not original wire bytes")
            if payload.get("status") == "SUCCESS":
                try:
                    validate_response(query, payload)
                except (ValueError, TypeError, KeyError) as exc:
                    payload.update(status="RESPONSE_REJECTED", retryable=False, error_type=type(exc).__name__, error=str(exc))
            payload_hash = hashlib.sha256(canonical(payload)).hexdigest()
            raw_path = Path("raw") / (request_id + f"_a{attempt}_" + payload_hash + ".json")
            write_immutable(self.output_dir / raw_path, payload)
            item = {"attempt": attempt + 1, "status": payload["status"], "raw_path": raw_path.as_posix(),
                    "raw_sha256": payload_hash, "row_count": len(payload.get("rows", [])),
                    "error_code": payload.get("error_code"), "error_type": payload.get("error_type"),
                    "retryable": payload.get("retryable", False)}
            attempts.append(item)
            selected = item
            if payload["status"] == "SUCCESS" or not payload.get("retryable"):
                break
            if attempt < self.max_retries:
                self.sleeper(min(2 ** attempt, 4))
        manifest = {"schema_version": "baostock-query-1.0", "query": asdict(query), "request_id": request_id,
                    "status": selected["status"], "research_admission": "NOT_DATASET_GATE",
                    "performance_evidence": False, "expected_sdk_version": SDK_VERSION,
                    "parameters": {"worker_wall_timeout": self.timeout, "max_retries": self.max_retries,
                                   "minimum_request_interval": self.min_interval}, "attempts": attempts,
                    "selected_attempt": selected["attempt"], "raw_path": selected["raw_path"],
                    "raw_sha256": selected["raw_sha256"], "row_count": selected["row_count"]}
        manifest_path = Path("manifests") / (request_id + ".json")
        manifest_hash = write_immutable(self.output_dir / manifest_path, manifest)
        return dict(asdict(query), status=manifest["status"], manifest_path=manifest_path.as_posix(),
                    manifest_sha256=manifest_hash, raw_path=manifest["raw_path"], raw_sha256=manifest["raw_sha256"],
                    row_count=manifest["row_count"], attempt_count=len(attempts))


def normalize_history(payload: dict) -> dict:
    """Parse observations without inventing limits, TR, events or availability.

    Prices/amount are decimal strings to preserve exact source precision;
    volume is an exact integer. Every row survives, with parse issues recorded.
    """
    if payload.get("status") != "SUCCESS":
        raise ValueError("Only successful validated responses may be normalized")
    query = Query(**payload["query"])
    if query.kind not in {"history", "universe"}:
        raise ValueError("History/universe response required")
    validate_response(query, payload)
    records = []
    for values in payload["rows"]:
        raw = dict(zip(payload["fields"], values))
        issues = []
        record = {"date": raw["date"], "instrument_id": raw["code"], "source": "BaoStock",
                  "ingested_at": payload["ingested_at"], "source_trade_status": raw.get("tradestatus"),
                  "suspended": {"0": True, "1": False}.get(raw.get("tradestatus")),
                  "source_adjustflag": raw.get("adjustflag"), "raw_row": raw}
        for column in ("open", "high", "low", "close", "preclose", "volume", "amount"):
            value = raw.get(column)
            try:
                number = Decimal(value) if value not in {None, ""} else None
                if number is None or not number.is_finite() or number < 0:
                    raise ValueError("missing/invalid/nonfinite/negative")
                if column == "volume":
                    if number != number.to_integral_value():
                        raise ValueError("fractional volume")
                    record[column] = int(number)
                else:
                    record[column] = str(number)
                if column in {"open", "high", "low", "close"} and number == 0:
                    issues.append(column + ":zero_price")
            except (InvalidOperation, ValueError, TypeError):
                record[column] = None
                issues.append(column + ":missing_or_invalid")
        if record["suspended"] is None:
            issues.append("trade_status:unknown")
        zero = record["volume"] == 0 and record["amount"] is not None and Decimal(record["amount"]) == 0
        record["zero_turnover"] = zero
        record["observation_state"] = "SUSPENDED" if record["suspended"] is True else ("ZERO_TURNOVER" if zero else ("NORMAL" if record["suspended"] is False else "UNKNOWN"))
        if record["suspended"] is True and (record["volume"] not in {None, 0} or (record["amount"] is not None and Decimal(record["amount"]) != 0)):
            issues.append("trade_status:suspension_turnover_conflict")
        record["normalization_issues"] = issues
        record["normalization_status"] = "QUARANTINED" if issues else "PARSED_OBSERVATION"
        records.append(record)
    return {"schema_version": "baostock-observations-1.0", "status": "STAGING_ONLY",
            "units": {"price": "CNY", "amount": "CNY", "volume": "fund_units_or_shares"},
            "decimal_encoding": "strings preserve exact provider precision; volume integer",
            "absent_not_inferred": ["available_at", "published_at", "vendor_first_seen_at", "upper_limit", "lower_limit", "total_return_index", "corporate_actions"],
            "records": records}
