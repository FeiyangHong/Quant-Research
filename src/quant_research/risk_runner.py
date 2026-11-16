"""Thin M9 registration wrapper around the unchanged M8 execution engine."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from .data import DataValidationError, audit_dataset, load_dataset
from .evaluation import nav_metrics
from .execution import run_backtest
from .liquid_cohort import LIQUID_SCOPE
from .liquid_runner import _verify_source_files
from .provenance import append_event, digest, source_provenance, write_json
from .risk_budget import (CLAIM_TYPE, RISK_RULE, RISK_SCOPE, generate_risk_targets,
                          initialize_fixed_scale, validate_initializer)
from .runner import _module_fingerprint, dataset_hash

IMPORTED_SOURCE_FINGERPRINT = _module_fingerprint()
CONFIG_FIELDS = ("variant", "initial_cash", "risk_scaling", "signal_release_delay",
                 "execution_delay", "cost_multiplier", "slippage_multiplier",
                 "annual_incremental_cost", "seed")
PATHS = {"base": (1, 1, 1), "cost_2x": (2, 2, 1), "cost_3x": (3, 3, 1),
         "delay_1_session": (1, 1, 2)}


def read_json(path):
    return json.loads(Path(path).read_bytes())


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_for(trial):
    return dict({key: trial[key] for key in CONFIG_FIELDS}, protocol_version="phase2-mvp-0.1",
                live_enabled=False, sample=trial["period"], universe=RISK_SCOPE,
                primary_capital_confirmed=True, claim_type=CLAIM_TYPE)


def validate_risk_config(config):
    expected = set(CONFIG_FIELDS) | {"protocol_version", "live_enabled", "sample", "universe",
                                     "primary_capital_confirmed", "claim_type"}
    if set(config) != expected:
        raise ValueError("M9 exact explicit configuration required")
    fixed = dict(protocol_version="phase2-mvp-0.1", live_enabled=False, universe=RISK_SCOPE,
                 initial_cash=100000, primary_capital_confirmed=True, risk_scaling=True,
                 signal_release_delay=1, seed=20261114, claim_type=CLAIM_TYPE,
                 annual_incremental_cost=None)
    for key, value in fixed.items():
        if type(config[key]) is not type(value) or config[key] != value:
            raise ValueError("Unregistered M9 setting: " + key)
    if config["sample"] not in ("development", "validation") or config["variant"] not in ("VE", "CE", "VR"):
        raise ValueError("Only registered M9 periods and three arms are open")
    if any(type(config[key]) is not int for key in ("cost_multiplier", "slippage_multiplier", "execution_delay")):
        raise ValueError("Explicit integer execution parameters required")
    if tuple(config[key] for key in ("cost_multiplier", "slippage_multiplier", "execution_delay")) not in PATHS.values():
        raise ValueError("Unregistered M9 execution path")


def validate_registry(registry, plan_path):
    if (registry.get("scope") != RISK_SCOPE or registry.get("claim_type") != CLAIM_TYPE
            or registry.get("data_scope") != LIQUID_SCOPE
            or registry.get("plan_sha256") != file_hash(plan_path)):
        raise ValueError("M9 frozen plan/scope mismatch")
    if any(registry.get("risk_estimator", {}).get(key) != RISK_RULE[key]
           for key in ("window", "min_complete", "ddof", "annualization", "vol_target")):
        raise ValueError("M9 registered estimator mismatch")
    if registry.get("primary", {}).get("gamma") != 5:
        raise ValueError("M9 registered utility gamma mismatch")
    trials = registry.get("trials", [])
    expected = {(period, variant, path) for period in ("development", "validation")
                for variant in ("VE", "CE", "VR") for path in PATHS}
    if len(trials) != 24 or {(t["period"], t["variant"], t["path"]) for t in trials} != expected:
        raise ValueError("Exactly the registered24 M9 cells required")
    for trial in trials:
        if (trial["trial_id"] != f'M9_{trial["period"]}_{trial["variant"]}_100000_{trial["path"]}'
                or trial["scope"] != RISK_SCOPE or trial["claim_type"] != CLAIM_TYPE
                or tuple(trial[k] for k in ("cost_multiplier", "slippage_multiplier", "execution_delay")) != PATHS[trial["path"]]):
            raise ValueError("M9 cell identity differs from registered matrix")
        validate_risk_config(config_for(trial))


def verify_data_binding(dataset, binding, sample, evidence_root):
    if (binding.get("experiment_id") != RISK_SCOPE or binding.get("data_scope") != LIQUID_SCOPE
            or dataset.manifest.get("research_scope") != LIQUID_SCOPE
            or dataset.manifest.get("sample") != sample or dataset.manifest.get("synthetic") is not False):
        raise DataValidationError("M9 must bind original real M8 scope and sample without relabelling")
    expected = binding.get("datasets", {}).get(sample, {})
    if expected.get("dataset_hash") != dataset_hash(dataset):
        raise DataValidationError("M9 bound M8 dataset identity mismatch")
    _verify_source_files(dataset, evidence_root)
    end = "2021-12-31" if sample == "development" else "2024-12-31"
    if (any(day > end for day in dataset.calendar) or any(dataset.bars.date.gt(end))
            or any(dataset.benchmark.date.gt(end)) or dataset.manifest.get("signal_release_delay") != 1):
        raise DataValidationError("M9 sample boundary/release clock mismatch")


def verify_fixed_initializer(initializer, development, binding):
    validate_initializer(initializer)
    expected = initialize_fixed_scale(development)
    if initializer != expected:
        raise DataValidationError("Fixed c differs from independently recomputed legal development initializer")
    if initializer["development_data_hash"] != binding["datasets"]["development"]["dataset_hash"]:
        raise DataValidationError("Fixed c is not bound to the frozen development dataset")


def verify_base_receipt(receipt_path, records, output_root, public_root=None):
    bases = [row for row in records if row["path"] == "base" and row["status"] == "COMPLETED"]
    expected_ids = {f"M9_{period}_{variant}_100000_base" for period in ("development", "validation")
                    for variant in ("VE", "CE", "VR")}
    if len(bases) != 6 or {row["trial_id"] for row in bases} != expected_ids:
        raise ValueError("Exactly six completed base accounts required before stresses")
    receipt = read_json(receipt_path)
    expected_public = {row["trial_id"]: row["exported_tables"] for row in bases}
    expected_private = {row["trial_id"]: row["private_table_hashes"] for row in bases}
    if (receipt.get("decision") != "PASS_DATA_AND_ACCOUNTING"
            or receipt.get("author_role") != "INDEPENDENT_REVIEWER"
            or receipt.get("base_account_hashes") != expected_public
            or receipt.get("private_table_hashes") != expected_private):
        raise ValueError("Independent hash-bound six-base accounting receipt required")
    for row in bases:
        for name, expected in row["private_table_hashes"].items():
            if file_hash(Path(output_root) / row["run_id"] / name) != expected:
                raise ValueError("Base private account bytes changed after independent review")
        if public_root is not None:
            for name, expected in row["exported_tables"].items():
                if file_hash(Path(public_root) / "accounts" / row["trial_id"] / name) != expected:
                    raise ValueError("Base public account bytes changed after independent review")
    return file_hash(receipt_path)


def run_risk_experiment(dataset, config, output_root, repo_root, evidence_root, trial,
                        registration_paths, initializer, binding, base_receipt_hash=None,
                        development=None, base_receipt_path=None, public_root=None):
    """Save one immutable real M9 account, including failures and full local books.

    The orchestration entry verifies the initializer against development and the
    independent base receipt. All four paths use this exact same engine.
    """
    output_root, repo_root = Path(output_root), Path(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / trial["trial_id"]
    destination.mkdir(exist_ok=False)  # Failed paths are also immutable; no silent replay.
    run_id = destination.name
    events = output_root / "trial_registry.jsonl"
    try:
        if _module_fingerprint() != IMPORTED_SOURCE_FINGERPRINT:
            raise RuntimeError("Source changed after import; restart before any account")
        validate_risk_config(config)
        if config != config_for(trial):
            raise ValueError("M9 config differs from registered cell")
        frozen_registry = read_json(repo_root / "reports/m9_risk/EXPERIMENT_REGISTRY.json")
        validate_registry(frozen_registry, repo_root / "docs/M9_PLAN.md")
        if [row for row in frozen_registry["trials"] if row["trial_id"] == trial["trial_id"]] != [trial]:
            raise ValueError("M9 account trial differs from frozen registration")
        if trial["path"] != "base":
            if base_receipt_path is None:
                raise ValueError("M9 stresses require independent six-base receipt")
            public_root = Path(public_root) if public_root else repo_root / "reports/m9_risk"
            actual_receipt = verify_base_receipt(base_receipt_path,
                read_json(public_root / "ACCOUNT_PATHS.json"), output_root, public_root)
            if base_receipt_hash != actual_receipt:
                raise ValueError("M9 independent receipt identity mismatch")
        provenance = source_provenance(repo_root)
        registered = {str(Path(path).resolve().relative_to(repo_root.resolve()).as_posix()): file_hash(path)
                      for path in registration_paths}
        identity = dict(config_hash=digest(config), data_hash=dataset_hash(dataset),
                        source_hash=provenance["source_hash"], registration_hash=digest(registered),
                        rule_hash=digest(RISK_RULE), initializer_hash=initializer["initializer_hash"],
                        binding_hash=digest(binding), base_receipt_hash=base_receipt_hash)
        write_json(destination / "config.json", config)
        write_json(destination / "provenance.json", dict(provenance, **identity, run_id=run_id,
                   registration_hashes=registered, evidence_root_mode="EXTERNAL_READ_ONLY",
                   started_at=datetime.now(timezone.utc).isoformat()))
        append_event(events, dict(event="REGISTERED", run_id=run_id, config=config, **identity))
        for relative, expected in {**provenance["source_files"], **registered}.items():
            content = (repo_root / relative).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError("Source or registration changed during snapshot")
            target = destination / "source_snapshot" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        verify_data_binding(dataset, binding, config["sample"], evidence_root)
        if development is None:
            development = (dataset if config["sample"] == "development" else
                load_dataset(Path(evidence_root) / binding["datasets"]["development"]["relative_path"]))
        verify_fixed_initializer(initializer, development, binding)
        audit = audit_dataset(dataset)
        write_json(destination / "data_audit.json", audit)
        if audit["status"] != "PASSED" or audit["errors"] or audit["blockers"]:
            raise DataValidationError("M9 necessary source audit blocked")
        decisions = generate_risk_targets(dataset, config["variant"], initializer, config["execution_delay"])
        write_json(destination / "decisions.json", [dict(asdict(d), decision_at=d.decision_at.isoformat()) for d in decisions])
        write_json(destination / "risk_signals.json", [dict(d.diagnostics, execution_date=d.execution_date,
                                                           decision_at=d.decision_at.isoformat()) for d in decisions])
        start = "2020-01-01" if config["sample"] == "development" else "2022-01-01"
        result = run_backtest(dataset, decisions, 100000, cost_multiplier=config["cost_multiplier"],
                              slippage_multiplier=config["slippage_multiplier"], start_date=start)
        write_json(destination / "execution_assumptions.json", {k: v for k, v in result.items() if not isinstance(v, pd.DataFrame)})
        hashes = {}
        for name, table in result.items():
            if isinstance(table, pd.DataFrame):
                payload = table.to_json(orient="records", date_format="iso", double_precision=15).encode("utf-8")
                (destination / (name + ".json")).write_bytes(payload)
                hashes[name] = hashlib.sha256(payload).hexdigest()
        metrics = nav_metrics(result["nav"], 100000)
        metrics.update(status="DAILY_SCREEN_ONLY", run_id=run_id, research_scope=RISK_SCOPE,
                       claim_type=CLAIM_TYPE, economic_confirmation="BLOCKED_HURDLE")
        write_json(destination / "metrics.json", metrics)
        write_json(destination / "table_hashes.json", hashes)
        if source_provenance(repo_root)["source_hash"] != identity["source_hash"]:
            raise RuntimeError("Source changed during account execution; retain failed evidence")
        if any(file_hash(repo_root / path) != expected for path, expected in registered.items()):
            raise RuntimeError("Registration changed during account execution; retain failed evidence")
        append_event(events, dict(event="COMPLETED", run_id=run_id, table_hashes=hashes))
        return destination, metrics
    except BaseException as error:
        failure = dict(event="FAILED", run_id=run_id, error=type(error).__name__, reason=str(error))
        if hasattr(error, "diagnostics"):
            failure["risk_diagnostics"] = error.diagnostics
        write_json(destination / "failure.json", failure)
        append_event(events, failure)
        raise
