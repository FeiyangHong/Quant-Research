"""Staging integrity is necessary but must never unlock historical experiments."""
import copy
import json

from quant_research.providers.baostock import BaoStockAdapter, Query, normalize_history, write_immutable
from quant_research.real_data import audit_collection


def collection_fixture(root):
    history = {"status": "SUCCESS", "fields": ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "adjustflag", "tradestatus", "turn", "pctChg", "isST"],
               "rows": [["2024-04-01", "sh.512320", "0.8", "0.8", "0.8", "0.8", "0.8", "0", "0", "3", "1", "0", "0", "0"],
                        ["2024-04-03", "sh.512320", "0.8", "0.8", "0.8", "0.8", "0.8", "0", "0", "3", "0", "0", "0", "0"]]}
    calendar = {"status": "SUCCESS", "fields": ["calendar_date", "is_trading_day"],
                "rows": [[f"2024-04-0{i}", "1"] for i in range(1, 4)]}
    answers = iter([calendar, history])
    adapter = BaoStockAdapter(root, worker=lambda *_: copy.deepcopy(next(answers)), min_interval=0)
    items = [adapter.collect(Query("calendar", start="2024-04-01", end="2024-04-03")),
             adapter.collect(Query("history", code="sh.512320", start="2024-04-01", end="2024-04-03"))]
    item = items[1]
    payload = json.loads((root / item["raw_path"]).read_bytes())
    normalized = normalize_history(payload)
    item["normalized_path"] = "normalized/history.json"
    item["normalized_sha256"] = write_immutable(root / item["normalized_path"], normalized)
    value = {"schema_version": "baostock-collection-1.0", "synthetic": False,
             "history_end_cap": "2024-12-31", "query_results": items}
    value["request_plan_sha256"] = write_immutable(root / "request_plan.json", {
        "queries": [{k: item[k] for k in ("kind", "code", "start", "end", "date")} for item in items]})
    write_immutable(root / "collection.json", value)
    return value


def test_missing_day_is_reported_and_zero_turnover_not_relabelled(tmp_path):
    collection_fixture(tmp_path)
    report = audit_collection(tmp_path)
    assert report["status"] == "BLOCKED_DATA" and report["performance_evidence"] is False
    history = report["histories"][0]
    assert history["internal_missing_sessions"] == ["2024-04-02"]
    assert history["zero_turnover_marked_tradable_dates"] == ["2024-04-01"]
    assert history["observed_state_counts"] == {"ZERO_TURNOVER": 1, "SUSPENDED": 1}
    assert history["observed_first"] == "2024-04-01"
    assert "listed_on" not in history


def test_raw_tampering_never_reaches_observation_audit(tmp_path):
    value = collection_fixture(tmp_path)
    (tmp_path / value["query_results"][1]["raw_path"]).write_text("{}")
    report = audit_collection(tmp_path)
    assert report["integrity_status"] == "FAIL"
    assert not report["histories"]
    assert any("hash mismatch" in e for e in report["errors"])


def test_normalized_tampering_cannot_be_hidden_by_rehashing(tmp_path):
    value = collection_fixture(tmp_path)
    item = value["query_results"][1]
    normal = json.loads((tmp_path / item["normalized_path"]).read_bytes())
    normal["records"][0]["suspended"] = True
    item["normalized_path"] = "normalized/tampered.json"
    item["normalized_sha256"] = write_immutable(tmp_path / item["normalized_path"], normal)
    (tmp_path / "collection.json").write_text(json.dumps(value))
    report = audit_collection(tmp_path)
    assert any("disagree with raw" in e for e in report["errors"])
    assert not report["histories"]


def test_manifest_path_traversal_is_rejected(tmp_path):
    value = collection_fixture(tmp_path)
    value["query_results"][1]["manifest_path"] = "../outside.json"
    (tmp_path / "collection.json").write_text(json.dumps(value))
    assert any("escapes collection" in e for e in audit_collection(tmp_path)["errors"])
