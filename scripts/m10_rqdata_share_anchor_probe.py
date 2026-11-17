"""One preregistered PIT-share query; max three observed RPC attempts.

No strategy, event-history, industry-history, or admission entry. Run only with
the matching M10 follow-up plan and remaining cross-host budget.
"""
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

PARAMS = dict(order_book_ids=["000002.XSHE", "600028.XSHG", "000725.XSHE", "600519.XSHG", "002857.XSHE"],
    fields=["total_shares", "total_a_shares", "paid_in_capital", "equity_preferred_stock", "treasury_stock"],
    start_quarter="2019q4", end_quarter="2020q2", date="2020-07-31", statements="all")


def run(credential_file, sdk_path, output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    result = dict(task="M10_SOURCE_ACTIVATION_V1", purpose="FIXED_FIVE_ID_PIT_SHARE_ANCHOR_ONLY",
        started_at=datetime.now(timezone.utc).isoformat(), status="STARTED", rpc_execute_attempts=0,
        rpc_attempt_cap=3, financial_attempts=0, request=PARAMS, source_request_count_exact=None,
        wire_bytes=None, actual_r2_accounts=0, full_sample_admission=False)
    receipt = root / "receipt.json"
    def save():
        receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    save()
    stage = "LOCAL_CONFIGURATION"
    try:
        key = read_license(credential_file)
        sys.path.insert(0, str(Path(sdk_path).resolve()))
        for name in ("RQDATAC_PROXY", "RQDATAC_CONF", "RQDATAC2_CONF"):
            os.environ.pop(name, None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import rqdatac
            from rqdatac.thread_local import ThreadLocalConnection
            original = ThreadLocalConnection._execute
            def counted(self, conn, method, args, kwargs):
                if result["rpc_execute_attempts"] >= 3:
                    raise RuntimeError("LOCAL_RPC_BUDGET_STOP")
                result["rpc_execute_attempts"] += 1
                save()
                return original(self, conn, method, args, kwargs)
            ThreadLocalConnection._execute = counted
            stage = "SDK_INITIALIZATION"
            rqdatac.init("license", key, connect_timeout=8, timeout=15,
                         auto_load_plugins=False, enable_bjse=False)
            result["authentication"] = "PASSED"
            stage = "QUOTA"
            result["quota_before"] = safe_quota(rqdatac.user.get_quota())
            q = result["quota_before"]
            if q["remaining_days"] == 0 or q["bytes_limit"] - q["bytes_used"] < 1024 * 1024:
                raise RuntimeError("LOCAL_QUOTA_STOP")
            stage = "FIXED_PIT_SHARE_ANCHOR"
            result["financial_attempts"] = 1
            save()
            frame = rqdatac.get_pit_financials_ex(**copy.deepcopy(PARAMS))
            raw = b"null" if frame is None else frame.to_json(
                orient="split", date_format="iso", double_precision=15).encode()
            if len(raw) > 1024 * 1024:
                raise RuntimeError("LOCAL_BYTES_STOP")
            (root / "raw.json").write_bytes(raw)
            result.update(status="RETURNED_NOT_ADMITTED", rows=0 if frame is None else len(frame),
                columns=[] if frame is None else list(frame.columns),
                source_payload_hash=hashlib.sha256(raw).hexdigest(), saved_bytes=len(raw),
                serialization="SDK_DATAFRAME_JSON_SPLIT_NOT_WIRE_PAYLOAD")
    except Exception as exc:
        code = str(exc) if str(exc) in ("LOCAL_RPC_BUDGET_STOP", "LOCAL_QUOTA_STOP", "LOCAL_BYTES_STOP") else safe_failure(exc)
        result.update(status="STOPPED_NOT_ADMITTED", failure_stage=stage, failure_code=code)
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
