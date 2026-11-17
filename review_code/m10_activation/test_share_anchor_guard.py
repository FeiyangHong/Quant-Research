"""Synthetic transport boundary checks for the remaining-budget probe."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("anchor_probe", ROOT / "scripts/m10_rqdata_share_anchor_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


@pytest.mark.parametrize("mode", ["returned", "fourth_rpc", "denied"])
def test_remaining_budget_and_secret_boundary(mode, tmp_path, monkeypatch, capsys):
    secret = "SYNTHETIC_SECRET_ONLY"
    calls = []
    class Connection:
        def _execute(self, conn, method, args, kwargs):
            calls.append(method)
    connection = Connection()
    def execute(method):
        return connection._execute(None, method, (), {})
    def init(*a, **kw):
        execute("init_quota")
        if mode == "denied":
            raise PermissionError("permission denied " + secret)
    def quota():
        execute("explicit_quota")
        return dict(bytes_limit=209715200.0, bytes_used=0, remaining_days=286, license_type="EDU")
    def financial(**kw):
        assert kw["date"] == "2020-07-31" and kw["statements"] == "all"
        assert len(kw["order_book_ids"]) == 5
        execute("financial")
        kw["fields"].append("SDK_MUTATION")
        print(secret)
        if mode == "fourth_rpc":
            execute("hidden_fourth")
        return pd.DataFrame({"synthetic": [1]})
    monkeypatch.setitem(sys.modules, "rqdatac", SimpleNamespace(init=init,
        user=SimpleNamespace(get_quota=quota), get_pit_financials_ex=financial))
    monkeypatch.setitem(sys.modules, "rqdatac.thread_local", SimpleNamespace(ThreadLocalConnection=Connection))
    credential = tmp_path / "synthetic.txt"
    credential.write_text(secret)
    out = tmp_path / "output"
    result = PROBE.run(credential, tmp_path, out)
    assert result["rpc_execute_attempts"] == len(calls) <= 3
    assert "hidden_fourth" not in calls
    assert "SDK_MUTATION" not in PROBE.PARAMS["fields"]
    assert result["status"] == ("RETURNED_NOT_ADMITTED" if mode == "returned" else "STOPPED_NOT_ADMITTED")
    assert result["actual_r2_accounts"] == 0 and result["full_sample_admission"] is False
    emitted = capsys.readouterr()
    assert secret not in emitted.out + emitted.err + json.dumps(result)
    before = (out / "receipt.json").read_bytes()
    with pytest.raises(FileExistsError):
        PROBE.run(credential, tmp_path, out)
    assert before == (out / "receipt.json").read_bytes()
