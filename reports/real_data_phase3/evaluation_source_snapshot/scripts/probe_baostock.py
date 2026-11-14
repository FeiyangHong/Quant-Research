"""Fixed pre-2025 BaoStock samples; NOT_DATASET_GATE and no performance claims.

Requires separately installed optional baostock==0.9.4. Uses the documented
anonymous login; never accepts user credentials or downloads/installs code.
Run from the repository root. Each decoded result and failure is hashed and
saved locally. SDK output and raw rows are never printed to the terminal.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import socket
import sys


EXPECTED_VERSION = "0.9.4"
QUERY_IDS = ["calendar_20231201_20231208", "etf_510300_20231201_20231208",
             "all_etf_20231201", "delisted_512320_20240301_20240308", "master_512320"]


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot(output, label, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = output / (label + "_" + digest + ".json")
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Existing content-addressed snapshot has different bytes")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"sha256": digest, "snapshot_path": str(path.resolve()), "bytes": len(raw)}


def run(output, timeout=12):
    output.mkdir(parents=True, exist_ok=True)
    summary = {"status": "NOT_DATASET_GATE", "performance_evidence": False,
               "started_at": now(), "python": platform.python_version(),
               "expected_baostock_version": EXPECTED_VERSION, "baostock_version": None,
               "credential_mode": "documented_default_anonymous", "user_credentials_used": False,
               "endpoint": "public-api.baostock.com:10030", "socket_timeout_seconds": timeout,
               "historical_queries_end_before": "2025-01-01", "probes": []}
    manifest_path = output / ("probe_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")

    def record(item, payload=None):
        item.update(snapshot(output, item["id"], payload if payload is not None else item))
        summary["probes"].append(item)

    def query(label, function, has_rows=True):
        started = now()
        sdk_output = io.StringIO()
        rows, fields = [], []
        error_code, error_msg = None, None
        try:
            with redirect_stdout(sdk_output), redirect_stderr(sdk_output):
                result = function()
                error_code, error_msg = result.error_code, result.error_msg
                fields = list(result.fields)
                if has_rows and error_code == "0":
                    while result.next():
                        row = result.get_row_data()
                        for column in ("date", "calendar_date"):
                            if column in fields and row[fields.index(column)] >= "2025-01-01":
                                raise ValueError("Unexpected holdout date in historical response")
                        rows.append(row)
                    # Pagination can fail after an initially successful response.
                    error_code, error_msg = result.error_code, result.error_msg
            item = {"id": label, "requested_at": started,
                    "status": "RETURNED" if error_code == "0" else "FAILED",
                    "error_code": error_code, "error_msg": error_msg,
                    "rows": len(rows), "fields": fields}
        except Exception as exc:
            item = {"id": label, "requested_at": started, "status": "FAILED",
                    "error_type": type(exc).__name__, "error": str(exc), "rows": len(rows)}
        payload = {"metadata": dict(item), "fields": fields, "rows": rows,
                   "error_code": error_code, "error_msg": error_msg,
                   "sdk_diagnostics": sdk_output.getvalue(),
                   "snapshot_format": "Decoded SDK response; not original network wire bytes"}
        record(item, payload)
        return item

    bs = None
    login_attempted = False
    previous_timeout = socket.getdefaulttimeout()
    try:
        summary["baostock_version"] = importlib.metadata.version("baostock")
        if summary["baostock_version"] != EXPECTED_VERSION:
            raise RuntimeError("Expected optional baostock==0.9.4; use an isolated environment")
        import baostock as bs
        socket.setdefaulttimeout(timeout)
        login_attempted = True
        login = query("login", lambda: bs.login(), has_rows=False)
        if login.get("error_code") == "0":
            functions = [
                lambda: bs.query_trade_dates(start_date="2023-12-01", end_date="2023-12-08"),
                lambda: bs.query_history_k_data_plus("sh.510300", "date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus", start_date="2023-12-01", end_date="2023-12-08", frequency="d", adjustflag="3"),
                lambda: bs.query_daily_history_k_ETF(date="2023-12-01"),
                lambda: bs.query_history_k_data_plus("sh.512320", "date,code,open,high,low,close,volume,amount", start_date="2024-03-01", end_date="2024-03-08", frequency="d", adjustflag="3"),
                lambda: bs.query_stock_basic(code="sh.512320"),
            ]
            for label, function in zip(QUERY_IDS, functions):
                query(label, function)
        else:
            for label in QUERY_IDS:
                record({"id": label, "status": "SKIPPED", "reason": "anonymous_login_failed"})
    except Exception as exc:
        record({"id": "setup", "status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
        completed = {item["id"] for item in summary["probes"]}
        for label in QUERY_IDS:
            if label not in completed:
                record({"id": label, "status": "SKIPPED", "reason": "setup_failed"})
    finally:
        if bs is not None and login_attempted:
            query("logout", lambda: bs.logout(), has_rows=False)
        socket.setdefaulttimeout(previous_timeout)
        summary["finished_at"] = now()
        summary["manifest_path"] = str(manifest_path.resolve())
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/provider_probes/baostock"))
    parser.add_argument("--timeout", type=float, default=12, help="Socket timeout in seconds, default 12")
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error("timeout must be in (0, 30]")
    result = run(args.output, args.timeout)
    print(json.dumps({"status": result["status"], "baostock_version": result["baostock_version"],
                      "manifest_path": result["manifest_path"],
                      "probes": [{key: item[key] for key in ("id", "status", "error_code", "rows", "sha256", "error_type") if key in item}
                                 for item in result["probes"]]}, ensure_ascii=False))
    return 1 if any(item["status"] == "FAILED" for item in result["probes"]) else 0


if __name__ == "__main__":
    sys.exit(main())
