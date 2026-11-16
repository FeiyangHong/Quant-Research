"""Independent failure boundaries for the narrow Windows atomic rename repair."""
import json
from pathlib import Path
import pytest
from quant_research import budget


@pytest.mark.parametrize("code", [5,32,33])
def test_same_fsynced_bytes_are_retried_without_mutating_old_file(tmp_path,monkeypatch,code):
    destination = tmp_path/"snapshot.json"
    destination.write_text('{"old":true}',encoding="utf-8")
    before = destination.read_bytes()
    replace = budget.os.replace
    attempts = []
    def once(source,target):
        attempts.append((Path(source).read_bytes(),str(source)))
        if len(attempts) == 1:
            assert destination.read_bytes() == before
            error = PermissionError("independent simulated rename conflict")
            error.winerror = code
            raise error
        return replace(source,target)
    monkeypatch.setattr(budget.os,"replace",once)
    monkeypatch.setattr(budget.time,"sleep",lambda _:None)
    budget.atomic_json(destination,{"new":[1,2,3]})
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert json.loads(destination.read_bytes()) == {"new":[1,2,3]}
    assert not list(tmp_path.glob("*.tmp"))


def test_unrelated_permission_error_has_no_retry_or_old_snapshot_loss(tmp_path,monkeypatch):
    destination = tmp_path/"snapshot.json"
    destination.write_text("old",encoding="utf-8")
    calls = []
    def fail(*args):
        calls.append(args)
        raise PermissionError("not a recognized Windows sharing code")
    monkeypatch.setattr(budget.os,"replace",fail)
    monkeypatch.setattr(budget.time,"sleep",lambda _:pytest.fail("unexpected retry"))
    with pytest.raises(PermissionError): budget.atomic_json(destination,{"x":1})
    assert len(calls) == 1 and destination.read_text() == "old"
    assert not list(tmp_path.glob("*.tmp"))
