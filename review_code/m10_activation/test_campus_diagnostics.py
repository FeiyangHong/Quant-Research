"""Non-author offline diagnostics: synthetic values only, no real SDK or key."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "campus_independent_access", ROOT / "scripts" / "m10_rqdata_access.py"
)
ACCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCESS)
SECRET = "REVIEWER_SYNTHETIC_SECRET_NEVER_REAL"


def test_shape_excludes_text_unknown_keys_and_arbitrary_object_metadata():
    class Sensitive:
        def __repr__(self):
            return SECRET

    result = ACCESS.quota_shape({
        "bytes_limit": SECRET, "bytes_used": Sensitive(), "remaining_days": True,
        SECRET: SECRET, "license_type": SECRET,
    })
    assert result == {
        "bytes_limit": {"kind": "TEXT"},
        "bytes_used": {"kind": "OTHER"},
        "remaining_days": {"kind": "BOOL"},
    }
    assert SECRET not in json.dumps(result)
    assert ACCESS.quota_shape([SECRET]) == {"container": "UNEXPECTED"}


@pytest.mark.parametrize("value,expected", [
    (-1, {"kind": "INT", "numeric_value": -1}),
    (2 ** 63, {"kind": "INT"}),
    (float("inf"), {"kind": "FLOAT", "finite": False, "integral": False}),
    (float("nan"), {"kind": "FLOAT", "finite": False, "integral": False}),
])
def test_shape_values_are_finite_bounded_metadata(value, expected):
    result = ACCESS.quota_shape({"bytes_limit": value})
    assert result["bytes_limit"] == expected
    json.dumps(result, allow_nan=False)


def test_integral_float_quota_normalizes_without_granting_other_permissions():
    result = ACCESS.safe_quota({
        "bytes_limit": 123456789.0, "bytes_used": 0.0,
        "remaining_days": 286.0, "license_type": "EDU",
        "private_identity": SECRET,
    })
    assert result == {"bytes_limit": 123456789, "bytes_used": 0,
                      "remaining_days": 286, "license_type": "EDU"}
    assert all(type(result[k]) is int for k in (
        "bytes_limit", "bytes_used", "remaining_days"))


@pytest.mark.parametrize("value", [True, "123456789", SECRET, -1, -1.0,
                                  0.5, float("inf"), float("nan"), 2 ** 63,
                                  float(2 ** 63)])
def test_quota_mapping_refuses_unproven_numeric_forms(value):
    with pytest.raises(ValueError, match="^QUOTA_METADATA_INVALID$"):
        ACCESS.safe_quota({"bytes_limit": value, "bytes_used": 0,
                           "remaining_days": 286, "license_type": "EDU"})


@pytest.mark.parametrize("mode,stage,code", [
    ("initialization", "SDK_INITIALIZATION", "EDUCATION_NETWORK_REQUIRED"),
    ("quota_request", "QUOTA_REQUEST", "PERMISSION_DENIED"),
    ("quota_schema", "QUOTA_VALIDATION", "QUOTA_METADATA_INVALID"),
])
def test_real_progress_is_distinguished_without_exception_disclosure(
        tmp_path, monkeypatch, capsys, mode, stage, code):
    calls = []

    def initialize(*args, **kwargs):
        calls.append("init")
        print(SECRET)
        if mode == "initialization":
            raise PermissionError("education network " + SECRET)

    def quota():
        calls.append("quota")
        print(SECRET, file=sys.stderr)
        if mode == "quota_request":
            raise PermissionError("permission denied " + SECRET)
        return {"bytes_limit": -1, "bytes_used": SECRET,
                "remaining_days": 10, "license_type": SECRET}

    monkeypatch.setitem(sys.modules, "rqdatac", SimpleNamespace(
        __version__="synthetic_sdk", init=initialize,
        user=SimpleNamespace(get_quota=quota),
    ))
    credential = tmp_path / "synthetic.txt"
    credential.write_text(SECRET, encoding="utf-8")
    receipt = tmp_path / "new_receipt.json"
    result = ACCESS.probe(credential, tmp_path, receipt)
    assert result["failure_stage"] == stage
    assert result["failure_code"] == code
    assert result["authentication"] == (
        "NOT_VERIFIED" if mode == "initialization" else "PASSED")
    assert calls == (["init"] if mode == "initialization" else ["init", "quota"])
    assert result["status"] == "BLOCKED_ACCESS_OR_LICENSE"
    assert result["historical_capability"] == "NOT_TESTED"
    assert result["actual_r2_accounts"] == result["market_financial_requests"] == 0
    assert "quota" not in result
    emitted = capsys.readouterr()
    assert SECRET not in receipt.read_text(encoding="utf-8") + emitted.out + emitted.err
