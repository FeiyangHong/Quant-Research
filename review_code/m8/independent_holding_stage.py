"""Independently bind raw prices/actions and a virtual reinvested fund ledger."""
import argparse
from bisect import bisect_right
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from independent_raw_bars import ROOT, build, checked
from independent_action_documents import EXPECTED
from independent_accounts import read, sha, load_stage, close

D = Decimal


def secondary(primary):
    manifest = read(ROOT/"reports/m8_rotation/PRICE_RECONCILIATION.json")
    summaries = []
    for item in manifest["records"]:
        sid = item["instrument_id"]
        rows = {}
        for receipt in item["captures"]:
            raw = checked(receipt)
            # Access only requested historical day arrays; all unsolicited
            # current-quote/name fields in the transport body remain unused.
            payload = json.loads(raw)
            assert payload["code"] == 0
            day_rows = payload["data"][sid.replace(".","")].get("day",[])
            for values in day_rows:
                assert "2019-01-01" <= values[0] <= "2024-12-31" and values[0] not in rows
                rows[values[0]] = dict(zip(("date","open","close","high","low","vendor_volume"),values[:6]))
        comparisons = 0
        for (day,identity),row in primary.items():
            if identity != sid: continue
            if row["tradestatus"] == "1": assert day in rows, (sid,day)
            if day not in rows: continue
            for field in ("open","high","low","close"):
                assert abs(D(row[field])-D(rows[day][field])) <= D("0.00005"), (sid,day,field)
                comparisons += 1
        assert comparisons == item["comparisons"]
        summaries.append(dict(instrument_id=sid,matched_raw_OHLC_fields=comparisons,source_hashes=[r["sha256"] for r in item["captures"]]))
    assert len(summaries) == 10
    return summaries


def run(stage):
    source = load_stage(stage)
    manifest = read(stage/"manifest.json")
    assert manifest["market_history_start"] == "2019-01-01" and not manifest["build_blockers"]
    assert manifest["synthetic"] is False
    for path,digest in manifest["file_sha256"].items(): assert sha(stage/path) == digest
    for path,digest in manifest["source_snapshot_hashes"].items(): assert sha(ROOT/path) == digest, path
    primary,raw_summary = build()
    corroboration = secondary(primary)
    assert len(source["bars"]) == len(primary)
    assert set((r["date"],r["instrument_id"]) for r in source["bars"]) == set(primary)
    days = source["calendar"]
    def available(day): return days[bisect_right(days,day)]+"T21:00:00+08:00"
    actual_actions = source["actions"]
    assert len(actual_actions) == len(EXPECTED) == 5
    event_map = {}
    for expected in EXPECTED:
        matches = [r for r in actual_actions if r["instrument_id"] == expected["instrument_id"] and r["ex_date"] == expected["ex_date"]]
        assert len(matches) == 1
        row = matches[0]
        for key,value in expected.items():
            if key == "market_ex_date": assert row["source_ex_date"] == value
            elif key in ("share_factor","cash_per_share"): close(row[key],D(value),key,D("1e-12"))
            else: assert row[key] == value, (key,row[key],value)
        assert row["available_at"] == available(expected["announcement_date"])
        assert row["terms_verified"] is True and row["action_status"] == "CONFIRMED"
        if expected["action_type"] == "CASH_DIVIDEND":
            assert row["actual_pay_date"] is None and row["actual_account_receipt_observed"] is False
            assert row["settlement_mode"] == "RULE_BASED_SIMULATION" and row["settlement_rule_credit_basis"] == "ANNOUNCED_INVESTOR_PAY_DATE"
            assert row["settlement_rule_verified"] is True
        event_map[expected["ex_date"],expected["instrument_id"]] = expected
    tr_summaries = []
    for sid in sorted({r["instrument_id"] for r in source["bars"]}):
        rows = sorted((r for r in source["bars"] if r["instrument_id"] == sid),key=lambda r:r["date"])
        virtual_shares = None
        mark = None
        largest_error = D(0)
        for row in rows:
            day = row["date"]
            raw = primary[day,sid]
            for field in ("open","high","low","close","preclose","amount","volume"):
                close(row[field],D(raw[field]),(day,sid,field),D("1e-10"))
            assert row["suspended"] == (raw["tradestatus"]=="0")
            assert row["available_at"] == day+"T21:00:00+08:00"
            assert row["total_return_available_at"] == row["available_at"]
            assert row["vendor_first_seen_at"] is None
            assert row["usage_scope"] == "FULL_STRATEGY"
            for field,factor in (("upper_limit",D("1.1")),("lower_limit",D("0.9"))):
                expected_limit = (D(raw["preclose"])*factor/D("0.001")).to_integral_value(rounding=ROUND_HALF_UP)*D("0.001")
                close(row[field],expected_limit,(day,sid,field),D("1e-10"))
            event = event_map.get((day,sid))
            if virtual_shares is None:
                assert event is None
                mark = D(raw["close"])
                virtual_shares = D(100)/mark
            dividend_cash = D(0)
            if event and event["action_type"] == "SPLIT" and event["effective_phase"] == "BOD":
                virtual_shares *= D(event["share_factor"])
                mark /= D(event["share_factor"])
            if event and event["action_type"] == "CASH_DIVIDEND":
                dividend_cash = virtual_shares*D(event["cash_per_share"])
                mark -= D(event["cash_per_share"])
            if raw["tradestatus"] == "1": mark = D(raw["close"])
            if event and event["action_type"] == "SPLIT" and event["effective_phase"] == "EOD":
                virtual_shares *= D(event["share_factor"])
                mark /= D(event["share_factor"])
            # A separate proportional fund starts with100 and immediately
            # reinvests ex-date cash into fractional units at source close.
            virtual_shares += dividend_cash/mark
            total_return = virtual_shares*mark
            close(row["valuation_close"],mark,"theoretical valuation close",D("1e-10"))
            close(row["total_return_index"],total_return,(day,sid,"TR"),D("1e-8"))
            largest_error = max(largest_error,abs(D(str(row["total_return_index"]))-total_return))
        tr_summaries.append(dict(instrument_id=sid,rows=len(rows),maximum_TR_difference=str(largest_error)))
    expected_benchmark = read(ROOT/"data/admitted_r1/phase2_v1/validation/benchmark.json")["records"]
    assert len(source["benchmark"]) == len(expected_benchmark)
    for row,prior in zip(source["benchmark"],expected_benchmark):
        assert {k:v for k,v in row.items() if k!="quality_status"} == {k:v for k,v in prior.items() if k!="quality_status"}
    output = dict(decision="PASS_NORMALIZED_HOLDING_DATA_RAW_AND_TR",author_role="INDEPENDENT_REVIEWER",
        stage_manifest_sha256=sha(stage/"manifest.json"),source_hashes_checked=len(manifest["source_snapshot_hashes"]),
        full_rows=len(primary),all_competitors_have_nonnull_TR=True,secondary_raw_OHLC=corroboration,TR_virtual_share_ledgers=tr_summaries,
        action_count=5,source_scope="2019–2024 selected cohort only; earlier calendar is listing-age evidence; unknown vendor vintage remains unknown",
        limits=["Primary volume/amount retain vendor share/CNY units and OHLC bounds; secondary provider does not independently certify amounts.",
            "Source timing is historical public reconstruction, not observed vendor first-seen or live feed.",
            "Benchmark value/calendar raw-original review is separately bound; fee/license/lifecycle review is separately bound."])
    (ROOT/"reports/m8_review/independent_holding_stage.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output["decision"],output["full_rows"])


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--stage",type=Path,required=True)
    run(parser.parse_args().stage)
