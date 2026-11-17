"""Bounded metadata-only probe. Never grants research admission or emits credentials."""
import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys


def read_license(path):
    lines = [x.strip() for x in Path(path).read_text(encoding="utf-8-sig").splitlines()
             if x.strip() and not x.lstrip().startswith("#")]
    if len(lines) != 1:
        raise ValueError("CONFIG_REQUIRES_ONE_VALUE")
    value = re.sub(r"^(?:export\s+)?(?:RQDATA_LICENSE|RQDATAC_LICENSE|RQSDK_LICENSE|LICENSE|license)\s*=\s*", "", lines[0])
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    # A raw base64 license may contain '='. Do not treat it as a shell assignment.
    if not value or re.search(r"\s|[;`$]", value) or value.startswith("rqdata://"):
        raise ValueError("CONFIG_EXPECTS_RAW_LICENSE_OR_NAMED_LICENSE")
    return value


def safe_failure(exc):
    message = str(exc).lower()
    if "education network" in message or "campus" in message:
        return "EDUCATION_NETWORK_REQUIRED"
    if "expired" in message:
        return "LICENSE_EXPIRED"
    if "permission" in message or "denied" in message:
        return "PERMISSION_DENIED"
    if "timed out" in message or "timeout" in message:
        return "NETWORK_TIMEOUT"
    if "config_" in message:
        return "LOCAL_CONFIGURATION_INVALID"
    return "AUTHENTICATION_OR_SDK_ERROR"


def safe_quota(quota):
    if not isinstance(quota, dict):
        raise ValueError("QUOTA_METADATA_INVALID")
    cleaned = {}
    for name in ("bytes_limit", "bytes_used", "remaining_days"):
        value = quota.get(name)
        lower = -1 if name == "remaining_days" else 0
        if type(value) is not int or value < lower:
            raise ValueError("QUOTA_METADATA_INVALID")
        cleaned[name] = value
    kind = quota.get("license_type")
    cleaned["license_type"] = kind if kind in ("TRIAL", "FULL", "EDU", "EDUCATION") else "UNKNOWN"
    return cleaned


def probe(credential_file, sdk_path, receipt_path):
    out = Path(receipt_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = dict(schema_version=1, purpose="ACCESS_METADATA_ONLY", data_origin="REAL",
                  started_at=datetime.now(timezone.utc).isoformat(), status="STARTED",
                  sdk_init_attempts=0, explicit_quota_attempts=0,
                  sdk_internal_requests=None, wire_bytes=None, market_financial_requests=0,
                  actual_r2_accounts=0, historical_capability="NOT_TESTED",
                  applicable_use="NOT_VERIFIED", performance_metrics=None)
    # Exclusive creation prevents an accidental repeated request and preserves interruption evidence.
    with out.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    try:
        key = read_license(credential_file)
        sys.path.insert(0, str(Path(sdk_path).resolve()))
        # Do not inherit a proxy/alternate account or scan any account store.
        for name in ("RQDATAC_PROXY", "RQDATAC_CONF", "RQDATAC2_CONF"):
            os.environ.pop(name, None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import rqdatac
            result["sdk_version"] = rqdatac.__version__
            result["sdk_init_attempts"] = 1
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            # License init already requests user.get_quota; it does not query the trading calendar.
            rqdatac.init("license", key, connect_timeout=8, timeout=15,
                         auto_load_plugins=False, enable_bjse=False)
            result["authentication"] = "PASSED"
            result["explicit_quota_attempts"] = 1
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            quota = rqdatac.user.get_quota()
            result["quota"] = safe_quota(quota)
            result["status"] = "ACCESS_METADATA_PASSED_NOT_DATA_ADMISSION"
    except Exception as exc:
        result["status"] = "BLOCKED_ACCESS_OR_LICENSE"
        result["failure_code"] = safe_failure(exc)
        result["authentication"] = result.get("authentication", "NOT_VERIFIED")
        # Never serialize the original exception, which may contain secrets or account identity.
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--sdk-path", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.credential_file, args.sdk_path, args.receipt), ensure_ascii=True))
