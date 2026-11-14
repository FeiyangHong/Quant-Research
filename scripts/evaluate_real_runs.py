"""Audit and describe both complete registered real-data matrices; never select a winner.

Usage: python scripts/evaluate_real_runs.py --development runs/real_r1_development_v2
       --validation runs/real_r1_validation_v2 --output reports/real_data_phase3
No output is written until all 448 completed runs and retained failed attempts pass audit.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from quant_research.evaluation import holm_four, nav_metrics, paired_inference
from quant_research.provenance import digest, source_provenance, validate_run_config, write_json
from scripts.summarize_runs import grouped, reconcile


CAPITALS = (10000, 100000, 500000, 1000000)
VARIANTS = ("E0", "R0", "E1", "R1")
PATHS = {(1, 1, 1, 0): "base", (2, 2, 1, 0): "cost2_slip2",
         (3, 3, 1, 0): "cost3_slip3", (1, 0, 1, 0): "slip0",
         (1, 1, 2, 0): "delay2", (1, 1, 1, 1): "cash_delay1",
         (1, 1, 1, 3): "cash_delay3"}
PERIODS = {"development": (2016, 2021), "validation": (2022, 2024)}
BLOCKS = (60, 20, 120)
REPETITIONS = 5000
SEED = 20261114
PRIMARY_CAPITAL = 100000
REQUIRED_TABLES = {"nav", "positions", "fills", "orders", "costs", "rejected_orders",
                   "cash_events", "exposure", "order_events", "rights", "share_events"}
LEDGER_TABLES = ("nav", "positions", "fills", "costs", "cash_events")
GRID_FIELDS = {"initial_cash", "variant", "risk_scaling", "cost_multiplier",
               "slippage_multiplier", "execution_delay", "cash_delay_sessions"}
NOTICE = ("Historical daily simulation, not realized account profit or a final holdout test. "
          "2022–2024 is validation. 2025–2026 remains locked. Annual incremental operating "
          "cost is unknown; formal economic confirmation is BLOCKED_HURDLE. "
          "No factor alpha is estimated without factor returns. No winning configuration is selected.")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + value)))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def child(root, name):
    root = Path(root).resolve()
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Run directory must be a direct child")
    destination = (root / name).resolve()
    if destination.parent != root:
        raise ValueError("Run directory escapes matrix root")
    return destination


def config_key(config):
    return (config["initial_cash"], config["variant"], config["risk_scaling"],
            config.get("cost_multiplier", 1), config.get("slippage_multiplier", 1),
            config.get("execution_delay", 1), config.get("cash_delay_sessions", 0))


def expected_keys():
    return {(capital, variant, scaling, *path) for capital, variant, scaling, path in
            itertools.product(CAPITALS, VARIANTS, (False, True), PATHS)}


def validate_grid(entries, period):
    if period not in PERIODS or not isinstance(entries, list):
        raise ValueError("Require development and validation matrix lists")
    keys, names, fixed = [], [], []
    for entry in entries:
        config = entry["config"]
        validate_run_config(config)
        if (config["sample"] != period or config.get("signal_release_delay") != 1
                or config.get("annual_incremental_cost") is not None):
            raise ValueError("Period, one-session signal release, or unknown hurdle contract mismatch")
        if type(config.get("risk_scaling")) is not bool:
            raise ValueError("Explicit risk_scaling boolean required")
        keys.append(config_key(config))
        names.append(entry["directory"])
        fixed.append(digest({k: v for k, v in config.items() if k not in GRID_FIELDS}))
    expected = expected_keys()
    if len(keys) != len(set(keys)) or set(keys) != expected or len(names) != len(set(names)):
        raise ValueError(f"Require all 224 unique configurations in {period}: got {len(keys)}, "
                         f"missing {len(expected - set(keys))}, unexpected {len(set(keys) - expected)}")
    if len(set(fixed)) != 1:
        raise ValueError("Non-grid configuration settings differ within period")
    return {config_key(entry["config"]): entry for entry in entries}


def _verify_identity(directory, config, registered):
    provenance = read_json(directory / "provenance.json")
    if read_json(directory / "config.json") != config or registered["config"] != config:
        raise ValueError("Registered configuration differs from run artifact")
    if provenance.get("run_id") != directory.name or registered["run_id"] != directory.name:
        raise ValueError("Run identity mismatch")
    identity = {field: provenance.get(field) for field in ("config_hash", "data_hash", "source_hash")}
    if identity["config_hash"] != digest(config) or any(registered.get(k) != v for k, v in identity.items()):
        raise ValueError("Registered provenance hashes disagree")
    if any(not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None for v in identity.values()):
        raise ValueError("Invalid provenance digest")
    if not directory.name.startswith(digest(identity)[:16] + "-"):
        raise ValueError("Run id does not bind configuration/data/source identity")
    return provenance


def audit_registry(matrix_root, entries):
    matrix_root = Path(matrix_root)
    if (matrix_root / ".runner.lock").exists():
        raise ValueError("Matrix writer is still active")
    path = matrix_root / "trial_registry.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    registrations, terminals, order = {}, {}, {}
    for i, event in enumerate(records):
        kind, run_id = event.get("event"), event.get("run_id")
        if kind == "REGISTERED":
            if run_id in registrations:
                raise ValueError("Duplicate registry registration")
            registrations[run_id], order[run_id] = event, i
        elif kind in ("COMPLETED", "FAILED"):
            if run_id not in registrations or run_id in terminals:
                raise ValueError("Registry terminal event without unique prior registration")
            terminals[run_id] = event
        else:
            raise ValueError("Unknown or invalidated registry event: " + str(kind))
    if set(registrations) != set(terminals):
        raise ValueError("Pending registered attempts remain")
    completed = {k for k, v in terminals.items() if v["event"] == "COMPLETED"}
    manifest_ids = {entry["directory"] for entry in entries}
    if completed != manifest_ids:
        raise ValueError("Completed registry attempts and matrix manifest disagree")
    observed_dirs = {p.name for p in matrix_root.iterdir() if p.is_dir() and
                     any((p / name).exists() for name in ("config.json", "failure.json", "nav.json"))}
    if observed_dirs != set(registrations):
        raise ValueError("Unregistered or missing run directories")
    failures = []
    for run_id, terminal in terminals.items():
        if terminal["event"] != "FAILED":
            continue
        directory = child(matrix_root, run_id)
        registered = registrations[run_id]
        provenance = _verify_identity(directory, registered["config"], registered)
        failure = read_json(directory / "failure.json")
        if any(failure.get(k) != terminal.get(k) for k in ("run_id", "event", "error", "reason")):
            raise ValueError("Failed attempt artifact differs from registry")
        later = [k for k in sorted(completed) if order[k] > order[run_id]
                 and registrations[k]["config"] == registered["config"]]
        failures.append({"run_id": run_id, "config": registered["config"], "failure": failure,
                         "provenance_identity": {k: provenance[k] for k in ("config_hash", "data_hash", "source_hash")},
                         "artifact_hashes": {name: sha256(directory / name) for name in
                                             ("config.json", "provenance.json", "failure.json")},
                         "later_same_config_completed_runs": later,
                         "correction_evidence": "Later exact-config completion only; no inferred causal explanation."
                         if later else "No later exact-config completion; failed attempt retained separately."})
    return registrations, terminals, {"status": "PASS", "registry_sha256": sha256(path),
            "registered_attempts": len(registrations), "completed_attempts": len(completed),
            "failed_attempts": len(failures), "failures": failures,
            "scope": "Local recorded integrity and chronology, not external timestamp authentication."}


def _verify_source_snapshot(directory, provenance):
    files = provenance.get("source_files")
    if not files or digest(files) != provenance["source_hash"]:
        raise ValueError("Source manifest digest mismatch")
    snapshot = (directory / "source_snapshot").resolve()
    actual = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    if actual != set(files):
        raise ValueError("Source snapshot inventory mismatch")
    for relative, expected in files.items():
        path = (snapshot / relative).resolve()
        if snapshot not in path.parents or sha256(path) != expected:
            raise ValueError("Source snapshot hash mismatch: " + relative)


def verify_run(directory, entry, registered, completed, period):
    """Verify one registered real run, then rebuild its independent accounting arithmetic."""
    directory = Path(directory)
    config = entry["config"]
    provenance = _verify_identity(directory, config, registered)
    _verify_source_snapshot(directory, provenance)
    audit = read_json(directory / "data_audit.json")
    if (audit.get("status") != "PASSED" or audit.get("performance_evidence") is not True
            or audit.get("errors") or audit.get("blockers")):
        raise ValueError("Run did not pass real-data admission audit")
    metrics = read_json(directory / "metrics.json")
    if (metrics != entry["metrics"] or metrics.get("run_id") != directory.name
            or metrics.get("status") != "DAILY_SCREEN_ONLY"
            or metrics.get("economic_confirmation") != "BLOCKED_HURDLE"
            or completed.get("status") != metrics["status"]):
        raise ValueError("Metric identity/status differs from manifest or registry")
    assumptions = read_json(directory / "execution_assumptions.json")
    hashes = read_json(directory / "table_hashes.json")
    if not REQUIRED_TABLES.issubset(hashes) or completed.get("table_hashes") != hashes:
        raise ValueError("Required table hashes absent or not registry-bound")
    tables = {}
    for name, expected in hashes.items():
        if re.fullmatch(r"[a-z_]+", name) is None:
            raise ValueError("Invalid table name")
        path = directory / (name + ".json")
        if sha256(path) != expected:
            raise ValueError(f"Table hash mismatch: {directory.name}/{name}")
        records = read_json(path)
        if not isinstance(records, list):
            raise ValueError("Table must contain JSON records")
        tables[name] = pd.DataFrame(records)
        if "date" in tables[name] and any(str(day) >= "2025-01-01" for day in tables[name].date):
            raise ValueError("Locked final holdout date present")
    # Share-event metadata may predate the funded account; it is not a cash/NAV entry.
    check = reconcile({name: tables[name] for name in LEDGER_TABLES}, config["initial_cash"])
    nav = tables["nav"]
    start, end = PERIODS[period]
    if (any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)) is None for d in nav.date)
            or nav.date.min() < f"{start}-01-01" or nav.date.max() > f"{end}-12-31"
            or {int(d[:4]) for d in nav.date} != set(range(start, end + 1))):
        raise ValueError("NAV account period is incomplete or outside registered years")
    recomputed = nav_metrics(nav, config["initial_cash"])
    for field, value in recomputed.items():
        observed = metrics.get(field)
        if field == "warning":
            continue
        if value is None:
            if observed is not None:
                raise ValueError("NAV metric mismatch: " + field)
        elif not isinstance(observed, (int, float)) or not math.isclose(observed, value, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("NAV metric mismatch: " + field)
    result, returns = summarize_tables(tables, config)
    result.update(period=period, directory=directory.name, config=config,
                  path=PATHS[config_key(config)[3:]], metrics=recomputed, ledger_reconciliation=check,
                  execution_assumptions=assumptions,
                  provenance={k: provenance[k] for k in ("source_hash", "data_hash", "config_hash", "git_commit")},
                  artifact_hashes={name: sha256(directory / name) for name in
                                   ("config.json", "provenance.json", "data_audit.json", "metrics.json",
                                    "table_hashes.json", "decisions.json", "execution_assumptions.json")},
                  table_hashes=hashes)
    return result, returns, provenance["source_files"]


def summarize_tables(tables, config):
    nav, fills, positions, rejected = (tables[k] for k in ("nav", "fills", "positions", "rejected_orders"))
    dates = pd.Index(nav.date, name="date")
    equity = pd.Series(nav.nav.to_numpy(dtype=float), index=dates)
    prior = equity.shift(1).fillna(config["initial_cash"])
    returns = equity / prior - 1
    fees = grouped(fills, dates, "fees")
    turnover = .5 * grouped(fills, dates, "notional") / prior
    cash = pd.Series(nav.cash_total.to_numpy(dtype=float), index=dates) / equity
    gross = pd.Series(nav.holdings_value.to_numpy(dtype=float), index=dates) / equity
    if positions.empty:
        maximum = hhi = counts = pd.Series(0., index=dates)
    else:
        marked = positions.copy()
        marked["capital_weight"] = marked.market_value / marked.date.map(equity)
        marked["squared_weight"] = marked.capital_weight ** 2
        maximum = marked.groupby("date").capital_weight.max().reindex(dates, fill_value=0.)
        hhi = grouped(marked, dates, "squared_weight")
        counts = marked.loc[marked.quantity.gt(0)].groupby("date").size().reindex(dates, fill_value=0)
    year_rows = []
    for year in sorted({d[:4] for d in dates}):
        mask = dates.str.startswith(year)
        pnl = float((equity - prior).loc[mask].sum())
        year_rows.append({"year": int(year), "pnl_cny": pnl,
                          "additive_return_contribution_initial_capital": pnl / config["initial_cash"],
                          "year_return": float((1 + returns.loc[mask]).prod() - 1),
                          "fees_cny": float(fees.loc[mask].sum()),
                          "one_way_turnover": float(turnover.loc[mask].sum()),
                          "mean_cash_weight": float(cash.loc[mask].mean()),
                          "mean_gross_exposure": float(gross.loc[mask].mean()),
                          "maximum_single_instrument_weight": float(maximum.loc[mask].max())})
    def total(column):
        return float(fills[column].sum()) if not fills.empty else 0.
    return {"first_account_date": dates[0], "last_account_date": dates[-1],
            "account_dates_sha256": digest(dates.tolist()), "ending_nav_cny": float(equity.iloc[-1]),
            "fills": len(fills), "order_intents": len(tables["orders"]), "rejection_events": len(rejected),
            "rejected_order_ids": int(rejected.order_id.nunique()) if not rejected.empty else 0,
            "rejection_reasons": {str(k): int(v) for k, v in rejected.reason.value_counts().items()} if not rejected.empty else {},
            "fees_cny": float(fees.sum()), "commission_cny": total("commission"),
            "stamp_duty_cny": total("stamp_duty"), "transfer_fee_cny": total("transfer_fee"),
            "slippage_cny": total("slippage_cost"), "traded_notional_cny": total("notional"),
            "one_way_turnover": float(turnover.sum()),
            "annualized_one_way_turnover_252": float(turnover.sum() * 252 / len(dates)),
            "mean_cash_weight": float(cash.mean()), "ending_cash_weight": float(cash.iloc[-1]),
            "mean_gross_exposure": float(gross.mean()), "maximum_gross_exposure": float(gross.max()),
            "maximum_single_instrument_weight": float(maximum.max()),
            "mean_largest_instrument_weight": float(maximum.mean()),
            "mean_sum_squared_instrument_capital_weights": float(hhi.mean()),
            "mean_positive_position_count": float(counts.mean()),
            "valuation_uncertainty_sessions": int(nav.valuation_uncertainty.sum()) if "valuation_uncertainty" in nav else None,
            "maximum_position_stale_sessions": int(positions.stale_days.max())
                if not positions.empty and "stale_days" in positions else None,
            "ending_receivables_cny": float(nav.receivables.iloc[-1]), "year_contributions": year_rows}, returns


def inference_for_pair(candidate, baseline):
    common = {"primary_capital": PRIMARY_CAPITAL, "repetitions": REPETITIONS, "seed": SEED}
    return {"formal": paired_inference(candidate, baseline, annual_incremental_cost=None,
                                       block_length=60, **common),
            "exploratory_zero_hurdle": {
                "status": "EXPLORATORY_ZERO_INCREMENTAL_COST_ASSUMPTION",
                "annual_incremental_cost_assumed_cny": 0,
                "multiplicity_confirmed": False,
                "factor_alpha": False,
                "interpretation": "Marginal paired diagnostics only; unknown time/operating costs are assumed zero. "
                                  "Not economic confirmation, final testing, or a registered primary-candidate selection.",
                "main_block_length": 60,
                "blocks": [paired_inference(candidate, baseline, annual_incremental_cost=0,
                                            block_length=block, **common) for block in BLOCKS]}}


def comparisons(results, series):
    paired, stresses, sizes = [], [], []
    for period, capital, scaling, path in itertools.product(PERIODS, CAPITALS, (False, True), PATHS):
        for candidate, baseline in (("R0", "E0"), ("R1", "E1")):
            a, b = (period, capital, candidate, scaling, *path), (period, capital, baseline, scaling, *path)
            delta = series[a] - series[b]
            year_a = {y["year"]: y for y in results[a]["year_contributions"]}
            year_b = {y["year"]: y for y in results[b]["year_contributions"]}
            row = {"period": period, "candidate": candidate, "baseline": baseline,
                   "initial_cash": capital, "risk_scaling": scaling, "path": PATHS[path], "n_dates": len(delta),
                   "mean_daily_net_increment": float(delta.mean()),
                   "terminal_return_difference": results[a]["metrics"]["total_return"] - results[b]["metrics"]["total_return"],
                   "cagr_difference": results[a]["metrics"]["cagr"] - results[b]["metrics"]["cagr"],
                   "fee_difference_cny": results[a]["fees_cny"] - results[b]["fees_cny"],
                   "one_way_turnover_difference": results[a]["one_way_turnover"] - results[b]["one_way_turnover"],
                   "annual_differences": [{"year": int(y), "mean_daily_net_increment": float(delta.loc[delta.index.str.startswith(y)].mean()),
                       "pnl_difference_cny": year_a[int(y)]["pnl_cny"] - year_b[int(y)]["pnl_cny"],
                       "additive_return_contribution_difference": year_a[int(y)]["additive_return_contribution_initial_capital"]
                       - year_b[int(y)]["additive_return_contribution_initial_capital"]}
                                          for y in sorted({d[:4] for d in delta.index})]}
            if capital == PRIMARY_CAPITAL and PATHS[path] == "base":
                row["uncertainty"] = inference_for_pair(series[a], series[b])
            else:
                row["uncertainty"] = {"status": "DESCRIPTIVE_SCENARIO_ONLY", "p_net": None, "ci95": None}
            paired.append(row)
        for variant in VARIANTS:
            key = (period, capital, variant, scaling, *path)
            row = results[key]
            common = {"period": period, "initial_cash": capital, "variant": variant,
                      "risk_scaling": scaling, "path": PATHS[path]}
            if PATHS[path] != "base":
                base = results[(period, capital, variant, scaling, 1, 1, 1, 0)]
                difference = row["metrics"]["total_return"] - base["metrics"]["total_return"]
                stresses.append(dict(common, terminal_return_difference=difference,
                    direction="LOWER" if difference < -1e-12 else "HIGHER" if difference > 1e-12 else "UNCHANGED",
                    cagr_difference=row["metrics"]["cagr"] - base["metrics"]["cagr"],
                    max_drawdown_difference=row["metrics"]["max_drawdown"] - base["metrics"]["max_drawdown"],
                    fee_difference_cny=row["fees_cny"] - base["fees_cny"],
                    turnover_difference=row["one_way_turnover"] - base["one_way_turnover"],
                    rejection_event_difference=row["rejection_events"] - base["rejection_events"]))
            if capital != PRIMARY_CAPITAL:
                primary = results[(period, PRIMARY_CAPITAL, variant, scaling, *path)]
                sizes.append(dict(common, reference_capital=PRIMARY_CAPITAL,
                    total_return_difference=row["metrics"]["total_return"] - primary["metrics"]["total_return"],
                    fees_fraction_initial_capital=row["fees_cny"] / capital,
                    cash_weight_difference=row["mean_cash_weight"] - primary["mean_cash_weight"],
                    rejection_event_difference=row["rejection_events"] - primary["rejection_events"]))
    return paired, stresses, sizes


def evaluate(development, validation, output):
    # Post-processing has its own version. Never pretend an amended checker
    # was part of the earlier engine execution or rewrite any run artifact.
    evaluation_provenance = source_provenance(ROOT)
    roots = {"development": Path(development).resolve(), "validation": Path(validation).resolve()}
    if roots["development"] == roots["validation"]:
        raise ValueError("Development and validation require separate fresh-account matrices")
    results, series, registry_audits, manifests, grids, sources = {}, {}, {}, {}, {}, {}
    for period, root in roots.items():
        entries = read_json(root / "matrix_summary.json")
        grids[period] = validate_grid(entries, period)
        manifests[period] = sha256(root / "matrix_summary.json")
        registered, completed, registry_audits[period] = audit_registry(root, entries)
        for key in sorted(grids[period]):
            entry = grids[period][key]
            name = entry["directory"]
            row, returns, source_files = verify_run(child(root, name), entry, registered[name], completed[name], period)
            results[(period, *key)], series[(period, *key)] = row, returns
            sources[row["provenance"]["source_hash"]] = source_files
        period_rows = [row for key, row in results.items() if key[0] == period]
        if len({row["provenance"]["data_hash"] for row in period_rows}) != 1:
            raise ValueError("Data snapshot changes within a period")
        if len({row["account_dates_sha256"] for row in period_rows}) != 1:
            raise ValueError("Account calendars differ between paired runs")
    if len(sources) != 1:
        raise ValueError("Source snapshot changes across the 448 completed runs")
    frozen_sources = next(iter(sources.values()))
    # Report orchestration/reconciliation may be repaired after execution and
    # is independently bound above. Statistical definitions and identity logic
    # must still equal the original, verified execution snapshot.
    for relative in ("src/quant_research/evaluation.py", "src/quant_research/provenance.py"):
        if frozen_sources.get(relative) != sha256(ROOT / relative):
            raise ValueError("Evaluator source differs from run snapshot: " + relative)
    fixed_configs = {digest({k: v for k, v in row["config"].items() if k not in GRID_FIELDS | {"sample"}})
                     for row in results.values()}
    if len(fixed_configs) != 1:
        raise ValueError("Non-period/non-grid settings differ between account periods")
    paired, stresses, sizes = comparisons(results, series)
    ordered = [results[(period, capital, variant, scaling, *path)] for period, capital, variant, scaling, path in
               itertools.product(PERIODS, CAPITALS, VARIANTS, (False, True), PATHS)]
    formal_families = {family: {"status": "NOT_READY", "p_value_placeholder": 1.,
                        "reasons": ["HURDLE_UNKNOWN", "PRIMARY_FINAL_CANDIDATE_UNFROZEN"] if family == "R1"
                        else ["FAMILY_NOT_EVALUATED"]} for family in ("R1", "R2", "R3", "R4")}
    report = {"schema_version": "real-matrix-evaluation-1.0", "status": "DESCRIPTIVE_DAILY_SCREEN_ONLY",
              "notice": NOTICE, "run_count": len(ordered), "primary_capital_cny": PRIMARY_CAPITAL,
              "annual_incremental_cost_cny": None, "economic_confirmation": "BLOCKED_HURDLE",
              "final_holdout_accessed": False, "factor_alpha": None,
              "periods": {p: {"start_year": y[0], "end_year": y[1], "fresh_account": True,
                               "role": p, "is_final_holdout": False} for p, y in PERIODS.items()},
              "provenance": {"matrix_roots": {k: str(v) for k, v in roots.items()},
                  "matrix_manifest_sha256": manifests, "source_hash": next(iter(sources)),
                  "evaluator_sha256": sha256(Path(__file__)),
                  "data_hashes": {p: sorted({r["provenance"]["data_hash"] for r in ordered if r["period"] == p}) for p in PERIODS}},
              "evaluation_provenance": evaluation_provenance,
              "grid": {"capitals": CAPITALS, "variants": VARIANTS, "risk_scaling": [False, True],
                  "signal_release_delay": 1, "paths": [{"label": label, "cost_multiplier": p[0],
                  "slippage_multiplier": p[1], "execution_delay": p[2], "cash_delay_sessions": p[3]}
                  for p, label in PATHS.items()]},
              "method": {"timing": "Anchor D, decision D+1, baseline execution D+2; delay2 executes D+3 (trading sessions).",
                  "ledger": "Independent event/position arithmetic; not independent price or source-fact verification. Pre-NAV share metadata is excluded from account entries.",
                  "calendar": "Each period requires identical unique chronological account dates across all configurations, all registered years, and no dates outside the account period.",
                  "turnover": "Sum of 0.5 * absolute daily filled notional / prior NAV; annualized by 252/session count.",
                  "costs": "Fees debit cash; slippage is embedded in execution prices and is not deducted twice.",
                  "sharpe": "252-session annualization and zero cash return; no risk-free or factor adjustment.",
                  "concentration": "Instrument market values / total NAV, including cash in denominator; post-market-move weights can exceed target caps.",
                  "yearly": "Year returns compound; year CNY NAV changes / initial capital are additive contributions.",
                  "stress": "Every path is compared with its matching base. Changed fills and cash constraints can make stress directions non-monotonic; no outcome is dropped.",
                  "inference": "100k/base R0-E0 and R1-E1 for both scalings, separately by period; HAC-studentized null-centered circular block bootstrap, 5000 draws, main60 and sensitivity20/120. Marginal exploratory intervals, no multiplicity-confirmed significance.",
                  "formal_families": "All four registered families retained as not-ready p=1 placeholders; no endpoint is selected or aggregated from exploratory contrasts."},
              "registry_audits": registry_audits,
              "ledger_reconciliation": {"status": "ALL_PASS", "runs_checked": len(ordered), "tolerance_cny": 1e-6},
              "valuation_review": {"accounting_timing_ineligible_runs": [r["directory"] for r in ordered
                  if r["execution_assumptions"].get("accounting_timing_eligible") is not True],
                  "runs_with_uncertain_valuation": [r["directory"] for r in ordered if r["valuation_uncertainty_sessions"]],
                  "interpretation": "Uncertain valuation or timing cannot support economic confirmation; all affected outcomes remain visible."},
              "formal_four_families": formal_families,
              "formal_holm_placeholders": holm_four({family: 1. for family in formal_families}),
              "runs": ordered, "paired_effects": paired, "stress_effects": stresses, "capital_effects": sizes}
    # Validate serializability and finite numbers before creating any deliverable.
    digest(report)
    markdown = render_report(report)
    output = Path(output)
    if any(output.resolve() == root or root in output.resolve().parents for root in roots.values()):
        raise ValueError("Evaluation output must not modify either input matrix")
    output.mkdir(parents=True, exist_ok=True)
    for relative, expected in evaluation_provenance["source_files"].items():
        content = (ROOT / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Evaluation source changed while computing the report")
        target = output / "evaluation_source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != content:
            raise ValueError("Existing evaluation source snapshot differs; use a new output version")
        target.write_bytes(content)
    write_json(output / "evaluation_provenance.json", evaluation_provenance)
    temporary = output / "results_summary.json.tmp"
    write_json(temporary, report)
    temporary.replace(output / "results_summary.json")
    temporary = output / "RESULTS.md.tmp"
    temporary.write_text(markdown, encoding="utf-8")
    temporary.replace(output / "RESULTS.md")
    return report


def render_report(report):
    def percent(value):
        return "null" if value is None else f"{value:.2%}"
    def number(value):
        return "null" if value is None else f"{value:.3f}"
    failures = sum(a["failed_attempts"] for a in report["registry_audits"].values())
    timing_gaps = len(report["valuation_review"]["accounting_timing_ineligible_runs"])
    lines = ["# Registered real-data matrix evaluation", "", NOTICE, "",
             f"All {report['run_count']} completed configurations passed table/source hash, registry and independent ledger arithmetic checks. "
             f"The registries retain {failures} failed attempts, with reasons and later exact-config completions in JSON.", "",
             f"Accounting timing is unverified or ineligible in {timing_gaps} runs; affected run IDs and valuation flags remain in JSON. "
             "Cash settlement is historical rule-based simulation when so recorded, not proof of personal broker receipt.", "",
             "Primary capital is CNY100,000. Each period starts with fresh cash. Formal four-family p=1 values are not-ready placeholders, not test results. "
             "The unknown incremental operating-cost hurdle prevents economic confirmation.", "",
             "100k base-path comparisons (all four contrasts per period; no preferred configuration):", "",
             "| Period | Candidate − baseline | Scaling | Daily increment bp | Total-return difference | Formal status |",
             "|---|---|---|---:|---:|---|"]
    main = [r for r in report["paired_effects"] if r["initial_cash"] == PRIMARY_CAPITAL and r["path"] == "base"]
    for row in main:
        lines.append(f"| {row['period']} | {row['candidate']} − {row['baseline']} | {row['risk_scaling']} | "
                     f"{row['mean_daily_net_increment'] * 10000:.3f} | {percent(row['terminal_return_difference'])} | BLOCKED_HURDLE |")
    lines += ["", "Exploratory zero-incremental-cost diagnostics; marginal daily-return intervals, not multiplicity-confirmed. "
              "Block60 is the main diagnostic; block20/120 are sensitivity checks. All are shown even when inconclusive.", "",
              "| Period | Contrast | Scaling | Block | Diagnostic status | Daily CI95 bp | One-sided p |",
              "|---|---|---|---:|---|---|---:|"]
    for row in main:
        for block in row["uncertainty"]["exploratory_zero_hurdle"]["blocks"]:
            ci = block["ci95"]
            interval = "null" if ci is None else f"[{ci[0] * 10000:.3f}, {ci[1] * 10000:.3f}]"
            lines.append(f"| {row['period']} | {row['candidate']} − {row['baseline']} | {row['risk_scaling']} | "
                         f"{block['block_length']} | {block['status']} | {interval} | {number(block['p_net'])} |")
    lines += ["", "All 448 outcomes follow. JSON also contains every annual contribution, rejection reason, exposure/concentration measure, "
              "capital comparison and matched stress direction. Fees and embedded slippage are reported separately; they must not be subtracted twice.", "",
              "| Period | Capital | Variant | Scaling | Path | CAGR | Max DD | Sharpe (zero cash) | Fees CNY | Slippage CNY | Turnover | Mean cash | Mean exposure | Max position | Reject events |",
              "|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["runs"]:
        c, m = row["config"], row["metrics"]
        lines.append(f"| {row['period']} | {c['initial_cash']} | {c['variant']} | {c['risk_scaling']} | {row['path']} | "
            f"{percent(m['cagr'])} | {percent(m['max_drawdown'])} | {number(m['sharpe_zero_cash'])} | {row['fees_cny']:.2f} | "
            f"{row['slippage_cny']:.2f} | {row['one_way_turnover']:.2f} | {percent(row['mean_cash_weight'])} | "
            f"{percent(row['mean_gross_exposure'])} | {percent(row['maximum_single_instrument_weight'])} | {row['rejection_events']} |")
    lines += ["", "Checks establish local artifact consistency and ledger arithmetic. They do not independently establish market prices, "
              "source publication facts, stationarity, realized broker receipts, factor alpha, or future performance.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(args.development, args.validation, args.output)
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.exit(2, "Evaluation refused; no new results published: " + str(error) + "\n")
    print(f"Audited {result['run_count']} runs; formal economic confirmation remains BLOCKED_HURDLE.")


if __name__ == "__main__":
    main()
