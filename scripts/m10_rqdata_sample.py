"""Fixed M10 source samples only; raw responses remain local, no strategy entry."""
import argparse
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from m10_rqdata_access import read_license, safe_failure, safe_quota

FIELDS = ["net_profit_parent_company", "cash_flow_from_operating_activities", "total_assets"]
CASES = [
    ("600518.XSHG", "2017q4", ["2018-04-25", "2018-04-27", "2019-05-06"]),
    ("002857.XSHE", "2023q3", ["2023-10-25", "2023-10-27", "2024-12-26"]),
    ("002729.XSHE", "2022q3", ["2022-10-28", "2022-11-01", "2024-12-12"]),
    ("300632.XSHE", "2022q4", ["2023-04-21", "2023-04-24", "2024-12-24"]),
]
SHARE_IDS = ["000002.XSHE", "600028.XSHG", "000725.XSHE", "600519.XSHG", "002857.XSHE"]


def requests():
    specs = []
    for security, quarter, dates in CASES:
        for phase, date in zip(["before", "original", "corrected", "repeat_original"], dates + [dates[1]]):
            specs.append({"id": security[:6] + "_" + phase, "endpoint": "get_pit_financials_ex",
                          "params": dict(order_book_ids=[security], fields=FIELDS.copy(), start_quarter=quarter,
                                         end_quarter=quarter, date=date, statements="all", market="cn")})
    for security, start, end, date in [("600518.XSHG", "2016q4", "2017q4", "2018-04-27"),
                                        ("002857.XSHE", "2022q3", "2023q3", "2023-10-27")]:
        specs.append({"id": security[:6] + "_warmup", "endpoint": "get_pit_financials_ex",
                      "params": dict(order_book_ids=[security], fields=FIELDS.copy(), start_quarter=start,
                                     end_quarter=end, date=date, statements="all", market="cn")})
    for date in ["2020-07-31", "2015-12-30"]:
        specs.append({"id": "identity_" + date, "endpoint": "all_instruments",
                      "params": dict(type="CS", date=date, market="cn")})
    specs.append({"id": "shares_2020", "endpoint": "get_shares", "params": dict(
        order_book_ids=SHARE_IDS, start_date="2020-07-31", end_date="2020-07-31",
        fields=["total", "total_a", "preferred_shares"], expect_df=True, market="cn")})
    for date in ["2016-01-04", "2020-07-31"]:
        specs.append({"id": "industry_" + date, "endpoint": "get_instrument_industry", "params": dict(
            order_book_ids=SHARE_IDS, source="citics", level=1, date=date, market="cn")})
    for endpoint in ["is_st_stock", "is_suspended"]:
        specs.append({"id": endpoint + "_kangmei", "endpoint": endpoint, "params": dict(
            order_book_ids=["600518.XSHG"], start_date="2019-05-13", end_date="2019-05-31", market="cn")})
    specs.append({"id": "moutai_dividends_2022", "endpoint": "get_dividend", "params": dict(
        order_book_ids=["600519.XSHG"], start_date="2022-01-01", end_date="2022-12-31",
        adjusted=False, expect_df=True, market="cn")})
    return specs


def validate_request(spec):
    p = spec["params"]
    dates = [p[k] for k in ["date", "start_date", "end_date"] if k in p]
    if not dates or any(not isinstance(d, str) or not "2010-01-01" <= d <= "2024-12-31" for d in dates):
        raise ValueError("EXPLICIT_PRE2025_DATES_REQUIRED")
    if spec["endpoint"] == "get_pit_financials_ex" and (
        p.get("statements") != "all" or p.get("fields") != FIELDS or
        not "2010q1" <= p["start_quarter"] <= p["end_quarter"] <= "2024q4"
    ):
        raise ValueError("FIXED_FINANCIAL_CONTRACT_REQUIRED")


