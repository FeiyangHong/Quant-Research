"""Orchestrate registered runs, preserving failures and immutable result directories."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pandas as pd

from .data import audit_dataset
from .evaluation import nav_metrics
from .execution import run_backtest
from .provenance import append_event, digest, source_provenance, validate_run_config, write_json
from .strategy import generate_targets


def _module_fingerprint():
    root = Path(__file__).parent
    return digest({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts})


IMPORTED_SOURCE_FINGERPRINT = _module_fingerprint()


def dataset_hash(dataset):
    content = {"calendar": dataset.calendar, "manifest": dataset.manifest}
    for name in ("instruments", "bars", "actions", "benchmark"):
        content[name] = json.loads(getattr(dataset, name).to_json(orient="records", date_format="iso", double_precision=15))
    return digest(content)


def _is_synthetic(dataset):
    return dataset.manifest.get("synthetic") is True


def run_experiment(dataset, config, output_root, repo_root):
    return _run_experiment(dataset, config, output_root, repo_root)


def _run_experiment(dataset, config, output_root, repo_root, context=None):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    lock = output_root / ".runner.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("One writer; remove only after verifying no runner remains.\n")
    try:
        if _module_fingerprint() != IMPORTED_SOURCE_FINGERPRINT:
            raise RuntimeError("Source changed after import; restart the runner to bind the actual executing code")
        provenance = source_provenance(repo_root)
        if context is not None and provenance["source_hash"] != context["source_hash"]:
            raise RuntimeError("Source changed within the registered matrix")
        identity = {"config_hash": digest(config), "data_hash": dataset_hash(dataset) if context is None else context["data_hash"], "source_hash": provenance["source_hash"]}
        attempt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = digest(identity)[:16] + "-" + attempt
        destination = output_root / run_id
        destination.mkdir()
        registry = output_root / "trial_registry.jsonl"
        write_json(destination / "config.json", config)
        write_json(destination / "provenance.json", dict(provenance, **identity, run_id=run_id))
        # Hashes alone cannot reproduce dirty/untracked sources after a later edit.
        for relative, expected in provenance["source_files"].items():
            content = (Path(repo_root) / relative).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError("Source changed while taking immutable run snapshot")
            target = destination / "source_snapshot" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        append_event(registry, dict(run_id=run_id, event="REGISTERED", config=config, **identity))
        try:
            validate_run_config(config)
            report = audit_dataset(dataset) if context is None else context["audit"]
            write_json(destination / "data_audit.json", report)
            synthetic = _is_synthetic(dataset)
            if config["sample"] == "synthetic" and not synthetic:
                raise ValueError("Real data cannot be relabelled synthetic")
            if config["sample"] != "synthetic" and synthetic:
                raise ValueError("Synthetic data cannot produce historical research results")
            if report.get("errors") or report.get("blockers"):
                raise ValueError("FAILED_DATA: input audit errors")
            if not synthetic and report.get("status") != "PASSED":
                raise ValueError("BLOCKED_DATA: complete real-data audit required")
            if any(d >= "2025-01-01" for d in dataset.calendar):
                raise ValueError("Final holdout is locked; supply a physically separate pre-2025 dataset")
            if not synthetic and config["sample"] == "development" and any(d > "2021-12-31" for d in dataset.calendar):
                raise ValueError("Development input contains validation dates")
            if config.get("signal_release_delay", 0) != dataset.manifest.get("signal_release_delay", 0):
                raise ValueError("Signal release delay must match the audited data availability policy")
            target_key = (config["variant"], config.get("risk_scaling", False), config.get("execution_delay", 1),
                          config["universe"], config.get("signal_release_delay", 0))
            cached = context["targets"].get(target_key) if context is not None else None
            if cached is None:
                decisions = generate_targets(dataset, variant=config["variant"], risk_scaling=config.get("risk_scaling", False),
                                             execution_delay=config.get("execution_delay", 1), universe=config["universe"],
                                             signal_release_delay=config.get("signal_release_delay", 0))
                if context is not None:
                    context["targets"][target_key] = decisions
            else:
                decisions = cached
            account_start = ("2022-01-01" if config["sample"] == "validation" else
                             "2016-01-01" if not synthetic else None)
            if account_start is not None:
                # Historical rows are permitted for feature warmup, but account starts fresh.
                decisions = [d for d in decisions if d.execution_date >= account_start]
            result = run_backtest(dataset, decisions, config["initial_cash"],
                                  cost_multiplier=config.get("cost_multiplier", 1),
                                  slippage_multiplier=config.get("slippage_multiplier", 1),
                                  cash_delay_sessions=config.get("cash_delay_sessions", 0),
                                  start_date=account_start)
            write_json(destination / "execution_assumptions.json", {
                name: value for name, value in result.items() if not isinstance(value, pd.DataFrame)})
            table_hashes = {}
            for name, table in result.items():
                if not isinstance(table, pd.DataFrame):
                    continue
                data = table.to_json(orient="records", date_format="iso", double_precision=15).encode("utf-8")
                (destination / (name + ".json")).write_bytes(data)
                table_hashes[name] = hashlib.sha256(data).hexdigest()
            metrics = nav_metrics(result["nav"], config["initial_cash"])
            metrics.update(status="SYNTHETIC_ENGINEERING_ONLY" if synthetic else "DAILY_SCREEN_ONLY",
                           run_id=run_id, economic_confirmation="BLOCKED_HURDLE" if config.get("annual_incremental_cost") is None else "NOT_PERFORMED")
            write_json(destination / "metrics.json", metrics)
            write_json(destination / "table_hashes.json", table_hashes)
            write_json(destination / "uncertainty.json", {"status": "NOT_A_CONFIRMATORY_TEST", "reason": "Synthetic engineering run" if synthetic else "Paired registered evaluation required"})
            write_json(destination / "decisions.json", [{"decision_date": d.decision_date, "execution_date": d.execution_date,
                       "decision_at": str(d.decision_at), "weights": d.weights, "reference_prices": d.reference_prices,
                       "adv20": d.adv20, "status": d.status, "diagnostics": d.diagnostics} for d in decisions])
            (destination / "report.md").write_text(
                "# Run " + run_id + "\n\n" + metrics["status"] + "\n\n"
                "Offline simulated ledger. Not realized profit or evidence of Alpha. "
                "Daily prices do not validate order queues or minute-window capacity.\n", encoding="utf-8")
            append_event(registry, dict(run_id=run_id, event="COMPLETED", status=metrics["status"], table_hashes=table_hashes))
            return destination, metrics
        except BaseException as error:
            failure = {"run_id": run_id, "event": "FAILED", "error": type(error).__name__, "reason": str(error)}
            write_json(destination / "failure.json", failure)
            append_event(registry, failure)
            raise
    finally:
        lock.unlink()


def run_matrix(dataset, base_config, output_root, repo_root, stress=False):
    # Private per-matrix reuse of audited inputs and internally generated
    # targets. No external target injection or cross-dataset cache is exposed.
    dataset = deepcopy(dataset)
    context = {"data_hash": dataset_hash(dataset), "source_hash": source_provenance(repo_root)["source_hash"],
               "audit": audit_dataset(dataset), "targets": {}}
    rows = []
    for variant in ("E0", "R0", "E1", "R1"):
        for scaling in (False, True):
            paths = [(1, 1, 1, 0)]
            if stress:
                # No tax scaling; each path is a predeclared robustness diagnostic.
                paths += [(2, 2, 1, 0), (3, 3, 1, 0), (1, 0, 1, 0), (1, 1, 2, 0)]
                if not _is_synthetic(dataset):
                    paths += [(1, 1, 1, 1), (1, 1, 1, 3)]
            for commission, slippage, delay, cash_delay in paths:
                for capital in (10000, 100000, 500000, 1000000):
                    config = dict(base_config, variant=variant, risk_scaling=scaling, initial_cash=capital,
                                  cost_multiplier=commission, slippage_multiplier=slippage, execution_delay=delay)
                    if cash_delay:
                        config["cash_delay_sessions"] = cash_delay
                    if dataset.manifest.get("signal_release_delay"):
                        config["signal_release_delay"] = dataset.manifest["signal_release_delay"]
                    destination, metrics = _run_experiment(dataset, config, output_root, repo_root, context)
                    rows.append(dict(config=config, metrics=metrics, directory=destination.name))
    if dataset_hash(dataset) != context["data_hash"]:
        append_event(Path(output_root) / "trial_registry.jsonl", {"event": "MATRIX_INVALIDATED", "reason": "Internal input mutation"})
        raise RuntimeError("Matrix mutated its immutable research input")
    write_json(Path(output_root) / "matrix_summary.json", rows)
    return rows
