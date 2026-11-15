"""Non-author review: real late notice and injected source conflict, never market returns."""
import json
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import m5_market_cap as subject


def test_real_late_notice_excluded_even_when_provider_sorts_it_first():
    summary = json.loads((ROOT / "reports/m5_market_cap/coverage_summary.json").read_text(encoding="utf-8"))
    case = next(c for c in summary["cases"] if c["instrument_id"] == "sz.002526")
    # The committed artifact retains both real candidate and excluded late row.
    # Raw-file hash/page checks live separately in market_cap_source_checks.json.
    records = [case["provider_candidate"]] + [r["row"] for r in case["provider_screen_rejections"]]
    for rows in (records, list(reversed(records))):
        chosen, rejected = subject.select_vendor_candidate(rows)
        assert chosen["END_DATE"].startswith("2020-01-03")
        late = next(r for r in rejected if r["row"]["END_DATE"].startswith("2020-06-30"))
        assert late["row"]["NOTICE_DATE"].startswith("2020-08-20")
        assert late["reason"] == "PROVIDER_NOTICE_NOT_VISIBLE_DATE_ONLY"


@pytest.mark.archived_source
def test_archived_provider_hash_and_full_rows_reproduce_selection():
    summary = json.loads((ROOT / "reports/m5_market_cap/coverage_summary.json").read_text(encoding="utf-8"))
    case = next(c for c in summary["cases"] if c["instrument_id"] == "sz.002526")
    source = case["provider_source"]
    original = source["raw_path"].replace("\\", "/")
    assert "/data/" in original, "Archived source must name a repository data path"
    path = ROOT / "data" / original.split("/data/", 1)[1]
    assert path.resolve().is_relative_to(ROOT.resolve())
    if not path.exists():
        pytest.skip("Archived original provider bytes absent in this checkout")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    assert len(raw) == source["byte_count"]
    payload = json.loads(raw)
    assert payload["success"] and payload["result"]["pages"] == 1
    records = payload["result"]["data"]
    assert all(row["SECURITY_CODE"] == "002526" for row in records)
    for rows in (records, list(reversed(records))):
        selected, rejected = subject.select_vendor_candidate(rows)
        assert selected == case["provider_candidate"]
        assert rejected == case["provider_screen_rejections"]


def isolated_reporting_inputs(tmp_path, monkeypatch):
    """Explicit invented ledger/doc placeholders test status logic without local caches.

    The five literal quantities are independent reviewed constants; no source
    authenticity claim is made for these temporary test objects. Actual source
    integrity was checked separately against all eighteen saved originals.
    """
    test_root = tmp_path / "INVENTED_REPORT_CONTRACT_FIXTURE"
    test_root.mkdir()
    counts = {"sh.600519": (1256197800, 1256197800), "sz.002526": (1782793836, 1782793836),
              "sh.601398": (356406257089, 269612212539), "sh.600518": (4973861675, 4973861675),
              "sz.300855": (200000000, 200000000)}
    pool = [dict(instrument_id=code, raw_ohlcv=dict(close="1.00")) for code in counts]
    pool += [dict(instrument_id=f"INVENTED_UNMEASURED_{n}") for n in range(3779 - len(pool))]
    pool_path = test_root / "reports/m4_data/full_pool_2020-07-31.json"
    pool_path.parent.mkdir(parents=True)
    pool_path.write_text(json.dumps({"rows": pool}), encoding="utf-8")
    calendar_path = test_root / "data/admitted_r1/phase2_v1/development/calendar.json"
    calendar_path.parent.mkdir(parents=True)
    verified_calendar = json.loads((ROOT / "tests/fixtures/m5_verified_calendar_2015_2024.json").read_text(encoding="utf-8"))
    calendar_path.write_text(json.dumps(verified_calendar["trading_dates"]), encoding="utf-8")
    attempts = []

    def source(label, payload):
        path = test_root / (label + ".INVENTED_TEST_ONLY")
        raw = json.dumps(payload).encode()
        path.write_bytes(raw)
        attempts.append(dict(label=label, scope="market_cap", terminal=True, status="FETCHED",
            raw_path=str(path), sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
            elapsed_seconds=0, provenance="INVENTED_TEST_ONLY"))

    for identity, (total, a) in counts.items():
        code = identity[3:]
        source("market_eastmoney_" + code + "_20200731", {"success": True, "result": {"pages": 1, "data": [
            dict(SECURITY_CODE=code, END_DATE="2020-01-01", NOTICE_DATE="2019-12-30", TOTAL_SHARES=total, TOTAL_A_SHARES=a)]}})
        source("market_pdf_" + code, {"note": "No real PDF; invented report-contract input only"})
        source("market_search_" + code, {})
    for label in ("market_002526_2018_annual", "market_002526_2018_interim", "market_002526_2018_capital_query"):
        source(label, {})
    ledger = test_root / "data/raw_m5_equity/budget.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"attempts": attempts}), encoding="utf-8")
    # The report's code-manifest step hashes these files; this is not execution.
    for relative in ("scripts/m5_sources.py", "src/quant_research/budget.py", "scripts/m4_data_feasibility.py"):
        path = test_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# INVENTED_REPORT_CONTRACT_FIXTURE\n", encoding="utf-8")
    # Keep __file__ inside the fixture for its relative manifest path only.
    script_path = test_root / "scripts/m5_market_cap.py"
    script_path.write_text("# INVENTED_REPORT_CONTRACT_FIXTURE\n", encoding="utf-8")
    monkeypatch.setattr(subject, "__file__", str(script_path))
    monkeypatch.setattr(subject, "ROOT", test_root)
    monkeypatch.setattr(subject, "OUT", tmp_path / "outputs")


@pytest.mark.parametrize("field", ["TOTAL_SHARES", "TOTAL_A_SHARES"])
def test_provider_document_count_conflict_cannot_report_crosscheck_pass(tmp_path, monkeypatch, field):
    isolated_reporting_inputs(tmp_path, monkeypatch)
    select = subject.select_vendor_candidate

    def inject_conflict(records, snapshot=subject.SNAPSHOT):
        chosen, rejected = select(records, snapshot)
        if chosen and chosen["SECURITY_CODE"] == "601398":
            chosen = dict(chosen)
            chosen[field] += 1  # Explicit invented source conflict: never written into real raw objects.
        return chosen, rejected

    monkeypatch.setattr(subject, "select_vendor_candidate", inject_conflict)
    subject.build()
    output = json.loads((subject.OUT / "coverage_summary.json").read_text(encoding="utf-8"))
    case = next(c for c in output["cases"] if c["instrument_id"] == "sh.601398")
    assert not (case["ordinary_share_count_matches_document"] and case["a_share_count_matches_document"])
    assert "PASS" not in case["status"], "Conflicting original/provider counts must not be labelled crosscheck PASS"
    assert output["original_document_value_crosschecks"] == 4
    row = next(r for r in json.loads((subject.OUT / "full_pool_market_cap_2020-07-31.json").read_text(encoding="utf-8"))["rows"]
               if r["instrument_id"] == "sh.601398")
    assert "CONFLICT" in row["status"] or "BLOCKED" in row["status"]