def run(credential_file, sdk_path, output):
    specs = requests()
    for spec in specs:
        validate_request(spec)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    result = dict(purpose="FIXED_CAPABILITY_SAMPLE_NOT_STRATEGY", started_at=datetime.now(timezone.utc).isoformat(),
                  status="STARTED", actual_r2_accounts=0, market_financial_attempts=0, sdk_init_attempts=0,
                  explicit_quota_attempts=0, rpc_execute_attempts=0, wire_requests=None, wire_bytes=None,
                  saved_response_bytes=0, request_results=[], performance_metrics=None, human_acceptances=0)
    receipt = root / "receipt.json"

    def save():
        receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    save()
    (root / "request_plan.json").write_text(json.dumps(specs, indent=2) + "\n", encoding="utf-8")
    stage = "LOCAL_CONFIGURATION"
    try:
        key = read_license(credential_file)
        for name in ("RQDATAC_PROXY", "RQDATAC_CONF", "RQDATAC2_CONF"):
            os.environ.pop(name, None)
        sys.path.insert(0, str(Path(sdk_path).resolve()))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import rqdatac
            from rqdatac.thread_local import ThreadLocalConnection
            original_execute = ThreadLocalConnection._execute

            def counted_execute(self, conn, method, args, kwargs):
                if result["rpc_execute_attempts"] >= 33:
                    raise RuntimeError("LOCAL_RPC_BUDGET_STOP")
                result["rpc_execute_attempts"] += 1
                save()
                return original_execute(self, conn, method, args, kwargs)

            ThreadLocalConnection._execute = counted_execute
            stage = "SDK_INITIALIZATION"
            result["sdk_init_attempts"] = 1
            save()
            rqdatac.init("license", key, connect_timeout=8, timeout=15, auto_load_plugins=False, enable_bjse=False)
            result["authentication"] = "PASSED"
            stage = "QUOTA"
            result["explicit_quota_attempts"] += 1
            result["quota_before"] = safe_quota(rqdatac.user.get_quota())
            q = result["quota_before"]
            if q["bytes_limit"] > 0 and q["bytes_limit"] - q["bytes_used"] < 10 * 1024 * 1024:
                raise RuntimeError("INSUFFICIENT_SAMPLE_QUOTA")
            for spec in specs:
                stage = spec["id"]
                entry = dict(spec, status="STARTED", source_payload_hash=None, filing_document_hash=None)
                result["request_results"].append(entry)
                result["market_financial_attempts"] += 1
                save()
                frame = getattr(rqdatac, spec["endpoint"])(**copy.deepcopy(spec["params"]))
                # Caller field lists may be mutated by the SDK; freeze the original plan above.
                raw = b"null" if frame is None else frame.to_json(orient="split", date_format="iso", double_precision=15).encode("utf-8")
                if result["saved_response_bytes"] + len(raw) > 10 * 1024 * 1024:
                    raise RuntimeError("LOCAL_SAVED_RESPONSE_BUDGET_STOP")
                (root / "raw" / (spec["id"] + ".json")).write_bytes(raw)
                result["saved_response_bytes"] += len(raw)
                entry.update(status="RETURNED", rows=0 if frame is None else len(frame),
                             source_payload_hash=hashlib.sha256(raw).hexdigest(), saved_bytes=len(raw),
                             serialization="SDK_DATAFRAME_JSON_SPLIT_NOT_WIRE_PAYLOAD")
                save()
            stage = "QUOTA_AFTER"
            result["explicit_quota_attempts"] += 1
            result["quota_after"] = safe_quota(rqdatac.user.get_quota())
            result["status"] = "SAMPLE_RETURNED_PENDING_SEMANTIC_VALIDATION"
    except Exception as exc:
        code = safe_failure(exc)
        local_code = str(exc) if str(exc) in (
            "LOCAL_RPC_BUDGET_STOP", "LOCAL_SAVED_RESPONSE_BUDGET_STOP", "INSUFFICIENT_SAMPLE_QUOTA"
        ) else None
        status = "PARTIAL_BUDGET_STOP" if local_code else "BLOCKED_ACCESS_OR_LICENSE"
        result.update(status=status, failure_stage=stage, failure_code=local_code or code)
        result["failure_is_proven_access_denial"] = code in (
            "EDUCATION_NETWORK_REQUIRED", "LICENSE_EXPIRED", "PERMISSION_DENIED"
        )
        if result["request_results"] and result["request_results"][-1]["status"] == "STARTED":
            result["request_results"][-1]["status"] = "FAILED"
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--sdk-path", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.credential_file, args.sdk_path, args.output)
