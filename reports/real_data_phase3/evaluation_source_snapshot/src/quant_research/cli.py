from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import audit_dataset, load_dataset, save_dataset, synthetic_dataset
from .provenance import write_json
from .runner import run_experiment, run_matrix


def main():
    parser = argparse.ArgumentParser(description="Offline A-share research; final holdout remains locked")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("fixture", help="Create synthetic engineering data, never investment evidence")
    fixture.add_argument("--output", type=Path, required=True)
    fixture.add_argument("--seed", type=int, default=20261114)
    audit = sub.add_parser("audit")
    audit.add_argument("--data", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    for name in ("run", "matrix"):
        run = sub.add_parser(name)
        run.add_argument("--data", type=Path, required=True)
        run.add_argument("--config", type=Path, default=Path("configs/r1b.json"))
        run.add_argument("--output", type=Path, required=True)
        if name == "matrix":
            run.add_argument("--stress", action="store_true")
    args = parser.parse_args()
    if args.command == "fixture":
        save_dataset(synthetic_dataset(seed=args.seed), args.output)
        print("SYNTHETIC_ENGINEERING_ONLY " + str(args.output))
        return
    dataset = load_dataset(args.data, allow_unverified=args.command == "audit")
    if args.command == "audit":
        report = audit_dataset(dataset)
        write_json(args.output, report)
        print(report.get("status", "AUDITED"))
        return
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.command == "run":
        destination, metrics = run_experiment(dataset, config, args.output, args.repo)
        print(metrics["status"] + " " + str(destination))
    else:
        rows = run_matrix(dataset, config, args.output, args.repo, stress=args.stress)
        print("Completed " + str(len(rows)) + " registered engineering/screening runs")


if __name__ == "__main__":
    main()
