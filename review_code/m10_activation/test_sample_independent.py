"""Independent fixed-sample contract tests; fake SDK and synthetic bytes only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "independent_sample", ROOT / "scripts" / "m10_rqdata_sample.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)
SECRET = "INDEPENDENT_SYNTHETIC_VALUE_NOT_REAL"


def test_plan_retains_registered_difficult_cases_and_explicit_pre2025_dates():
    specs = SAMPLE.requests()
    assert len(specs) == len({s["id"] for s in specs}) == 26
    expected = {
        "600518": ("2017q4", ["2018-04-25", "2018-04-27", "2019-05-06", "2018-04-27"]),
        "002857": ("2023q3", ["2023-10-25", "2023-10-27", "2024-12-26", "2023-10-27"]),
        "002729": ("2022q3", ["2022-10-28", "2022-11-01", "2024-12-12", "2022-11-01"]),
        "300632": ("2022q4", ["2023-04-21", "2023-04-24", "2024-12-24", "2023-04-24"]),
    }
    for code, (quarter, dates) in expected.items():
        selected = [s["params"] for s in specs if s["id"].startswith(code) and not s["id"].endswith("warmup")]
        assert [p["date"] for p in selected] == dates
        assert all(p["start_quarter"] == p["end_quarter"] == quarter for p in selected)
    for spec in specs:
        SAMPLE.validate_request(spec)
        params = spec["params"]
        assert "date" in params or {"start_date", "end_date"} <= params.keys()
        assert all(v <= "2024-12-31" for k, v in params.items() if k in ("date", "start_date", "end_date"))


@pytest.mark.parametrize("date", [None, "2025-01-01"])
def test_latest_and_holdout_requests_are_rejected(date):
    spec = SAMPLE.requests()[0]
    if date is None:
        del spec["params"]["date"]
    else:
        spec["params"]["date"] = date
    with pytest.raises(ValueError, match="EXPLICIT_PRE2025_DATES_REQUIRED"):
        SAMPLE.validate_request(spec)


def test_partial_result_is_preserved_and_denial_stops_without_secret(tmp_path, monkeypatch, capsys):
    calls = []

    class Connection:
        def _execute(self, conn, method, args, kwargs):
            return None

    original = Connection._execute
    monkeypatch.setattr(Connection, "_execute", original)

    class Frame:
        def to_json(self, **kwargs):
            return '{"synthetic": 17}'

        def __len__(self):
            return 1

    def financial(**kwargs):
        calls.append(kwargs["date"])
        kwargs["fields"].append("sdk_mutation")
        print(SECRET)
        if len(calls) == 2:
            raise PermissionError("permission denied " + SECRET)
        return Frame()

    monkeypatch.setitem(sys.modules, "rqdatac", SimpleNamespace(
        init=lambda *args, **kwargs: None,
        user=SimpleNamespace(get_quota=lambda: {"bytes_limit": 20 * 1024 * 1024,
                                              "bytes_used": 0, "remaining_days": 286,
                                              "license_type": "EDU"}),
        get_pit_financials_ex=financial,
    ))
    monkeypatch.setitem(sys.modules, "rqdatac.thread_local", SimpleNamespace(ThreadLocalConnection=Connection))
    credential = tmp_path / "synthetic.txt"
    credential.write_text(SECRET, encoding="utf-8")
    out = tmp_path / "fresh_output"
    result = SAMPLE.run(credential, tmp_path, out)
    assert calls == ["2018-04-25", "2018-04-27"]
    assert result["status"] == "BLOCKED_ACCESS_OR_LICENSE"
    assert result["failure_code"] == "PERMISSION_DENIED"
    assert result["market_financial_attempts"] == 2
    assert [e["status"] for e in result["request_results"]] == ["RETURNED", "FAILED"]
    raw = (out / "raw" / "600518_before.json").read_bytes()
    assert result["request_results"][0]["source_payload_hash"] == hashlib.sha256(raw).hexdigest()
    assert result["saved_response_bytes"] == len(raw)
    assert result["request_results"][0]["filing_document_hash"] is None
    assert result["actual_r2_accounts"] == result["human_acceptances"] == 0
    assert result["performance_metrics"] is None
    receipt_text = (out / "receipt.json").read_text(encoding="utf-8")
    emitted = capsys.readouterr()
    assert SECRET not in receipt_text + emitted.out + emitted.err
    assert "sdk_mutation" not in receipt_text
    with pytest.raises(FileExistsError):
        SAMPLE.run(credential, tmp_path, out)
    assert (out / "receipt.json").read_text(encoding="utf-8") == receipt_text
