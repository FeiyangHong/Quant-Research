"""Audit only the parent-released development matrix, without return metrics.

Reads the completed matrix summary only for its configs/directory identities;
does not inspect its metric values or open metrics.json.  Validation is neither
opened nor audited.  No frozen file is modified.  Preparation runs only
--selfcheck; the replacement development v2 matrix requires a separate release.
The prior v1 inventory PASS did not audit trade-notional or fee money boundaries.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import itertools
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from independent_inventory_review import (
    REVIEW_TABLES, audit_run, build_dataset_context, digest, read_json, require, sha256,
)
from run_independent_inventory_matrix_v3 import (
    ROOT, DEFAULT_PLAN_PATH, CAPITALS, VARIANTS, PATHS, TOTAL_FIELDS,
    selfcheck as matrix_selfcheck,
    FROZEN_REVIEWER, FROZEN_REVIEWER_SHA256, checked_child, grid_key,
)


def verify_registry(root, entries):
    require(not (root / ".runner.lock").exists(), "Development matrix writer still active")
    path = root / "trial_registry.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    registrations, terminals = {}, {}
    for row in records:
        identity = row["run_id"]
        if row["event"] == "REGISTERED":
            require(identity not in registrations, "Duplicate development registry identity")
            registrations[identity] = row
        elif row["event"] == "COMPLETED":
            require(identity in registrations and identity not in terminals, "Terminal without unique prior registration")
            require(row["status"] == "DAILY_SCREEN_ONLY", "Unsupported terminal status")
            terminals[identity] = row
        else:
            raise ValueError("Development registry is not the released 224-completed/zero-failed matrix: " + row["event"])
    expected = {row["directory"] for row in entries}
    require(len(expected) == 224 and set(registrations) == expected == set(terminals), "Development registry/summary mismatch")
    observed = {p.name for p in root.iterdir() if p.is_dir() and
                any((p / name).exists() for name in ("config.json", "failure.json", "nav.json"))}
    require(observed == expected, "Unexpected or missing development run directory")
    return registrations, terminals, {"registry_sha256": sha256(path), "registered": 224, "completed": 224, "failed": 0}


def resolve_review_paths(root=None, plan_path=None):
    root = Path(root or ROOT / "runs/real_r1_development_v2").resolve()
    require(root.name.endswith("development_v2"), "Only the replacement development v2 root is permitted")
    plan_path = Path(plan_path or DEFAULT_PLAN_PATH).resolve()
    return root, plan_path


def review_development(root=None, plan_path=None):
    root, plan_path = resolve_review_paths(root, plan_path)
    summary_path = root / "matrix_summary.json"
    require(sha256(FROZEN_REVIEWER) == FROZEN_REVIEWER_SHA256, "Frozen inventory reviewer changed")
    plan_hash, summary_hash, wrapper_hash = sha256(plan_path), sha256(summary_path), sha256(__file__)
    helper_path = Path(__file__).with_name("run_independent_inventory_matrix_v3.py")
    helper_hash = sha256(helper_path)
    plan = read_json(plan_path)
    # Deliberately discard metric values without selecting or displaying them.
    entries = [{"config": row["config"], "directory": row["directory"]}
               for row in read_json(summary_path)]
    require(len(entries) == 224, "Require exactly 224 completed development configurations")
    registered = {}
    for trial in plan["trials"]:
        if trial["config"]["sample"] != "development":
            continue
        identity = digest(trial["config"])
        require(identity == trial["config_hash"] and identity not in registered, "Invalid development preregistration")
        registered[identity] = trial["config"]
    require(len(registered) == 224, "Incomplete development preregistration")
    expected_keys = {("development", capital, variant, scaling, *path)
                     for capital, variant, scaling, path in itertools.product(CAPITALS, VARIANTS, (False, True), PATHS)}
    seen, keys = set(), set()
    for entry in entries:
        config = entry["config"]
        identity = digest(config)
        require(config["sample"] == "development" and config.get("live_enabled") is False
                and config.get("signal_release_delay") == 1, "Only released development configs are allowed")
        require(registered.get(identity) == config and identity not in seen, "Duplicate or unregistered development config")
        require(type(config["risk_scaling"]) is bool, "Risk scaling must be explicit boolean")
        checked_child(root, entry["directory"])
        seen.add(identity)
        keys.add(grid_key(config))
    require(seen == set(registered) and keys == expected_keys, "Development grid is incomplete")
    registrations, terminals, registry = verify_registry(root, entries)
    descriptor = plan["samples"]["development"]
    manifest = (ROOT / descriptor["manifest_path"]).resolve()
    require(sha256(manifest) == descriptor["manifest_sha256"], "Development admitted manifest changed")
    context = build_dataset_context(manifest.parent)
    require(context["calendar"][-1] <= "2021-12-31", "Development input includes validation dates")
    checks = []
    for entry in entries:
        directory = checked_child(root, entry["directory"])
        try:
            registration, terminal = registrations[directory.name], terminals[directory.name]
            provenance = read_json(directory / "provenance.json")
            config = entry["config"]
            require(read_json(directory / "config.json") == config == registration["config"], "Development config identity mismatch")
            require(provenance["run_id"] == directory.name == registration["run_id"], "Development run identity mismatch")
            identity = {field: provenance[field] for field in ("config_hash", "data_hash", "source_hash")}
            require(identity["config_hash"] == digest(config) and identity["data_hash"] == context["data_hash"]
                    and identity["source_hash"] == plan["source_hash"], "Run identity differs from registered source/data/config")
            require(all(registration[field] == value for field, value in identity.items()), "Registry provenance differs from run")
            require(directory.name.startswith(digest(identity)[:16] + "-"), "Run name does not bind identity")
            table_hashes = read_json(directory / "table_hashes.json")
            require(table_hashes == terminal["table_hashes"], "Terminal table hashes differ from run artifact")
            for name, expected in table_hashes.items():
                require(isinstance(name, str) and name.replace("_", "").isalpha(), "Invalid ledger table name")
                require(sha256(directory / (name + ".json")) == expected, "Terminal table hash mismatch: " + name)
            result = audit_run(directory, manifest.parent, "2016-01-01", context=context)
            require(result["status"] == "PASS" and result["checked_table_sha256"]
                    == {name: terminal["table_hashes"][name] for name in REVIEW_TABLES}, "Inventory/terminal identity mismatch")
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise ValueError("Development inventory failure " + directory.name + ": " + str(error)) from error
        result.update(period="development", initial_cash=config["initial_cash"], variant=config["variant"],
                      risk_scaling=config["risk_scaling"], cost_multiplier=config["cost_multiplier"],
                      slippage_multiplier=config["slippage_multiplier"], execution_delay=config["execution_delay"],
                      cash_delay_sessions=config.get("cash_delay_sessions", 0),
                      registry_terminal_table_hashes=terminal["table_hashes"])
        checks.append(result)
        if len(checks) % 32 == 0:
            print("Development inventory audit passed " + str(len(checks)) + "/224", file=sys.stderr, flush=True)
    require(len(checks) == 224, "Partial development inventory review")
    require(sha256(manifest) == context["manifest_sha256"], "Admitted manifest changed during review")
    for name, expected in context["input_file_sha256"].items():
        require(sha256(manifest.parent / name) == expected, "Admitted input changed during review")
    require(sha256(plan_path) == plan_hash and sha256(summary_path) == summary_hash
            and sha256(root / "trial_registry.jsonl") == registry["registry_sha256"], "Registration/matrix changed during review")
    require(sha256(FROZEN_REVIEWER) == FROZEN_REVIEWER_SHA256 and sha256(__file__) == wrapper_hash
            and sha256(helper_path) == helper_hash, "Review code changed during audit")
    totals = {field: sum(row[field] for row in checks) for field in TOTAL_FIELDS}
    totals.update(runs_checked=224, applied_share_events=sum(len(row["applied_share_events"]) for row in checks))
    return {"schema_version": "independent-development-inventory-1.0", "status": "ALL_224_DEVELOPMENT_PASS",
            "validation_results_accessed": False, "return_metrics_inspected": False,
            "matrix_summary_scope": "Only config and directory identities extracted; metric fields discarded.",
            "matrix_root": str(root), "matrix_summary_sha256": summary_hash,
            "registered_plan_sha256": plan_hash, "registry": registry, "source_hash": plan["source_hash"],
            "dataset_directory": context["directory"], "dataset_manifest_sha256": context["manifest_sha256"],
            "data_hash": context["data_hash"], "dataset_file_sha256": context["input_file_sha256"],
            "review_script_sha256": wrapper_hash, "matrix_helper_sha256": helper_hash,
            "frozen_inventory_reviewer_sha256": FROZEN_REVIEWER_SHA256,
            "totals": totals, "limitations": checks[0]["limitations"], "runs": checks}


def selfcheck():
    """Invented checks only; neither registration nor result files are opened."""
    root, plan = resolve_review_paths()
    require(root == (ROOT / "runs/real_r1_development_v2").resolve(), "Development v2 default regressed")
    require(plan == (ROOT / "reports/real_data_phase3/registered_plan_v2.json").resolve(),
            "Registration v2 default regressed")
    try:
        resolve_review_paths(ROOT / "runs/real_r1_development_v1")
    except ValueError:
        pass
    else:
        raise ValueError("Invalidated development v1 root was accepted")
    checks = matrix_selfcheck()
    require(checks["replacement_source_hash_accepted"], "Replacement source was not accepted")
    compile(Path(__file__).read_text(encoding="utf-8"), str(__file__), "exec")
    return {"status": "PASS", "development_v2_default_checked": True,
            "registered_plan_v2_default_checked": True, "v1_root_rejected": True,
            "replacement_source_hash_accepted": True, "actual_run_results_read": False,
            "matrix_invented_selfcheck": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "work/independent_inventory_development_review_v2.json")
    args = parser.parse_args()
    try:
        if args.selfcheck:
            print(json.dumps(selfcheck(), indent=2, sort_keys=True))
            return
        require(not args.output.exists(), "Refusing to overwrite existing development review")
        result = review_development()
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        print(json.dumps({"status": result["status"], "totals": result["totals"],
                          "output": str(args.output.resolve()), "output_sha256": sha256(args.output)}, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "FAILED_NO_SUCCESS_REPORT", "reason": str(error)}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
