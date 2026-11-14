"""Bounded evidence collection for equity admission, never a strategy dataset.

This intentionally lives beside, and does not alter, the sealed R1 adapter.
All market queries have explicit <= 2024 dates. Vendor revisions are not PIT.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import date
import hashlib
import importlib.metadata
import io
import json
import socket
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from quant_research.providers.baostock import canonical, utc_now, write_immutable

END = "2024-12-31"
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"


def validate_query(query):
    kind = query.get("kind")
    schemas = {"universe": {"day"}, "industry": {"code", "date"},
               "history": {"code", "start_date", "end_date"},
               "adjust": {"code", "start_date", "end_date"},
               "dividend": {"code", "year", "yearType"},
               "profit": {"code", "year", "quarter"},
               "balance": {"code", "year", "quarter"},
               "cashflow": {"code", "year", "quarter"}}
    if kind not in schemas or set(query) != schemas[kind] | {"kind"}:
        raise ValueError("Explicit exact query schema required")
    for key in ("day", "date", "start_date", "end_date"):
        if key in query:
            value = query[key]
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value or value > END:
                raise ValueError("Final holdout locked; explicit date <=2024-12-31 required")
    if "start_date" in query and query["start_date"] > query["end_date"]:
        raise ValueError("Ordered dates required")
    if "year" in query and (not isinstance(query["year"], int) or not 1990 <= query["year"] <= 2023):
        # A 2024 annual report is normally published in the sealed 2025 period.
        raise ValueError("Financial/action probe year must be <=2023")
    if "quarter" in query and query["quarter"] not in (1, 2, 3, 4):
        raise ValueError("Invalid quarter")
    if "yearType" in query and query["yearType"] != "operate":
        raise ValueError("Use explicit operation year")
    if "code" in query:
        import re
        if not re.fullmatch(r"(?:sh|sz)\.\d{6}", query["code"]):
            raise ValueError("Explicit security code required")


def inspect_records(query, fields, rows):
    """Validate response scope and discard unsolicited sealed-period records.

    Hashing is forensic only. Returned post-cutoff values are never persisted or
    exposed to the research process. updateDate is NOT an effective/public date.
    """
    validate_query(query)
    if len(fields) != len(set(fields)) or any(len(row) != len(fields) for row in rows):
        raise ValueError("Invalid response shape")
    required = {"history": set(FIELDS.split(",")), "universe": {"code", "tradeStatus", "code_name"},
                "industry": {"code", "industry", "industryClassification", "updateDate"},
                "dividend": {"code", "dividOperateDate", "dividCashPsBeforeTax"},
                "adjust": {"code", "dividOperateDate", "adjustFactor"},
                "profit": {"code", "pubDate", "statDate", "netProfit"},
                "balance": {"code", "pubDate", "statDate"},
                "cashflow": {"code", "pubDate", "statDate"}}[query["kind"]]
    if not required.issubset(fields):
        raise ValueError("Missing required response fields")
    accepted, rejected = [], []
    keys = set()
    for row in rows:
        record = dict(zip(fields, row))
        dates = [v for k, v in record.items() if (k.lower().endswith("date") or k == "date") and v]
        if any(len(v) >= 10 and v[:4].isdigit() and v[:10] > END for v in dates):
            rejected.append(row)
            continue
        if "code" in query and record.get("code") != query["code"]:
            raise ValueError("Security mismatch")
        if query["kind"] == "industry" and record["updateDate"] > query["date"]:
            raise ValueError("Industry snapshot later than requested as-of")
        if query["kind"] == "history":
            if not query["start_date"] <= record["date"] <= query["end_date"] or record.get("adjustflag") != "3":
                raise ValueError("History range/raw price mismatch")
        if query["kind"] in {"universe", "industry", "history", "profit", "balance", "cashflow"}:
            key = (record["code"], record.get("date", record.get("statDate", record.get("updateDate"))))
            if key in keys:
                raise ValueError("Duplicate response economic key")
            keys.add(key)
        accepted.append(row)
    return accepted, {"unsolicited_post_cutoff_rows_discarded": len(rejected),
                      "discarded_rows_sha256": hashlib.sha256(canonical(rejected)).hexdigest() if rejected else None}


def sdk_worker(config):
    query = config["query"]
    validate_query(query)
    sys.path.insert(0, config["sdk_path"])
    logs = io.StringIO()
    result = {"status": "FAILED", "fields": [], "rows": []}
    sdk = None
    logged_in = False
    with redirect_stdout(logs), redirect_stderr(logs):
        try:
            version = importlib.metadata.version("baostock")
            if version != "0.9.4":
                raise ValueError("Pinned SDK 0.9.4 required")
            import baostock as sdk
            root = Path(sdk.__file__).parent
            hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.py"))}
            result.update(sdk_version=version, sdk_source_sha256=hashlib.sha256(canonical(hashes)).hexdigest())
            socket.setdefaulttimeout(10)
            login = sdk.login()
            result["login_code"] = login.error_code
            if login.error_code != "0":
                raise RuntimeError("Login failed: " + login.error_msg)
            logged_in = True
            time.sleep(1)
            kind = query["kind"]
            params = {k: v for k, v in query.items() if k != "kind"}
            names = {"universe": "query_all_stock", "history": "query_history_k_data_plus",
                     "industry": "query_stock_industry", "dividend": "query_dividend_data",
                     "adjust": "query_adjust_factor", "profit": "query_profit_data",
                     "balance": "query_balance_data", "cashflow": "query_cash_flow_data"}
            if kind == "history":
                params.update(fields=FIELDS, frequency="d", adjustflag="3")
            response = getattr(sdk, names[kind])(**params)
            result.update(error_code=response.error_code, error_msg=response.error_msg, fields=list(response.fields))
            rows = []
            while response.error_code == "0":
                prior_page = response.cur_page_num
                boundary = len(response.data) == int(response.per_page_count) and response.cur_row_num >= len(response.data)
                if not response.next():
                    if boundary and response.cur_page_num == prior_page and response.error_code == "0":
                        raise RuntimeError("Ambiguous page termination")
                    break
                rows.append(response.get_row_data())
                if len(rows) > 30000:
                    raise RuntimeError("Bounded 30000 row ceiling exceeded")
            accepted, rejection = inspect_records(query, result["fields"], rows)
            result.update(rows=accepted, **rejection)
            result["status"] = ("REJECTED_POST_CUTOFF_RESPONSE" if rejection["unsolicited_post_cutoff_rows_discarded"]
                                else ("SUCCESS" if response.error_code == "0" else "FAILED"))
        except Exception as exc:
            result.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        finally:
            if sdk and logged_in:
                try:
                    time.sleep(1)
                    sdk.logout()
                except Exception as exc:
                    result["logout_error"] = str(exc)
    result["sdk_diagnostics"] = logs.getvalue()[-3000:]
    return result


def fetch_http(output, label, url, method="GET", body=None, role="HISTORICAL_DOCUMENT_AUDIT"):
    """Append-only HTTP original bytes and every success/failure diagnostic."""
    output = Path(output)
    started = utc_now()
    record = {"id": label, "url": url, "method": method, "request_body": body,
              "role": role, "requested_at": started, "available_at": None,
              "vendor_first_seen_at": None, "performance_evidence": False}
    request = Request(url, data=body.encode("utf-8") if body is not None else None, method=method,
                      headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/",
                               "Content-Type": "application/x-www-form-urlencoded"})
    try:
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise RuntimeError("20MB ceiling exceeded")
            digest = hashlib.sha256(raw).hexdigest()
            path = output / "http" / (label + "_" + digest + ".bin")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(raw)
            record.update(status="FETCHED" if response.status == 200 else "HTTP_ERROR", http_status=response.status,
                          content_type=response.headers.get("Content-Type"), raw_path=path.as_posix(),
                          sha256=digest, byte_count=len(raw))
    except Exception as exc:
        record.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    record["ingested_at"] = utc_now()
    path = output / "http_manifests" / (label + "_" + hashlib.sha256(canonical(record)).hexdigest() + ".json")
    write_immutable(path, record)
    return record
