"""Non-author probes: local synthetic credentials and fake SDK only; no network."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "independent_m10_access", REPOSITORY / "scripts" / "m10_rqdata_access.py"
)
ACCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCESS)
FAKE_KEY = "INDEPENDENT_SYNTHETIC_SECRET_NOT_A_REAL_LICENSE"


def sdk(monkeypatch, *, init_error=None, quota_error=None, quota=None):
    calls = []

    def init(*args, **kwargs):
        calls.append(("init", args, kwargs))
        print(FAKE_KEY)
        print(FAKE_KEY, file=sys.stderr)
        if init_error:
            raise init_error

    def get_quota():
        calls.append(("quota",))
        if quota_error:
            raise quota_error
        return quota if quota is not None else {
            "bytes_limit": 200_000_000,
            "bytes_used": 12,
            "remaining_days": 30,
            "license_type": "EDUCATION",
            "credential": FAKE_KEY,
            "identity": "PRIVATE_ACCOUNT_ID",
        }

    monkeypatch.setitem(sys.modules, "rqdatac", SimpleNamespace(
        __version__="independent_fake_sdk", init=init,
        user=SimpleNamespace(get_quota=get_quota),
    ))
    return calls


def run(tmp_path, value):
    credential = tmp_path / "synthetic_input.txt"
    credential.write_text(value, encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    result = ACCESS.probe(credential, tmp_path, receipt)
    return result, receipt


@pytest.mark.parametrize("value", ["", "\n# only a comment\n", 'LICENSE=""',
                                  "LICENSE=first\nLICENSE=second", "LICENSE=$(whoami)",
                                  "LICENSE=abc;whoami", "LICENSE=abc`whoami",
                                  "rqdata://license:fake@host"])
def test_invalid_local_input_never_attempts_authentication(tmp_path, monkeypatch, value):
    calls = sdk(monkeypatch)
    result, _ = run(tmp_path, value)
    assert calls == []
    assert result["sdk_init_attempts"] == 0
    assert result["status"] == "BLOCKED_ACCESS_OR_LICENSE"
    assert result["failure_code"] == "LOCAL_CONFIGURATION_INVALID"


def test_campus_rejection_is_sanitized_not_provider_capability_failure(tmp_path, monkeypatch, capsys):
    calls = sdk(monkeypatch, init_error=PermissionError(
        "this license is only allowed to access through the education network " + FAKE_KEY
    ))
    result, receipt = run(tmp_path, "RQDATA_LICENSE=" + FAKE_KEY)
    assert [call[0] for call in calls] == ["init"]
    assert result["failure_code"] == "EDUCATION_NETWORK_REQUIRED"
    assert result["historical_capability"] == "NOT_TESTED"
    assert result["explicit_quota_attempts"] == 0
    assert FAKE_KEY not in receipt.read_text(encoding="utf-8")
    emitted = capsys.readouterr()
    assert FAKE_KEY not in emitted.out + emitted.err


def test_success_is_metadata_only_and_unknown_payload_keys_do_not_escape(tmp_path, monkeypatch, capsys):
    calls = sdk(monkeypatch)
    result, receipt = run(tmp_path, FAKE_KEY)
    assert [call[0] for call in calls] == ["init", "quota"]
    assert calls[0][1] == ("license", FAKE_KEY)
    assert calls[0][2]["auto_load_plugins"] is False
    assert result["status"] == "ACCESS_METADATA_PASSED_NOT_DATA_ADMISSION"
    assert result["market_financial_requests"] == 0
    assert result["actual_r2_accounts"] == 0
    assert result["historical_capability"] == "NOT_TESTED"
    assert result["applicable_use"] == "NOT_VERIFIED"
    assert result["performance_metrics"] is None
    assert result["sdk_internal_requests"] is None
    content = receipt.read_text(encoding="utf-8")
    assert FAKE_KEY not in content and "PRIVATE_ACCOUNT_ID" not in content
    emitted = capsys.readouterr()
    assert FAKE_KEY not in emitted.out + emitted.err


def test_existing_receipt_blocks_before_any_second_request(tmp_path, monkeypatch):
    calls = sdk(monkeypatch)
    _, receipt = run(tmp_path, FAKE_KEY)
    original = receipt.read_bytes()
    count = len(calls)
    with pytest.raises(FileExistsError):
        ACCESS.probe(tmp_path / "missing_input.txt", tmp_path, receipt)
    assert len(calls) == count
    assert receipt.read_bytes() == original


def test_quota_failure_preserves_actual_auth_progress_without_secret(tmp_path, monkeypatch, capsys):
    calls = sdk(monkeypatch, quota_error=RuntimeError("permission denied " + FAKE_KEY))
    result, receipt = run(tmp_path, FAKE_KEY)
    assert [call[0] for call in calls] == ["init", "quota"]
    assert result["authentication"] == "PASSED"
    assert result["explicit_quota_attempts"] == 1
    assert result["status"] == "BLOCKED_ACCESS_OR_LICENSE"
    assert FAKE_KEY not in receipt.read_text(encoding="utf-8")
    emitted = capsys.readouterr()
    assert FAKE_KEY not in emitted.out + emitted.err


@pytest.mark.parametrize("field", ["license_type", "bytes_limit", "bytes_used", "remaining_days"])
def test_unexpected_sensitive_value_in_allowlisted_metadata_cannot_be_published(tmp_path, monkeypatch, field):
    quota = {"bytes_limit": 200_000_000, "bytes_used": 0,
             "remaining_days": 10, "license_type": "EDUCATION"}
    quota[field] = FAKE_KEY
    sdk(monkeypatch, quota=quota)
    _, receipt = run(tmp_path, FAKE_KEY)
    assert FAKE_KEY not in receipt.read_text(encoding="utf-8")


def test_actual_receipt_does_not_imply_historical_admission():
    evidence = json.loads((REPOSITORY / "reports" / "m10_activation" / "ACCESS_RECEIPT.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "BLOCKED_ACCESS_OR_LICENSE"
    assert evidence["failure_code"] == "EDUCATION_NETWORK_REQUIRED"
    assert evidence["sdk_init_attempts"] == 1
    assert evidence["explicit_quota_attempts"] == 0
    assert evidence["market_financial_requests"] == 0
    assert evidence["actual_r2_accounts"] == 0
    assert evidence["historical_capability"] == "NOT_TESTED"
    assert evidence["sdk_internal_requests"] is None
    assert evidence["wire_bytes"] is None
