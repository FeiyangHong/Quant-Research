"""Recompute all monthly decisions directly from independently admitted tables."""
import argparse
from bisect import bisect_left
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
from independent_accounts import ROOT, read, sha, load_stage, close

D = Decimal


def calculate(source,selection,variant,delay,start,end):
    days = [day for day in source["calendar"] if day <= end]
    bars = {(r["date"],r["instrument_id"]):r for r in source["bars"]}
    benchmark = {r["date"]:r for r in source["benchmark"]}
    masters = defaultdict(list)
    for row in source["instruments"]: masters[row["instrument_id"]].append(row)
    result = []
    for i,anchor in enumerate(days):
        if i+1+delay >= len(days) or anchor[:7] == days[i+1][:7]: continue
        release,execution = days[i+1],days[i+1+delay]
        if execution < start: continue
        release_clock = release+"T21:00:00+08:00"
        anchor_clock = anchor+"T21:00:00+08:00"
        eligible,score,weights = [],{},{}
        trend = None
        if anchor_clock < selection["cohort_available_at"]:
            status = "CASH_COHORT_NOT_YET_KNOWN"
            count = None
        else:
            for sid in sorted(selection["selected_instruments"]):
                states = [r for r in masters[sid] if r["available_at"] <= anchor_clock]
                assert states, (anchor,sid,"unknown identity")
                meta = max(states,key=lambda r:r["available_at"])
                assert meta["status"] in ("NORMAL","ACTIVE","SUSPENDED","ECONOMIC_IDENTITY_CHANGED","RETIRED")
                assert isinstance(meta["account_verified"],bool)
                if not meta["account_verified"]: assert meta["account_permission_status"] == "DENIED"
                age = len([day for day in days[:i+1] if day >= meta["listed_on"]])
                if meta["listed_on"] > anchor or meta.get("delisted_on") or meta["status"] not in ("NORMAL","ACTIVE") or not meta["account_verified"] or age < 252: continue
                window = [bars[day,sid] for day in days[i-19:i+1]]
                assert len(window) == 20 and all(r["available_at"] <= release_clock for r in window)
                values = sorted(D(str(r["amount"])) for r in window)
                assert all(v.is_finite() and v >= 0 for v in values)
                assert all(isinstance(r["suspended"],bool) and (not r["suspended"] or r["amount"] == 0) for r in window)
                if not window[-1]["suspended"] and (values[9]+values[10])/2 >= 20000000: eligible.append(sid)
            count = len(eligible)
            if count >= 3:
                for sid in eligible:
                    numerator,denominator = bars[days[i-21],sid],bars[days[i-126],sid]
                    assert all(r["available_at"] <= release_clock and r.get("total_return_available_at",r["available_at"]) <= release_clock for r in (numerator,denominator))
                    value = D(str(numerator["total_return_index"]))/D(str(denominator["total_return_index"]))
                    score[sid] = value.ln()
            window = [benchmark[day] for day in days[i-199:i+1]]
            assert len(window) == 200 and all(r["available_at"] <= release_clock for r in window)
            values = [D(str(r["total_return_index"])) for r in window]
            assert all(v.is_finite() and v > 0 for v in values)
            trend = values[-1] > sum(values)/200
            ordered = sorted(score,key=lambda sid:(-score[sid],sid))
            status = "CASH_INSUFFICIENT_PRODUCTS" if count < 3 else "OK"
            if count >= 3:
                chosen = ordered[:3] if variant in ("R0","R1") else eligible
                weights = {sid:D(1)/len(chosen) for sid in sorted(chosen)}
                if variant in ("E1","R1") and not trend: status,weights = "CASH_TREND_OFF",{}
        result.append(dict(anchor=anchor,release=release,execution=execution,status=status,eligible=eligible,
            eligible_count=count,momentum=score,trend=trend,weights=weights))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage",type=Path,required=True)
    parser.add_argument("--phase",choices=["base","all"],required=True)
    args = parser.parse_args()
    source = load_stage(args.stage)
    selection = read(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")
    records = read(ROOT/"reports/m8_rotation/ACCOUNT_PATHS.json")
    summaries = []
    for record in records:
        if args.phase == "base" and record["path"] != "base": continue
        start,end = ("2020-01-01","2021-12-31") if record["period"] == "development" else ("2022-01-01","2024-12-31")
        expected = calculate(source,selection,record["variant"],record["execution_delay"],start,end)
        actual = read(ROOT/record["artifact_directory"]/"decisions.json")
        assert len(actual) == len(expected)
        for a,e in zip(actual,expected):
            assert a["decision_at"][:10] == e["release"] and a["execution_date"] == e["execution"]
            assert a["status"] == e["status"]
            info = a["diagnostics"]
            assert info["signal_anchor_date"] == e["anchor"] and info["eligible"] == e["eligible"]
            assert info["eligible_count"] == e["eligible_count"] and info["trend"] == e["trend"]
            assert set(a["weights"]) == set(e["weights"])
            for sid,w in e["weights"].items(): close(a["weights"][sid],w,"independent target weight",D("1e-14"))
            assert set(info["momentum"]) == set(e["momentum"])
            for sid,value in e["momentum"].items(): close(info["momentum"][sid],value,"independent momentum",D("1e-12"))
            assert a["ranks"] == {sid:i for i,sid in enumerate(sorted(e["weights"]),1)}
        summaries.append(dict(trial_id=record["trial_id"],decisions=len(expected),
            qualified_ranking_months=sum(len(e["eligible"])>=4 for e in expected),
            active_target_months=sum(bool(e["weights"]) for e in expected)))
    assert len(summaries) == (8 if args.phase == "base" else 32)
    out = dict(decision="PASS_INDEPENDENT_MONTHLY_SIGNALS",phase=args.phase,accounts=summaries,
        stage_manifest_sha256=sha(args.stage/"manifest.json"),
        method="Independent Decimal medians/126-to21 TR log ratio/200-session strict trend; all eligible losing competitors included; calendar age252 and D/D+1/D+2 orD+3 clocks; canonical identity priorities.")
    (ROOT/"reports/m8_review"/("independent_signals_"+args.phase+".json")).write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(out["decision"],len(summaries))


if __name__ == "__main__": main()
