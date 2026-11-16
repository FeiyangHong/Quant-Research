"""Explicit M8 admission and real account entry; ordinary R1I stays closed."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from .admission import verify_attestation
from .liquid_cohort import LIQUID_SCOPE, liquid_dependencies, generate_liquid_targets
from .data import TABLES, DataValidationError, audit_dataset, load_dataset, save_dataset
from .evaluation import nav_metrics
from .execution import run_backtest
from .provenance import append_event, digest, source_provenance, write_json
from .runner import dataset_hash, _module_fingerprint


IMPORTED_SOURCE_FINGERPRINT = _module_fingerprint()
REGISTRATION_FILES = ("docs/M8_PLAN.md", "reports/m8_rotation/SOURCE_POLICY_ADDENDUM.md",
                      "reports/m8_rotation/COHORT_SELECTION.json", "reports/m8_rotation/EXPERIMENT_REGISTRY.json")



def validate_liquid_config(config):
    allowed = {"protocol_version", "live_enabled", "sample", "universe", "variant", "initial_cash",
               "primary_capital_confirmed", "annual_incremental_cost", "risk_scaling", "execution_delay",
               "cost_multiplier", "slippage_multiplier", "seed", "claim_type", "signal_release_delay"}
    if set(config) - allowed:
        raise ValueError("Unknown cohort configuration keys: " + str(sorted(set(config) - allowed)))
    required = dict(protocol_version="phase2-mvp-0.1", live_enabled=False, universe=LIQUID_SCOPE,
                    initial_cash=100000, primary_capital_confirmed=True, risk_scaling=False,
                    signal_release_delay=1, seed=20261114, claim_type="economic_increment")
    for key, value in required.items():
        if type(config.get(key)) is not type(value) or config[key] != value:
            raise ValueError("Unregistered cohort setting: " + key)
    if config.get("sample") not in ("development", "validation", "synthetic"):
        raise ValueError("Final holdout is locked")
    if config.get("variant") not in ("E0", "R0", "E1", "R1"):
        raise ValueError("Unregistered cohort variant")
    for key in ("cost_multiplier", "slippage_multiplier", "execution_delay"):
        if type(config.get(key)) is not int:
            raise ValueError("Explicit integer cohort execution configuration required")
    path = tuple(config[k] for k in ("cost_multiplier", "slippage_multiplier", "execution_delay"))
    if path not in ((1, 1, 1), (2, 2, 1), (3, 3, 1), (1, 1, 2)):
        raise ValueError("Unregistered cohort pressure path")
    if "annual_incremental_cost" not in config or config["annual_incremental_cost"] is not None:
        raise ValueError("The registered32 cohort paths require explicit unknown fixed cost, null")


def split_liquid_sample(dataset, sample):
    """Physically separate market tables; each account starts with fresh cash."""
    if sample not in ("development", "validation"):
        raise DataValidationError("Final holdout is locked")
    if any(day >= "2025-01-01" for day in dataset.calendar):
        raise DataValidationError("Do not load final-holdout market data into the cohort adapter")
    result = deepcopy(dataset)
    end = "2021-12-31" if sample == "development" else "2024-12-31"
    result.calendar = [day for day in result.calendar if day <= end]
    result.instruments = result.instruments.loc[result.instruments.available_at.str[:10].le(end)].copy()
    result.bars = result.bars.loc[result.bars.date.le(end)].copy()
    result.benchmark = result.benchmark.loc[result.benchmark.date.le(end)].copy()
    result.actions = result.actions.loc[result.actions.ex_date.le(end)].copy()
    result.manifest.update(dataset_id="real-m8-historical-liquid-" + sample, dataset_version="admitted-v1",
                           sample=sample, coverage_start=result.calendar[0], coverage_end=result.calendar[-1],
                           funded_account_start="2020-01-01" if sample == "development" else "2022-01-01",
                           warmup_is_not_account_return=True)
    result.manifest["liquid_dependencies"] = liquid_dependencies(result)
    result.manifest["required_full_history_instruments"] = result.manifest["liquid_dependencies"]["required_full_history_instruments"]
    result.manifest.pop("file_sha256", None)
    return result


def admit_liquid_samples(stage, attestation, output, repo):
    """Reuse the hash-bound independent evidence admission, with new scope."""
    review = verify_attestation(stage, attestation, repo)
    if review.get("research_scope") != LIQUID_SCOPE:
        raise DataValidationError("Independent review must explicitly admit the fixed cohort")
    dataset = load_dataset(stage, allow_unverified=True)
    if dataset.manifest.get("synthetic") is not False or dataset.manifest.get("build_blockers"):
        raise DataValidationError("Only real data with resolved necessary dependencies can be admitted")
    if review.get("admission_scope") != "FULL_HOLDING_DEPENDENCIES":
        raise DataValidationError("Independent full holding-source admission required")
    dataset.manifest.update(status="ADMITTED_DAILY_SCREEN", strategy_runs_permitted=True,
                            admission_scope="FULL_HOLDING_DEPENDENCIES",
                            calendar_kind="VERIFIED_EXCHANGE_CALENDAR", evidence_gates=review["evidence_gates"],
                            admission_attestation=review,
                            admission_attestation_sha256=hashlib.sha256(Path(attestation).read_bytes()).hexdigest(),
                            admitted_stage_manifest_sha256=hashlib.sha256((Path(stage) / "manifest.json").read_bytes()).hexdigest(),
                            performance_evidence_scope="CONDITIONAL_DAILY_SIMULATION_ONLY")
    for name in TABLES:
        table = getattr(dataset, name)
        if not table.quality_status.isin(["provisional", "accepted"]).all():
            raise DataValidationError("Quarantined records cannot be promoted: " + name)
        table.loc[:, "quality_status"] = "accepted"
    summaries = {}
    for sample in ("development", "validation"):
        split = split_liquid_sample(dataset, sample)
        audit = audit_dataset(split)
        if audit["status"] != "PASSED":
            raise DataValidationError("Cohort admission audit failed: " + json.dumps(audit))
        destination = Path(output) / sample
        save_dataset(split, destination)
        write_json(destination / "admission_audit.json", audit)
        summaries[sample] = dict(path=str(destination), sessions=len(split.calendar), bars=len(split.bars),
                                 first_session=split.calendar[0], last_session=split.calendar[-1], status="PASSED")
    write_json(Path(output) / "sample_manifest.json", summaries)
    return summaries


def _verify_source_files(dataset, repo):
    if dataset.manifest.get("synthetic") is True:
        return
    selection_path = Path(repo) / "reports/m8_rotation/COHORT_SELECTION.json"
    if (not selection_path.is_file()
            or hashlib.sha256(selection_path.read_bytes()).hexdigest() != dataset.manifest.get("cohort_selection_sha256")
            or json.loads(selection_path.read_bytes()) != dataset.manifest.get("cohort_selection")):
        raise DataValidationError("Frozen formation selection differs from admitted snapshot")
    if dataset.manifest.get("admission_scope") != "FULL_HOLDING_DEPENDENCIES":
        raise DataValidationError("M7 all-cash admission cannot authorize M8 holdings")
    review = dataset.manifest.get("admission_attestation", {})
    if review.get("decision") != "ADMIT_DAILY_SCREEN" or review.get("research_scope") != LIQUID_SCOPE:
        raise DataValidationError("Independent fixed-cohort admission required")
    bound = dict(dataset.manifest.get("source_snapshot_hashes", {}))
    bound.update(review.get("evidence_files", {}))
    if not bound or not review.get("evidence_files"):
        raise DataValidationError("Missing bound source/admission evidence")
    root = Path(repo).resolve()
    for relative, expected in bound.items():
        path = (root / relative).resolve()
        path.relative_to(root)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise DataValidationError("Cohort original/evidence unavailable or changed: " + relative)


def run_liquid_experiment(dataset, config, output_root, repo_root):
    """Run and save one registered path through the corrected main engine.

    The caller runs eight base paths before the other twenty-four. This entry
    never conditions admission of a pressure path on the profitability of base.
    """
    output_root, repo_root = Path(output_root), Path(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    lock = output_root / ".liquid_runner.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("One cohort writer; retain until runner exits.\n")
    try:
        if _module_fingerprint() != IMPORTED_SOURCE_FINGERPRINT:
            raise RuntimeError("Source changed after import; restart to bind executing cohort code")
        provenance = source_provenance(repo_root)
        registered = {name: hashlib.sha256((repo_root / name).read_bytes()).hexdigest() for name in REGISTRATION_FILES}
        provenance["registration_hashes"] = registered
        identity = dict(config_hash=digest(config), data_hash=dataset_hash(dataset),
                        source_hash=provenance["source_hash"], registration_hash=digest(registered))
        run_id = digest(identity)[:16] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = output_root / run_id
        destination.mkdir()
        registry = output_root / "trial_registry.jsonl"
        write_json(destination / "config.json", config)
        write_json(destination / "provenance.json", dict(provenance, **identity, run_id=run_id))
        append_event(registry, dict(run_id=run_id, event="REGISTERED", config=config, **identity))
        try:
            validate_liquid_config(config)
            frozen_registry = json.loads((repo_root / REGISTRATION_FILES[-1]).read_bytes())
            if frozen_registry.get("plan_sha256") != registered[REGISTRATION_FILES[0]]:
                raise ValueError("M8 plan differs from frozen preregistration")
            synthetic = dataset.manifest.get("synthetic") is True
            if synthetic != (config["sample"] == "synthetic"):
                raise ValueError("Real and synthetic data must retain their actual labels")
            if not synthetic:
                matches = [trial for trial in frozen_registry["trials"] if trial["period"] == config["sample"]
                           and trial["variant"] == config["variant"]
                           and all(trial[key] == config[key] for key in
                                   ("initial_cash", "risk_scaling", "signal_release_delay", "execution_delay",
                                    "cost_multiplier", "slippage_multiplier", "seed", "annual_incremental_cost"))]
                if len(matches) != 1:
                    raise ValueError("Path is absent or ambiguous in frozen32 registry")
            for relative, expected in {**provenance["source_files"], **registered}.items():
                content = (repo_root / relative).read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise RuntimeError("Source changed during immutable run snapshot")
                target = destination / "source_snapshot" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            _verify_source_files(dataset, repo_root)
            audit = audit_dataset(dataset)
            write_json(destination / "data_audit.json", audit)
            if audit["errors"] or audit["blockers"] or (not synthetic and audit["status"] != "PASSED"):
                raise DataValidationError("DATA_BLOCKED_LIQUID_COHORT: necessary input audit failed")
            end = "2021-12-31" if config["sample"] == "development" else "2024-12-31"
            if (any(day > end for day in dataset.calendar)
                    or any(dataset.bars.date.gt(end)) or any(dataset.benchmark.date.gt(end))):
                raise DataValidationError("Supply physically separate pre-boundary market tables")
            if dataset.manifest.get("signal_release_delay") != 1:
                raise DataValidationError("Cohort release clock must match audited data")
            decisions = generate_liquid_targets(dataset, config["variant"], config["execution_delay"])
            start = "2022-01-01" if config["sample"] == "validation" else "2020-01-01"
            decisions = [decision for decision in decisions if decision.execution_date >= start]
            write_json(destination / "decisions.json", [dict(asdict(d), decision_at=d.decision_at.isoformat()) for d in decisions])
            result = run_backtest(dataset, decisions, config["initial_cash"],
                                  cost_multiplier=config["cost_multiplier"],
                                  slippage_multiplier=config["slippage_multiplier"], start_date=start)
            write_json(destination / "execution_assumptions.json", {key: value for key, value in result.items()
                                                                    if not isinstance(value, pd.DataFrame)})
            hashes = {}
            for name, table in result.items():
                if isinstance(table, pd.DataFrame):
                    payload = table.to_json(orient="records", date_format="iso", double_precision=15).encode("utf-8")
                    (destination / (name + ".json")).write_bytes(payload)
                    hashes[name] = hashlib.sha256(payload).hexdigest()
            metrics = nav_metrics(result["nav"], config["initial_cash"])
            metrics.update(status="SYNTHETIC_ENGINEERING_ONLY" if synthetic else "DAILY_SCREEN_ONLY", run_id=run_id,
                           research_scope=LIQUID_SCOPE,
                           economic_confirmation="BLOCKED_HURDLE" if config.get("annual_incremental_cost") is None else "NOT_PERFORMED")
            write_json(destination / "metrics.json", metrics)
            write_json(destination / "table_hashes.json", hashes)
            write_json(destination / "uncertainty.json", dict(status="NOT_A_CONFIRMATORY_TEST", reason="Paired registered evaluation required"))
            append_event(registry, dict(run_id=run_id, event="COMPLETED", status=metrics["status"], table_hashes=hashes))
            return destination, metrics
        except BaseException as error:
            failure = dict(run_id=run_id, event="FAILED", error=type(error).__name__, reason=str(error))
            write_json(destination / "failure.json", failure)
            append_event(registry, failure)
            raise
    finally:
        lock.unlink()
