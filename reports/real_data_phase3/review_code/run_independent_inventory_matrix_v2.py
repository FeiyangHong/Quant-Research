"""Read-only wrapper for the complete, released 448-run inventory review.

Preparation/selfcheck opens no actual runs or result summaries.  Invoke the real
review only after the parent reviewer releases both complete matrices:

python work/run_independent_inventory_matrix_v2.py --selfcheck
python work/run_independent_inventory_matrix_v2.py \
  --summary reports/real_data_phase3/results_summary.json \
  --output work/independent_inventory_matrix_review.json

The output contains inventory checks and provenance only, never return metrics.
A failure exits nonzero and creates no success report.  Existing reports are
never overwritten.  The frozen independent reviewer remains unmodified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import itertools
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from independent_inventory_review import (
    REVIEW_TABLES, ReviewFailure, audit_run, build_dataset_context,
    digest, read_json, require, sha256,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_REVIEWER = Path(__file__).with_name("independent_inventory_review.py")
FROZEN_REVIEWER_SHA256 = "18f1b3cde4a74ae43ea8ba81c27fb6c69934c5d6311c30fdeca9308172e14242"
PERIODS = {"development": "2016-01-01", "validation": "2022-01-01"}
CAPITALS = (10000, 100000, 500000, 1000000)
VARIANTS = ("E0", "R0", "E1", "R1")
PATHS = ((1, 1, 1, 0), (2, 2, 1, 0), (3, 3, 1, 0),
         (1, 0, 1, 0), (1, 1, 2, 0), (1, 1, 1, 1), (1, 1, 1, 3))
TOTAL_FIELDS = ("sessions_checked", "positions_checked", "fills_checked",
                "source_share_events_checked", "pre_account_metadata_checked",
                "liquidation_right_snapshots_checked", "dividend_entitlements_checked",
                "dividend_cash_events_checked", "dividend_receivables_unpaid_at_end")


def grid_key(config):
    return (config["sample"], config["initial_cash"], config["variant"], config["risk_scaling"],
            config["cost_multiplier"], config["slippage_multiplier"],
            config["execution_delay"], config.get("cash_delay_sessions", 0))


def validate_registration(report, plan):
    """Validate complete registered identities before opening any run artifact."""
    require(report.get("status") == "DESCRIPTIVE_DAILY_SCREEN_ONLY", "Evaluation is not a completed daily screen")
    require(report.get("run_count") == 448 and len(report["runs"]) == 448, "Require all 448 completed rows")
    require(report.get("final_holdout_accessed") is False, "Final holdout is locked")
    require(report.get("economic_confirmation") == "BLOCKED_HURDLE", "Unknown hurdle was relabeled")
    require(report.get("factor_alpha") is None, "Unsupported factor-alpha claim")
    require(set(report["provenance"]["matrix_roots"]) == set(PERIODS), "Both matrix roots are required")
    require(report["provenance"]["source_hash"] == plan["source_hash"], "Summary/preregistration source mismatch")
    require(len(plan["trials"]) == 448, "Incomplete preregistration")
    registered = {}
    for trial in plan["trials"]:
        identity = digest(trial["config"])
        require(identity == trial["config_hash"] and identity not in registered,
                "Duplicate or invalid registered configuration hash")
        registered[identity] = trial["config"]
    expected = {(period, capital, variant, scaling, *path)
                for period, capital, variant, scaling, path in
                itertools.product(PERIODS, CAPITALS, VARIANTS, (False, True), PATHS)}
    seen_hashes, seen_keys, seen_directories = set(), set(), set()
    for row in report["runs"]:
        config, period = row["config"], row["period"]
        require(period in PERIODS and config["sample"] == period, "Row/sample period mismatch")
        require(config.get("live_enabled") is False and config.get("signal_release_delay") == 1,
                "Live mode or signal release differs from frozen protocol")
        require(type(config["risk_scaling"]) is bool, "Risk scaling must be an explicit boolean")
        identity = digest(config)
        require(registered.get(identity) == config and identity not in seen_hashes,
                "Missing, duplicate or unregistered completed configuration")
        require(row["provenance"]["config_hash"] == identity
                and row["provenance"]["source_hash"] == plan["source_hash"],
                "Row provenance differs from registration")
        name = row["directory"]
        require(isinstance(name, str) and name not in ("", ".", "..")
                and Path(name).name == name and "/" not in name and "\\" not in name,
                "Run directory must be a direct child")
        location = (period, name)
        require(location not in seen_directories, "Duplicate run directory")
        seen_directories.add(location)
        seen_hashes.add(identity)
        seen_keys.add(grid_key(config))
    require(seen_hashes == set(registered) and seen_keys == expected,
            "Completed matrix omits registered grid entries")
    return {"registered_configurations": len(registered), "completed_unique_configurations": len(seen_hashes),
            "runs_by_period": dict(Counter(row["period"] for row in report["runs"]))}


def checked_child(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    require(path.parent == root, "Run path escapes matrix root")
    return path


def review_matrix(summary_path, plan_path=None):
    """Call only after explicit release of both completed matrices."""
    summary_path = Path(summary_path).resolve()
    plan_path = Path(plan_path or ROOT / "reports/real_data_phase3/registered_plan.json").resolve()
    require(sha256(FROZEN_REVIEWER) == FROZEN_REVIEWER_SHA256, "Frozen inventory reviewer changed")
    summary_hash, plan_hash, wrapper_hash = sha256(summary_path), sha256(plan_path), sha256(__file__)
    report, plan = read_json(summary_path), read_json(plan_path)
    registration = validate_registration(report, plan)
    roots = {period: Path(value).resolve() for period, value in report["provenance"]["matrix_roots"].items()}
    contexts, datasets = {}, {}
    for period in PERIODS:
        descriptor = plan["samples"][period]
        manifest = (ROOT / descriptor["manifest_path"]).resolve()
        require(sha256(manifest) == descriptor["manifest_sha256"], "Admitted manifest differs from registration")
        contexts[period] = build_dataset_context(manifest.parent)
        datasets[period] = {"directory": str(manifest.parent),
                            "manifest_sha256": contexts[period]["manifest_sha256"],
                            "data_hash": contexts[period]["data_hash"],
                            "input_file_sha256": contexts[period]["input_file_sha256"]}
    checks = []
    for row in report["runs"]:
        period = row["period"]
        directory = checked_child(roots[period], row["directory"])
        try:
            # Bind the check to the already published evaluator artifacts, not
            # merely to whichever self-consistent files happen to be present.
            for name in ("config.json", "provenance.json", "table_hashes.json"):
                require(sha256(directory / name) == row["artifact_hashes"][name],
                        "Artifact differs from completed summary: " + name)
            require(read_json(directory / "config.json") == row["config"], "Run config differs from summary")
            provenance = read_json(directory / "provenance.json")
            require(all(provenance[key] == row["provenance"][key]
                        for key in ("config_hash", "source_hash", "data_hash")),
                    "Run provenance differs from summary")
            result = audit_run(directory, datasets[period]["directory"], PERIODS[period], context=contexts[period])
            require(result["status"] == "PASS", "Inventory review did not pass")
            require(result["checked_table_sha256"] == {name: row["table_hashes"][name] for name in REVIEW_TABLES},
                    "Inventory table hashes differ from completed summary")
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise ReviewFailure("Inventory audit failed for " + period + "/" + directory.name + ": " + str(error)) from error
        result.update(period=period, run_directory=str(directory), initial_cash=row["config"]["initial_cash"],
                      variant=row["config"]["variant"], risk_scaling=row["config"]["risk_scaling"], path=row["path"])
        checks.append(result)
    require(len(checks) == 448 and all(row["status"] == "PASS" for row in checks), "Incomplete successful audit")
    # Recheck immutable inputs after the full pass, before creating a report.
    for period, descriptor in datasets.items():
        directory = Path(descriptor["directory"])
        require(sha256(directory / "manifest.json") == descriptor["manifest_sha256"], "Manifest changed during review")
        for name, expected in descriptor["input_file_sha256"].items():
            require(sha256(directory / name) == expected, "Admitted dataset changed during review: " + name)
    require(sha256(summary_path) == summary_hash and sha256(plan_path) == plan_hash,
            "Summary or registration changed during review")
    require(sha256(FROZEN_REVIEWER) == FROZEN_REVIEWER_SHA256 and sha256(__file__) == wrapper_hash,
            "Review code changed during review")
    totals = {field: sum(row[field] for row in checks) for field in TOTAL_FIELDS}
    totals.update(runs_checked=len(checks), applied_share_events=sum(len(row["applied_share_events"]) for row in checks),
                  runs_by_period=dict(Counter(row["period"] for row in checks)))
    result = {"schema_version": "independent-inventory-matrix-1.0", "status": "ALL_448_PASS",
              "registration": registration, "totals": totals, "dataset_contexts": datasets,
              "summary_path": str(summary_path), "summary_sha256": summary_hash,
              "registered_plan_path": str(plan_path), "registered_plan_sha256": plan_hash,
              "source_hash": plan["source_hash"], "review_wrapper_sha256": wrapper_hash,
              "inventory_reviewer_sha256": FROZEN_REVIEWER_SHA256,
              "matrix_roots": {key: str(value) for key, value in roots.items()},
              "limitations": checks[0]["limitations"],
              "scope_note": "Quantity conservation does not establish fund-history completeness. ETF conversion into another fund type is not automatically a cash liquidation.",
              "runs": checks}
    digest(result)
    return result


def write_report(path, result):
    """Publish only a complete success, without overwriting any prior file."""
    destination = Path(path).resolve()
    require(result["status"] == "ALL_448_PASS", "Cannot publish an incomplete inventory audit")
    for root in result["matrix_roots"].values():
        matrix = Path(root).resolve()
        require(destination != matrix and matrix not in destination.parents, "Output must not alter input matrices")
    require(destination not in (Path(result["summary_path"]), Path(result["registered_plan_path"])),
            "Output must not replace summary or registration")
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def selfcheck():
    """Pure invented 448-identity fixture; no run artifacts are opened."""
    require(sha256(FROZEN_REVIEWER) == FROZEN_REVIEWER_SHA256, "Frozen inventory reviewer changed")
    trials, rows = [], []
    for number, (period, capital, variant, scaling, path) in enumerate(
            itertools.product(PERIODS, CAPITALS, VARIANTS, (False, True), PATHS)):
        config = dict(sample=period, initial_cash=capital, variant=variant, risk_scaling=scaling,
                      cost_multiplier=path[0], slippage_multiplier=path[1], execution_delay=path[2],
                      cash_delay_sessions=path[3], live_enabled=False, signal_release_delay=1)
        config_hash = digest(config)
        trials.append({"config": config, "config_hash": config_hash})
        rows.append({"period": period, "config": config, "directory": "invented_" + str(number),
                     "provenance": {"config_hash": config_hash, "source_hash": "INVENTED"}})
    plan = {"source_hash": "INVENTED", "trials": trials}
    report = {"status": "DESCRIPTIVE_DAILY_SCREEN_ONLY", "run_count": 448, "runs": rows,
              "economic_confirmation": "BLOCKED_HURDLE", "final_holdout_accessed": False, "factor_alpha": None,
              "provenance": {"source_hash": "INVENTED", "matrix_roots": {p: "invented/" + p for p in PERIODS}}}
    validate_registration(report, plan)
    omitted_report, omitted_plan = deepcopy(report), deepcopy(plan)
    for row, trial in zip(omitted_report["runs"], omitted_plan["trials"]):
        if row["config"]["cash_delay_sessions"] == 0:
            row["config"].pop("cash_delay_sessions")
            trial["config"].pop("cash_delay_sessions")
            identity = digest(row["config"])
            row["provenance"]["config_hash"] = identity
            trial["config_hash"] = identity
    validate_registration(omitted_report, omitted_plan)
    rejected = []
    for label in ("missing_run", "duplicate_config", "duplicate_directory", "unregistered_config",
                  "wrong_period", "changed_source", "holdout_access", "path_traversal"):
        bad = deepcopy(report)
        if label == "missing_run": bad["runs"].pop()
        elif label == "duplicate_config": bad["runs"][1] = deepcopy(bad["runs"][0])
        elif label == "duplicate_directory": bad["runs"][1]["directory"] = bad["runs"][0]["directory"]
        elif label == "unregistered_config": bad["runs"][0]["config"]["initial_cash"] = 999
        elif label == "wrong_period": bad["runs"][0]["period"] = "validation"
        elif label == "changed_source": bad["runs"][0]["provenance"]["source_hash"] = "CHANGED"
        elif label == "holdout_access": bad["final_holdout_accessed"] = True
        elif label == "path_traversal": bad["runs"][0]["directory"] = "../elsewhere"
        try:
            validate_registration(bad, plan)
        except ReviewFailure:
            rejected.append(label)
        else:
            raise ReviewFailure("Selfcheck failed to reject " + label)
    compile(Path(__file__).read_text(encoding="utf-8"), str(__file__), "exec")
    return {"status": "PASS", "invented_completed_configurations": 448, "omitted_zero_delay_default_checked": True,
            "invented_mutations_rejected": rejected, "actual_run_results_read": False,
            "frozen_inventory_reviewer_sha256": FROZEN_REVIEWER_SHA256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--registered-plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.selfcheck:
            result = selfcheck()
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if args.summary is None or args.output is None:
                parser.error("--summary and --output are required")
            result = review_matrix(args.summary, args.registered_plan)
            write_report(args.output, result)
            print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                              "output_sha256": sha256(args.output), "totals": result["totals"]},
                             indent=2, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "FAILED_NO_SUCCESS_REPORT", "reason": str(error)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
