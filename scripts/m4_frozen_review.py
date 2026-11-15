"""Read-only M4 audit of frozen R1 artifacts; no production imports or strategy runs.

Interpretation is independently implemented from each run's hash-bound source.
Only reports/m4_frozen is written. Market input is restricted to admitted 2016-24
datasets with their original necessary warmup. No estimator replacement/search.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/m4_frozen"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                     allow_nan=False) + "\n", encoding="utf-8")


def csv_out(name, rows):
    if not rows:
        (OUT / name).write_text("", encoding="utf-8")
        return
    with (OUT / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True)
                             if isinstance(v, (list, dict)) else v for k, v in row.items()})


def master_choice(rows, cutoff, effective=False):
    """Frozen latest-publication selector; optional original strategy interval filter."""
    at = pd.Timestamp(cutoff)
    day = at.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")
    known = [r for r in rows if pd.Timestamp(r["available_at"]) <= at]
    if effective:
        known = [r for r in known if (not r.get("effective_from") or r["effective_from"][:10] <= day)
                 and (not r.get("effective_to") or r["effective_to"][:10] > day)]
    return max(known, key=lambda r: pd.Timestamp(r["available_at"])) if known else None


def original_risk(returns, weights):
    """Original fixed 50% sample + 50% diagonal estimator, beside direct series std."""
    clean = np.asarray(returns, dtype=float)
    clean = clean[np.isfinite(clean).all(axis=1)]
    if len(clean) < 45:
        return {"complete_sessions": len(clean), "direct_sigma": None,
                "original_shrink_sigma": None, "original_scale": 0.0}
    vector = np.asarray(weights, dtype=float)
    covariance = np.atleast_2d(np.cov(clean, rowvar=False, ddof=1))
    shrunk = .5 * covariance + .5 * np.diag(np.diag(covariance))
    sigma = float(np.sqrt(max(0., vector @ shrunk @ vector * 252)))
    direct = float(np.std(clean @ vector, ddof=1) * np.sqrt(252))
    return {"complete_sessions": len(clean), "direct_sigma": direct,
            "original_shrink_sigma": sigma,
            "original_scale": min(1., .10 / sigma) if sigma else 1.0}


def repeat_exposure_counterexample():
    # Deterministic exposure identity experiment; not a market or shrinkage search.
    common = np.tile([-.02, .02], 30)
    rows = []
    for count in (3, 6, 9):
        repeated = np.column_stack([common] * count)
        result = original_risk(repeated, np.repeat(1. / count, count))
        rows.append({"identical_exposure_slots": count, **result,
                     "analytic_shrunk_to_direct_ratio": float(np.sqrt(.5 + .5 / count))})
    return {"status": "DESIGN_COUNTEREXAMPLE_ORIGINAL_ESTIMATOR_UNCHANGED", "rows": rows,
            "interpretation": "Splitting one identical return exposure among 3, 6 and 9 equal-weight names (all within the original 35% single-name cap) leaves direct portfolio risk unchanged, but the original diagonal shrink estimator lowers estimated risk. This is a representation dependence design limit, not evidence that actual ETFs are identical, not an alternative estimator, and not a new performance experiment."}


def daily_attribution(nav, positions, fills, cash_events, initial_cash):
    """Marked value change + signed trade cash - fees + recognized income."""
    values, flows, fees = defaultdict(dict), defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for row in positions:
        values[row["date"]][row["instrument_id"]] = row["market_value"]
    for row in fills:
        day, sid = row["date"], row["instrument_id"]
        flows[day][sid] += (row["notional"] if row["side"] == "SELL" else -row["notional"]) - row["fees"]
        fees[day][sid] += row["fees"]
    for row in cash_events:
        if row["event"] == "DIVIDEND_RECEIVABLE":
            flows[row["date"]][row["instrument_id"]] += row["amount"]
        assert not row["event"].startswith("LIQUIDATION"), "Separate rights attribution required"
    daily, previous_values, previous_nav = {}, {}, initial_cash
    max_error = 0.
    for row in nav:
        day = row["date"]
        current = values[day]
        pnl = {sid: current.get(sid, 0.) - previous_values.get(sid, 0.) + flows[day].get(sid, 0.)
               for sid in set(current) | set(previous_values) | set(flows[day])}
        error = abs(sum(pnl.values()) - (row["nav"] - previous_nav))
        max_error = max(max_error, error)
        assert error < 1e-6, (day, error)
        daily[day] = pnl
        previous_values, previous_nav = current, row["nav"]
    return daily, fees, max_error


def prepare_master(period, data):
    rows = data["instruments"]
    groups = defaultdict(list)
    for row in rows:
        groups[row["instrument_id"]].append(row)
    assert all(pd.Timestamp(r["available_at"]).tz_convert("Asia/Shanghai").strftime("%H:%M:%S") == "21:00:00" for r in rows)
    cutoffs = [(day,clock,pd.Timestamp(day+"T"+clock+"+08:00").value)
               for day in data["calendar"] for clock in ("09:30:00","21:00:00")]
    discrepancies, lookup = [], {}
    # Covers all original warmup/account calendar dates at both execution clocks.
    for sid, candidates in groups.items():
        timed = sorted((pd.Timestamp(r["available_at"]).value,i,r) for i,r in enumerate(candidates))
        for day,clock,cutoff_value in cutoffs:
                known = [r for timestamp,_,r in timed if timestamp <= cutoff_value]
                valid = [r for r in known if (not r.get("effective_from") or r["effective_from"][:10]<=day)
                         and (not r.get("effective_to") or r["effective_to"][:10]>day)]
                old, new = (known[-1] if known else None), (valid[-1] if valid else None)
                if (old or {}).get("revision_id") == (new or {}).get("revision_id"):
                    continue
                row = {"period": period, "date": day, "clock": clock, "instrument_id": sid,
                       "old_revision": (old or {}).get("revision_id"),
                       "interval_revision": (new or {}).get("revision_id"),
                       "old_available_at": (old or {}).get("available_at"),
                       "old_effective_from": (old or {}).get("effective_from"),
                       "old_effective_to": (old or {}).get("effective_to"),
                       "old_benchmark": (old or {}).get("benchmark_id"),
                       "interval_benchmark": (new or {}).get("benchmark_id"),
                       "old_universe": (old or {}).get("strategy_universe"),
                       "interval_universe": (new or {}).get("strategy_universe"),
                       "account_scope": "ACCOUNT" if day >= data["account_start"] else "WARMUP"}
                discrepancies.append(row)
                lookup[(day, clock, sid)] = row
                # Original _action_cutoff uses 15:00 for EOD share events.
                # All frozen master availability clocks verified21:00 above;
                # therefore 09:30 and 15:00 choose exactly the same rows.
                if clock == "09:30:00":
                    lookup[(day,"15:00:00",sid)] = {**row,"clock":"15:00:00"}
    return groups, discrepancies, lookup


def inspect_run(run, tables, data, groups, mismatch):
    checks = Counter()
    triggers = []
    run_id = run["directory"]

    def check(day, sid, clock, scope, detail=None):
        checks[scope] += 1
        row = mismatch.get((day, clock, sid))
        if row:
            triggers.append({**row, "run_id": run_id, "path": run["path"], "scope": scope,
                             "detail": detail})

    for row in tables["positions"]:
        for clock in ("09:30:00", "21:00:00"):
            check(row["date"], row["instrument_id"], clock, "HELD_OPEN_AND_CLOSE")
    orders = {r["order_id"]: r for r in tables["orders"]}
    for row in tables["orders"]:
        check(row["decision_date"], row["instrument_id"], "21:00:00", "ORDER_CREATION", row["order_id"])
        check(row["execution_date"], row["instrument_id"], "09:30:00", "ORDER_EXECUTION", row["order_id"])
    for row in tables["order_events"] + tables["fills"] + tables["rejected_orders"]:
        sid = row.get("instrument_id") or orders.get(row.get("order_id"), {}).get("instrument_id")
        if sid:
            check(row["date"], sid, "09:30:00", "EXECUTION_EVENT", row.get("order_id"))
    for decision in tables["decisions"]:
        diag = decision["diagnostics"]
        # Full candidate metadata query, as well as actually selected IDs.
        for sid in groups:
            check(diag["signal_anchor_date"], sid, "21:00:00", "STRATEGY_ANCHOR_ALL_MASTER")
        for sid in set(diag["representatives"]) | set(diag["eligible"]) | set(decision["weights"]):
            check(diag["signal_anchor_date"], sid, "21:00:00", "STRATEGY_REP_ELIGIBLE_TARGET")
            check(decision["decision_date"], sid, "21:00:00", "TARGET_RELEASE")
    # Representative selection runs at every quarter boundary, even no-order days.
    calendar = data["calendar"]
    for idx, day in enumerate(calendar):
        if idx and (pd.Timestamp(day).year, pd.Timestamp(day).quarter) != (pd.Timestamp(calendar[idx-1]).year, pd.Timestamp(calendar[idx-1]).quarter):
            for sid in groups:
                check(calendar[idx-1], sid, "21:00:00", "QUARTER_ALL_MASTER")
    account_days = {r["date"] for r in tables["nav"]}
    for action in data["actions"]:
        day = action.get("effective_date") or action.get("ex_date")
        if day in account_days:
            check(day, action["instrument_id"], "09:30:00", "CORPORATE_ACTION_METADATA", action["action_id"])
    for row in tables["share_events"]:
        check(row["date"], row["instrument_id"], "15:00:00" if row.get("effective_phase") == "EOD" else "09:30:00",
              "SHARE_EVENT_METADATA", row["action_id"])
    actual_scopes = {"HELD_OPEN_AND_CLOSE", "ORDER_CREATION", "ORDER_EXECUTION", "EXECUTION_EVENT", "TARGET_RELEASE", "CORPORATE_ACTION_METADATA", "SHARE_EVENT_METADATA"}
    impacts = [r for r in triggers if r["scope"] in actual_scopes]
    return {"run_id": run_id, "period": run["period"], "path": run["path"],
            "initial_cash": run["config"]["initial_cash"], "variant": run["config"]["variant"],
            "risk_scaling": run["config"]["risk_scaling"], "query_coverage": dict(checks),
            "metadata_discrepancy_contexts": len(triggers), "actual_execution_dependency_discrepancies": len(impacts),
            "conclusion": "NO_OBSERVED_EFFECTIVE_INTERVAL_EXECUTION_TRIGGER" if not impacts else "REVIEW_REQUIRED"}, triggers


def monthly_account(run, tables, data, master, daily):
    nav = pd.DataFrame(tables["nav"]).set_index("date")
    returns = nav.nav / nav.nav.shift(1).fillna(run["config"]["initial_cash"]) - 1
    positions = defaultdict(dict)
    for p in tables["positions"]:
        positions[p["date"]][p["instrument_id"]] = p["weight"]
    bars = data["bars_frame"]
    calendar = data["calendar"]
    config = run["config"]
    decisions = tables["decisions"]
    result = []
    for idx, decision in enumerate(decisions):
        diag = decision["diagnostics"]
        anchor, day, execution = diag["signal_anchor_date"], decision["decision_date"], decision["execution_date"]
        end = decisions[idx+1]["execution_date"] if idx+1 < len(decisions) else "9999-12-31"
        eligible = diag["eligible"]
        selected = sorted(diag.get("momentum", {}), key=lambda s: (-diag["momentum"][s], s))[:3] if config["variant"].startswith("R") else eligible
        ungated = {s: min(.35, 1 / len(selected)) for s in selected}
        cutoff = pd.Timestamp(decision["decision_at"])
        index = calendar.index(anchor)
        dates = calendar[max(0, index-60):index+1]
        frame = bars.loc[bars.date.isin(dates) & bars.instrument_id.isin(selected) & bars._available.le(cutoff)].copy()
        frame = frame.sort_values("_available", kind="stable").drop_duplicates(["date", "instrument_id"], keep="last")
        frame.loc[frame._tr_available.isna() | frame._tr_available.gt(cutoff), "total_return_index"] = np.nan
        matrix = frame.pivot(index="date", columns="instrument_id", values="total_return_index").reindex(index=dates, columns=selected)
        matrix = matrix.where(np.isfinite(matrix) & matrix.gt(0))
        raw_r = matrix.pct_change(fill_method=None).iloc[-60:]
        risk = original_risk(raw_r.to_numpy(), [ungated[s] for s in selected])
        recorded_sigma = diag.get("annualized_sigma")
        sigma_error = abs(recorded_sigma - risk["original_shrink_sigma"]) if recorded_sigma is not None else None
        if sigma_error is not None:
            assert sigma_error < 1e-10, (day, sigma_error)
        trend = diag.get("trend")
        target = decision["weights"]
        after = positions[execution]
        before = positions[day]
        period_dates = [d for d in nav.index if execution <= d < end]
        forward = returns.loc[period_dates]
        pnl_by_sid = defaultdict(float)
        for d in period_dates:
            for sid, value in daily[d].items():
                pnl_by_sid[sid] += value
        meta = {s: master_choice(master[s], diag["signal_anchor_at"], True) for s in eligible}
        families = {s: (meta[s] or {}).get("benchmark_id") for s in eligible}
        row = {"run_id": run["directory"], "period": run["period"], "variant": config["variant"],
               "risk_scaling": config["risk_scaling"], "signal_anchor_date": anchor,
               "decision_date": day, "execution_date": execution,
               "holding_end_inclusive": period_dates[-1] if period_dates else None,
               "eligible_count": len(eligible), "eligible_ids": eligible,
               "index_families": families, "distinct_index_family_count": len(set(families.values())),
               "representatives": diag["representatives"], "exclusions": diag["exclusions"],
               "selected_ids_before_trend": selected, "trend": trend, "status": decision["status"],
               "ungated_selection_weights": ungated, "target_weights": target,
               "target_gross": sum(target.values()), "actual_weights_decision_close": before,
               "actual_weights_execution_close": after, "actual_gross_execution_close": sum(after.values()),
               "target_actual_L1_execution_close": sum(abs(target.get(s,0)-after.get(s,0)) for s in set(target)|set(after)),
               "ungated_direct_annualized_sigma": risk["direct_sigma"],
               "ungated_original_50pct_shrink_sigma": risk["original_shrink_sigma"],
               "ungated_original_scale": risk["original_scale"],
               "complete_risk_sessions": risk["complete_sessions"],
               "recorded_sigma": recorded_sigma, "recorded_scale": diag.get("risk_multiplier"),
               "recorded_sigma_absolute_error": sigma_error,
               "effective_scale": sum(target.values()) / sum(ungated.values()) if ungated else 0,
               "target_direct_sigma": (risk["direct_sigma"] * sum(target.values()) / sum(ungated.values())) if ungated and risk["direct_sigma"] is not None else None,
               "subsequent_holding_sessions": len(period_dates),
               "subsequent_realized_account_vol": float(forward.std(ddof=1)*np.sqrt(252)) if len(forward)>1 else None,
               "subsequent_net_pnl_cny": sum(pnl_by_sid.values()),
               "subsequent_net_pnl_by_etf": dict(sorted(pnl_by_sid.items())),
               "subsequent_sum_daily_returns": float(forward.sum())}
        result.append(row)
    return result


def run_review():
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = ROOT / "reports/real_data_phase3/results_summary.json"
    frozen = read(summary_path)
    assert frozen["run_count"] == 448
    datasets, master_groups, mismatches, grid, hashes = {}, {}, {}, [], {}
    for period in ("development", "validation"):
        folder = ROOT / "data/admitted_r1/phase2_v1" / period
        data = {}
        manifest = read(folder / "manifest.json")
        for name in ("instruments", "actions", "calendar", "bars", "benchmark"):
            path = folder / (name + ".json")
            digest = sha(path)
            assert digest == manifest["file_sha256"][name + ".json"]
            hashes[str(path.relative_to(ROOT)).replace("\\", "/")] = digest
            value = read(path)
            data[name] = value.get("records") if isinstance(value, dict) else value
        hashes[str((folder / "manifest.json").relative_to(ROOT)).replace("\\", "/")] = sha(folder / "manifest.json")
        data["account_start"] = "2016-01-01" if period == "development" else "2022-01-01"
        data["bars_frame"] = pd.DataFrame(data.pop("bars"))
        b = data["bars_frame"]
        b["_available"] = pd.to_datetime(b.available_at, utc=True)
        b["_tr_available"] = pd.to_datetime(b.total_return_available_at, utc=True, errors="coerce")
        master_groups[period], differences, mismatches[period] = prepare_master(period, data)
        grid.extend(differences)
        datasets[period] = data
        print("master grid", period, len(differences), flush=True)
    csv_out("effective_interval_discrepancy_grid.csv", grid)
    coverages, triggers, annual_rows, annual_accounts, monthly, primary_tables = [], [], [], [], [], {}
    source_hashes = defaultdict(set)
    artifact_checks = []
    for index, run in enumerate(frozen["runs"]):
        period, config = run["period"], run["config"]
        directory = Path(frozen["provenance"]["matrix_roots"][period]) / run["directory"]
        tables, checked = {}, {}
        for name in ("nav", "positions", "fills", "cash_events", "orders", "order_events", "rejected_orders", "share_events", "decisions"):
            path = directory / (name + ".json")
            digest = sha(path)
            expected = run["artifact_hashes"][name + ".json"] if name == "decisions" else run["table_hashes"][name]
            assert digest == expected, path
            checked[name] = digest
            tables[name] = read(path)
        provenance_path = directory / "provenance.json"
        assert sha(provenance_path) == run["artifact_hashes"]["provenance.json"]
        provenance = read(provenance_path)
        for name in ("data", "execution", "strategy"):
            relative = "src/quant_research/" + name + ".py"
            digest = sha(directory / "source_snapshot" / relative)
            assert digest == provenance["source_files"][relative]
            source_hashes[relative].add(digest)
        artifact_checks.append({"run_id": run["directory"], "directory": str(directory), "checked_hashes": checked,
                                "table_rows": {k:len(v) for k,v in tables.items()},
                                "original_source_hash": provenance["source_hash"], "original_data_hash": provenance["data_hash"]})
        coverage, found = inspect_run(run, tables, datasets[period], master_groups[period], mismatches[period])
        coverages.append(coverage)
        triggers.extend(found)
        daily, fees, daily_error = daily_attribution(tables["nav"], tables["positions"], tables["fills"], tables["cash_events"], config["initial_cash"])
        year_pnl, year_fees = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
        for day, by_sid in daily.items():
            for sid, value in by_sid.items():
                year_pnl[int(day[:4])][sid] += value
        for day, by_sid in fees.items():
            for sid, value in by_sid.items():
                year_fees[int(day[:4])][sid] += value
        sid_universe = sorted(master_groups[period])
        previous_nav = config["initial_cash"]
        for year in sorted({int(d[:4]) for d in daily}):
            ending = next(r["nav"] for r in reversed(tables["nav"]) if int(r["date"][:4]) == year)
            pnl, target_pnl = sum(year_pnl[year].values()), ending - previous_nav
            error = abs(pnl-target_pnl)
            assert error < 1e-6, (run["directory"], year, error)
            ident = {"run_id": run["directory"], "period": period, "path": run["path"],
                     "initial_cash": config["initial_cash"], "variant": config["variant"],
                     "risk_scaling": config["risk_scaling"], "year": year}
            annual_accounts.append({**ident, "etf_net_pnl_cny": pnl, "account_net_pnl_cny": target_pnl,
                                    "fees_cny": sum(year_fees[year].values()), "reconciliation_error_cny": error,
                                    "daily_reconciliation_max_error_cny": daily_error})
            for sid in sid_universe:
                annual_rows.append({**ident, "instrument_id": sid, "net_pnl_cny": year_pnl[year].get(sid,0.),
                                    "fees_cny": year_fees[year].get(sid,0.)})
            previous_nav = ending
        if config["initial_cash"] == 100000 and run["path"] == "base":
            account = monthly_account(run, tables, datasets[period], master_groups[period], daily)
            monthly.extend(account)
            primary_tables[(period, config["variant"], config["risk_scaling"])] = (run, account, tables, daily)
        if (index+1) % 32 == 0:
            print("audited", index+1, "of448", flush=True)
    common_trend = {(r["period"],r["decision_date"]):r["trend"] for r in monthly if r["variant"]=="E1" and not r["risk_scaling"]}
    for row in monthly:
        row["common_benchmark_trend"] = common_trend[(row["period"],row["decision_date"])]
    paired, pair_years, pair_summaries = [], [], []
    for period in ("development", "validation"):
        for scaled in (False, True):
            for candidate, baseline in (("R0", "E0"), ("R1", "E1")):
                cr, cm, ct, cd = primary_tables[(period, candidate, scaled)]
                br, bm, bt, bd = primary_tables[(period, baseline, scaled)]
                for c, b in zip(cm,bm):
                    assert c["execution_date"] == b["execution_date"]
                    all_ids = set(c["subsequent_net_pnl_by_etf"]) | set(b["subsequent_net_pnl_by_etf"])
                    weights_c, weights_b = c["target_weights"], b["target_weights"]
                    delta = {s:c["subsequent_net_pnl_by_etf"].get(s,0)-b["subsequent_net_pnl_by_etf"].get(s,0) for s in all_ids}
                    paired.append({"period": period, "candidate": candidate, "baseline": baseline,
                        "risk_scaling": scaled, "candidate_run_id": cr["directory"], "baseline_run_id": br["directory"],
                        "decision_date": c["decision_date"], "execution_date": c["execution_date"],
                        "holding_end_inclusive": c["holding_end_inclusive"], "eligible_count": c["eligible_count"],
                        "top3_vs_equal_selection_differs": set(c["selected_ids_before_trend"]) != set(b["selected_ids_before_trend"]),
                        "trend": c["trend"], "target_L1_difference": sum(abs(weights_c.get(s,0)-weights_b.get(s,0)) for s in set(weights_c)|set(weights_b)),
                        "target_gross_difference": c["target_gross"]-b["target_gross"],
                        "net_pnl_increment_cny": c["subsequent_net_pnl_cny"]-b["subsequent_net_pnl_cny"],
                        "sum_paired_daily_returns": c["subsequent_sum_daily_returns"]-b["subsequent_sum_daily_returns"],
                        "net_pnl_increment_by_etf": delta})
                for year in sorted({int(d[:4]) for d in cd}):
                    per_sid = {s:sum(cd[d].get(s,0)-bd[d].get(s,0) for d in cd if int(d[:4])==year)
                               for s in sorted(master_groups[period])}
                    pair_years.append({"period":period,"candidate":candidate,"baseline":baseline,"risk_scaling":scaled,
                                       "year":year,"net_pnl_increment_cny":sum(per_sid.values()),"net_pnl_increment_by_etf":per_sid})
                these = [r for r in paired if (r["period"],r["candidate"],r["risk_scaling"]) == (period,candidate,scaled)]
                total = sum(r["net_pnl_increment_cny"] for r in these)
                expected = ct["nav"][-1]["nav"]-bt["nav"][-1]["nav"]
                assert abs(total-expected)<1e-6
                pair_summaries.append({"period":period,"candidate":candidate,"baseline":baseline,"risk_scaling":scaled,
                    "holding_periods":len(these),"selection_divergent_periods":sum(r["top3_vs_equal_selection_differs"] for r in these),
                    "target_divergent_periods":sum(r["target_L1_difference"]>1e-12 for r in these),
                    "paired_net_pnl_cny":total,"holding_period_to_account_reconciliation_error_cny":abs(total-expected)})
    csv_out("annual_etf_pnl_all448.csv", annual_rows)
    csv_out("annual_account_reconciliation_all448.csv", annual_accounts)
    dump("monthly_primary16.json", monthly)
    dump("holding_period_pairs_primary8.json", paired)
    dump("annual_pairs_primary8.json", pair_years)
    dump("paired_summary_primary8.json", pair_summaries)
    dump("effective_interval_run_coverage.json", coverages)
    dump("effective_interval_trigger_contexts.json", triggers)
    dump("input_hash_manifest.json", {"results_summary_sha256":sha(summary_path),"dataset_file_hashes":hashes,
                                   "frozen_source_file_hashes":{k:sorted(v) for k,v in source_hashes.items()},"runs":artifact_checks})
    dump("repeat_exposure_counterexample.json", repeat_exposure_counterexample())
    actual = [r for r in triggers if r["scope"] in {"HELD_OPEN_AND_CLOSE","ORDER_CREATION","ORDER_EXECUTION","EXECUTION_EVENT","TARGET_RELEASE","CORPORATE_ACTION_METADATA","SHARE_EVENT_METADATA"}]
    row_totals = Counter()
    for check in artifact_checks:
        row_totals.update(check["table_rows"])
    summary = {"status":"READ_ONLY_FROZEN_REVIEW_COMPLETE", "runs":len(coverages),"primary_accounts":len(primary_tables),
        "checked_table_row_totals":dict(row_totals),
        "primary_monthly_rows":len(monthly),"holding_period_pair_rows":len(paired),"annual_etf_rows":len(annual_rows),
        "annual_account_rows":len(annual_accounts),"annual_zero_etf_rows":sum(r["net_pnl_cny"]==0 for r in annual_rows),
        "max_annual_reconciliation_error_cny":max(r["reconciliation_error_cny"] for r in annual_accounts),
        "max_daily_reconciliation_error_cny":max(r["daily_reconciliation_max_error_cny"] for r in annual_accounts),
        "metadata_discrepancy_grid_rows":len(grid),"metadata_discrepancy_contexts":len(triggers),
        "master_availability_clock_verified":"All 202 master rows 21:00; EOD share-action 15:00 lookups equal 09:30 selections and are explicitly queried at 15:00.",
        "actual_execution_dependency_discrepancies":len(actual),
        "actual_affected_run_ids":sorted({r["run_id"] for r in actual}),
        "metadata_discrepancy_query_scopes":dict(Counter(r["scope"] for r in triggers)),
        "max_recorded_sigma_error":max(r["recorded_sigma_absolute_error"] or 0 for r in monthly),
        "original_shrink_to_direct_sigma_range":[min(r["ungated_original_50pct_shrink_sigma"]/r["ungated_direct_annualized_sigma"] for r in monthly),max(r["ungated_original_50pct_shrink_sigma"]/r["ungated_direct_annualized_sigma"] for r in monthly)],
        "scaled_monthly_targets_direct_sample_sigma_above_10pct":sum(r["risk_scaling"] and r["target_direct_sigma"]>.100000001 for r in monthly),
        "scaled_monthly_target_count":sum(r["risk_scaling"] for r in monthly),
        "max_scaled_target_direct_sample_sigma":max(r["target_direct_sigma"] for r in monthly if r["risk_scaling"]),
        "master_effective_to_present_rows":sum(bool(r.get("effective_to")) for d in datasets.values() for r in d["instruments"]),
        "frozen_summary_sha256":sha(summary_path),"script_sha256":sha(__file__),
        "scope":"Existing448 account artifacts and original admitted input only; no strategy replay, no new parameter/shrinkage search, no production imports, no holdout access.",
        "unknowns":["Missing effective_to means expiry logic has no real-data test in these inputs.",
          "No complete persisted trace of every internal master lookup exists; event/position/order coverage is a conservative reconstruction from frozen source and artifacts, not instrumented execution.",
          "Old master_asof is availability-only. Its whole-universe differences do not prove it was called on an execution-sensitive path; no persisted per-call trace.",
          "Current correction-chain/no-revival refinements are a separate semantic design, not a retroactive reinterpretation of frozen strategy outputs.",
          "Repeated ETF exposure counterexample demonstrates estimator representation dependence, not actual complete ETF return identity or a superior alternative.",
          "No ETF holdings look-through or causal factor model is available. Index-family counts and correlated returns are proxies, not independent economic exposures.",
          "Holding-period attribution means fixed rebalance execution-to-next-execution intervals, including all fills/fees/blocked positions; it is not FIFO trade attribution.",
          "Daily prices and modeled cash settlement retain all original data/execution limitations; fixed incremental costs remain unknown."]}
    dump("summary.json", summary)
    lines = ["# Frozen R1 temporal impact and exposure review", "",
        "Read-only review of the existing 448 runs; primary capital 100,000 CNY. No replay, new market test, parameter grid, shrinkage scan, production import, or 2025–2026 holdout access.", "",
        "Audit repair disclosure: the first read-only audit draft overwrote query scope with ACCOUNT/WARMUP, making its initial zero-impact classification invalid. The draft summary/context/coverage, hashes and exact repair are preserved in superseded_audit_draft. The corrected audit was rerun over all 448 artifacts and a focused injected-impact regression test now detects the failure. This was an audit repair, not a strategy trial.", "",
        "## Temporal impact", "",
        f"The frozen execution.master and data.master_asof choose the latest available row without effective interval checks. Original strategy._snapshot uses half-open [effective_from,effective_to) intervals before latest-publication selection. The full input grid has {len(grid)} differing metadata lookups; {len(triggers)} contexts occur in the 448 reconstructed query inventories. Observed execution-dependent discrepancies: {len(actual)}. These counts are distinct from changed orders or PnL.", "",
        "All master effective_to fields are null. Most raw differences are public listing announcements before the listing effective date. The dated sz.159908 index transition from SZ_FUNDAMENTAL200/OUTSIDE to CHINEXT/R1B is available 2018-12-05, effective 2018-12-10; it remains an ETF. Raw differing clocks are retained, with exact security/date/revision IDs. The instrument is absent from affected held/order paths. Current correction-chain and expiry/no-revival semantics are separate from this frozen interpretation.", "",
        "Coverage reconstructs held positions at open and close, order creation/execution/events, target dependencies, corporate/share actions, full master queries at signal anchors and quarter selection dates. This is not a persisted internal lookup trace. No observed execution trigger is evidence against blanket invalidation; it does not prove every conceivable defect absent.", "",
        "Original EOD share actions use 15:00; all 202 frozen master rows have availability 21:00, explicitly verified, so their 15:00 lookup state equals 09:30. The raw grid lists 09:30/21:00 while EOD queries use their equivalent 15:00 state.", "",
        "## Monthly opportunity set and original risk estimator", "",
        "monthly_primary16.json records every eligible ID/index family, exclusions, selection, common trend, target and actual close weights, direct portfolio return volatility, the original 50% shrink estimate and multiplier, and subsequent holding-window account risk. Dates separate anchor D, released decision D+1, and base execution D+2. Forward risk never enters historical decisions. The source estimates reproduce saved sigma exactly.", "",
        "| Sample | Monthly eligible-count frequency | Trend off / decisions |", "|---|---|---|"]
    for period in ("development","validation"):
        these = [r for r in monthly if r["period"]==period and r["variant"]=="E0" and not r["risk_scaling"]]
        lines.append(f"| {period} | {dict(sorted(Counter(r['eligible_count'] for r in these).items()))} | {sum(not r['common_benchmark_trend'] for r in these)}/{len(these)} |")
    lines += ["", f"Original shrunk/direct sigma ratios range {summary['original_shrink_to_direct_sigma_range'][0]:.6f}–{summary['original_shrink_to_direct_sigma_range'][1]:.6f}. Of 432 scaled primary monthly targets (including cash), {summary['scaled_monthly_targets_direct_sample_sigma_above_10pct']} have direct historical target volatility above 10%; maximum {summary['max_scaled_target_direct_sample_sigma']:.4%}. This is estimator disagreement on the same trailing sample, not a promised or future risk bound. Subsequent realized risk is separately recorded and does not establish forecasting calibration.", "",
        "The deterministic repeated-exposure design test uses 3/6/9 identical names and the unchanged original estimator, respecting 35% name caps. Equal splitting leaves direct risk unchanged while diagonal shrink lowers estimated risk by sqrt(0.5+0.5/n). No alternative shrink value or market return is searched. Actual ETFs need not be identical; index families and observed return dependence are not holdings look-through or causal factor attribution.", "",
        "## Net PnL and holding-period contributions", "",
        "| Sample | Pair | Scaling | Selection-different intervals | Net paired PnL CNY |", "|---|---|---|---:|---:|"]
    for r in pair_summaries:
        lines.append(f"| {r['period']} | {r['candidate']}−{r['baseline']} | {r['risk_scaling']} | {r['selection_divergent_periods']}/{r['holding_periods']} | {r['paired_net_pnl_cny']:.2f} |")
    lines += ["", f"Annual attribution covers all 448 runs, 2,016 account-years and 182,784 ETF-year rows, retaining 172,624 zero-PnL rows. Maximum account-year reconciliation error is {summary['max_annual_reconciliation_error_cny']:.3g} CNY; daily maximum {summary['max_daily_reconciliation_error_cny']:.3g} CNY. Formula: marked value change + sale notional − purchase notional − all fill fees + recognized dividend receivables. Payment is not income twice. Slippage is already in fill prices and is not deducted again. Annual boundaries carry prior-year marked value; development and validation start with separate initial cash.", "",
        "The 432 paired holding intervals run execution day through the day before next execution; ETF contributions and fees include retained/blocked positions. They reconcile to each pair's account difference. This is rebalance-window accounting, not FIFO completed trades or causal momentum alpha. Annual pairs retain 2016–2017 zero differences. PnL is additive CNY, not the registered mean daily-return endpoint and not a fixed-cost budget.", "",
        "## Limits and provenance", "",
        *["- "+x for x in summary["unknowns"]], "",
        f"Original result summary SHA256: `{sha(summary_path)}`. Original source and data hashes, every read artifact hash and row count are in input_hash_manifest.json. Frozen execution/data/strategy files were checked for all 448 runs, independently of current production source. Reproduce with `python scripts/m4_frozen_review.py`; focused design checks: `python -m pytest tests/test_m4_frozen_design.py -q`.", "",
        "Disposition: no temporal-impact evidence supports replaying or blanket-invalidating 448. Existing economic/evidence limitations and ARCHIVE_CURRENT_CONFIGURATION / STOP_ETF_PARAMETER_SEARCH remain. The risk design limitation does not authorize estimator replacement, parameter optimization, paper or live deployment.", ""]
    (OUT / "REVIEW.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    run_review()
