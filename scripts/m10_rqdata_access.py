"""Bounded metadata-only probe. Never grants research admission or emits credentials."""
import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
import math
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
    if message == "quota_metadata_invalid":
        return "QUOTA_METADATA_INVALID"
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


def quota_shape(quota):
    """Describe only fixed metadata keys and builtin scalars, never arbitrary text."""
    if type(quota) is not dict:
        return {"container": "UNEXPECTED"}
    shape = {}
    for name in ("bytes_limit", "bytes_used", "remaining_days"):
        value = quota.get(name)
        kind = {int: "INT", float: "FLOAT", str: "TEXT", type(None): "MISSING_OR_NULL", bool: "BOOL"}.get(type(value), "OTHER")
        item = {"kind": kind}
        if type(value) is int and -(2 ** 63) <= value < 2 ** 63:
            item["numeric_value"] = value
        elif type(value) is float:
            item["finite"] = math.isfinite(value)
            item["integral"] = math.isfinite(value) and value.is_integer()
            if math.isfinite(value) and -(2 ** 63) <= value < 2 ** 63:
                item["numeric_value"] = value
        shape[name] = item
    return shape


def safe_quota(quota):
    if not isinstance(quota, dict):
        raise ValueError("QUOTA_METADATA_INVALID")
    cleaned = {}
    for name in ("bytes_limit", "bytes_used", "remaining_days"):
        value = quota.get(name)
        lower = -1 if name == "remaining_days" else 0
        # The real education response uses a float for bytes_limit. Accept only
        # exactly integral, finite builtin numerics; never coerce text or bool.
        if type(value) is float and math.isfinite(value) and value.is_integer():
            value = int(value)
        if type(value) is not int or not lower <= value < 2 ** 63:
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
    stage = "LOCAL_CONFIGURATION"
    try:
        key = read_license(credential_file)
        sys.path.insert(0, str(Path(sdk_path).resolve()))
        # Do not inherit a proxy/alternate account or scan any account store.
        for name in ("RQDATAC_PROXY", "RQDATAC_CONF", "RQDATAC2_CONF"):
            os.environ.pop(name, None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            stage = "SDK_IMPORT"
            import rqdatac
            result["sdk_version"] = rqdatac.__version__
            result["sdk_init_attempts"] = 1
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            # License init already requests user.get_quota; it does not query the trading calendar.
            stage = "SDK_INITIALIZATION"
            rqdatac.init("license", key, connect_timeout=8, timeout=15,
                         auto_load_plugins=False, enable_bjse=False)
            result["authentication"] = "PASSED"
            result["explicit_quota_attempts"] = 1
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            stage = "QUOTA_REQUEST"
            quota = rqdatac.user.get_quota()
            stage = "QUOTA_VALIDATION"
            result["quota_metadata_shape"] = quota_shape(quota)
            result["quota"] = safe_quota(quota)
            result["status"] = "ACCESS_METADATA_PASSED_NOT_DATA_ADMISSION"
    except Exception as exc:
        result["status"] = "BLOCKED_ACCESS_OR_LICENSE"
        result["failure_code"] = safe_failure(exc)
        result["failure_stage"] = stage
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
