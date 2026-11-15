"""Verify a BaoStock staging collection and preserve its audit and run disposition."""
import argparse
import itertools
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_research.provenance import source_provenance, validate_run_config, write_json
from quant_research.real_data import audit_collection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory for immutable audit")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new immutable audit directory")
    report = audit_collection(args.collection)
    repo = Path(__file__).resolve().parents[1]
    provenance = source_provenance(repo)
    config = json.loads((repo / "configs/r1b.json").read_text(encoding="utf-8"))
    plans = []
    for sample, capital, variant, scaling, path in itertools.product(
            ("development", "validation"), (10000, 100000, 500000, 1000000),
            ("E0", "R0", "E1", "R1"), (False, True), ((1, 1, 1), (2, 2, 1), (3, 3, 1), (1, 0, 1), (1, 1, 2))):
        cfg = dict(config, sample=sample, initial_cash=capital, variant=variant, risk_scaling=scaling,
                   cost_multiplier=path[0], slippage_multiplier=path[1], execution_delay=path[2])
        validate_run_config(cfg)
        plans.append({"config": cfg, "execution_status": "NOT_RUN_BLOCKED_DATA", "metrics": None,
                      "reason": "Staging observations have not passed Dataset evidence gates"})
    args.output.mkdir(parents=True)
    write_json(args.output / "data_audit.json", report)
    write_json(args.output / "experiment_disposition.json", {"primary_statistical_capital": 100000,
        "planned_configurations": len(plans), "executed": 0, "statistical_tests_performed": 0,
        "final_holdout": "LOCKED", "plans": plans})
    write_json(args.output / "provenance.json", provenance)
    # Preserve exactly what was audited, including source code when dirty.
    for name, expected in provenance["source_files"].items():
        payload = (repo / name).read_bytes()
        import hashlib
        if hashlib.sha256(payload).hexdigest() != expected:
            raise RuntimeError("Source changed during audit snapshot")
        target = args.output / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    print(json.dumps({"status": report["status"], "integrity_status": report["integrity_status"],
                      "errors": report["errors"], "output": str(args.output)}))
    return 0 if report["integrity_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
