"""Run only the frozen six-base/eighteen-stress M9 accounts; no M8 replay."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.data import load_dataset
from quant_research.provenance import digest, source_provenance, write_json
from quant_research.risk_runner import (config_for, file_hash, read_json, run_risk_experiment,
    validate_registry, verify_base_receipt, verify_data_binding, verify_fixed_initializer)

PUBLIC_TABLES = ("nav.json", "metrics.json", "config.json", "provenance.json",
                 "execution_assumptions.json", "table_hashes.json", "risk_signals.json")


def export_account(destination, exported):
    exported.mkdir(parents=True, exist_ok=False)
    for name in PUBLIC_TABLES:
        shutil.copyfile(destination / name, exported / name)
    # References/ADV are raw market observations: full decisions remain private.
    decisions = read_json(destination / "decisions.json")
    public_decisions = [{key: value for key, value in row.items() if key not in ("reference_prices", "adv20")}
                        for row in decisions]
    write_json(exported / "decisions.json", public_decisions)
    return {path.name: file_hash(path) for path in sorted(exported.glob("*.json"))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--binding", type=Path, default=ROOT / "reports/m9_risk/DATA_BINDING.json")
    parser.add_argument("--registry", type=Path, default=ROOT / "reports/m9_risk/EXPERIMENT_REGISTRY.json")
    parser.add_argument("--initializer", type=Path, default=ROOT / "reports/m9_risk/INITIAL_RISK_ANCHOR.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs/m9_real")
    parser.add_argument("--public-root", type=Path, default=ROOT / "reports/m9_risk")
    parser.add_argument("--base-receipt", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--phase", choices=("base", "stress"))
    mode.add_argument("--trial-id")
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    lock = args.output_root / ".m9_runner.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("Single M9 matrix writer; retain until process exits.\n")
    try:
        run(args)
    finally:
        lock.unlink()


def run(args):
    registry, binding, initializer = (read_json(path) for path in (args.registry, args.binding, args.initializer))
    validate_registry(registry, ROOT / "docs/M9_PLAN.md")
    datasets = {sample: load_dataset(args.dataset_root / sample) for sample in ("development", "validation")}
    for sample, dataset in datasets.items():
        verify_data_binding(dataset, binding, sample, args.evidence_root)
    verify_fixed_initializer(initializer, datasets["development"], binding)
    records_path = args.public_root / "ACCOUNT_PATHS.json"
    records = read_json(records_path) if records_path.exists() else []
    wanted = [trial for trial in registry["trials"]
              if (trial["trial_id"] == args.trial_id if args.trial_id else
                  ((trial["path"] == "base") == (args.phase == "base")))]
    if not wanted:
        raise ValueError("Requested cell is absent from registered24")
    source_hash = source_provenance(ROOT)["source_hash"]
    registration_paths = (ROOT / "docs/M9_PLAN.md", args.registry, args.binding, args.initializer)
    registration_hash = digest({str(p.resolve().relative_to(ROOT.resolve()).as_posix()): file_hash(p)
                                for p in registration_paths})
    for previous in records:
        if previous.get("status") != "COMPLETED":
            raise RuntimeError("Prior failed attempt remains; explicit correctness registration required before replay")
        if (previous["code_hash"] != source_hash or previous["registration_hash"] != registration_hash
                or previous["data_hash"] != binding["datasets"][previous["period"]]["dataset_hash"]):
            raise RuntimeError("Source/data/registration changed since first M9 account")
    receipt_hash = None
    if any(t["path"] != "base" for t in wanted):
        if args.base_receipt is None:
            raise ValueError("Stress requires --base-receipt independent accounting review")
        receipt_hash = verify_base_receipt(args.base_receipt, records, args.output_root, args.public_root)
    for trial in wanted:
        if any(previous["trial_id"] == trial["trial_id"] for previous in records):
            raise RuntimeError("Immutable trial already attempted: " + trial["trial_id"])
        if source_provenance(ROOT)["source_hash"] != source_hash:
            raise RuntimeError("Code changed within M9 matrix phase")
        if digest({str(p.resolve().relative_to(ROOT.resolve()).as_posix()): file_hash(p)
                   for p in registration_paths}) != registration_hash:
            raise RuntimeError("Registration changed within M9 matrix phase")
        config = config_for(trial)
        try:
            destination, metrics = run_risk_experiment(datasets[trial["period"]], config,
                args.output_root, ROOT, args.evidence_root, trial, registration_paths,
                initializer, binding, receipt_hash, development=datasets["development"],
                base_receipt_path=args.base_receipt, public_root=args.public_root)
            exported = args.public_root / "accounts" / trial["trial_id"]
            hashes = export_account(destination, exported)
            provenance = read_json(destination / "provenance.json")
            private_hashes = {path.name: file_hash(path) for path in sorted(destination.glob("*.json"))}
            records.append(dict(trial, status="COMPLETED", actual_run_id=destination.name,
                run_id=destination.name, actual_config_hash=digest(config),
                code_commit=provenance["git_commit"], code_hash=provenance["source_hash"],
                data_hash=provenance["data_hash"], registration_hash=provenance["registration_hash"],
                initializer_hash=initializer["initializer_hash"], rule_hash=provenance["rule_hash"],
                metrics=metrics, exported_tables=hashes, private_table_hashes=private_hashes,
                artifact_directory=exported.relative_to(ROOT).as_posix(),
                private_artifact_directory=str(destination.resolve())))
        except BaseException as error:
            records.append(dict(trial, status="FAILED", error=type(error).__name__, reason=str(error),
                                private_artifact_directory=str((args.output_root / trial["trial_id"]).resolve())))
            write_json(records_path, records)
            raise
        write_json(records_path, records)
        print(trial["trial_id"], metrics["status"], flush=True)
    if args.phase:
        expected = 6 if args.phase == "base" else 24
        if len(records) != expected or any(row["status"] != "COMPLETED" for row in records):
            raise RuntimeError("M9 phase count differs from frozen registration")


if __name__ == "__main__":
    main()
