"""Build an immutable, explicitly unadmitted real R1 data staging snapshot."""
import argparse
import json
from pathlib import Path

from quant_research.providers.real_builder import build_dataset, write_staged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=Path("data/raw_r1_universe/r1_2010_2024"))
    parser.add_argument("--benchmark", type=Path, default=Path("data/normalized_csi/h00300_2010_2024_v1"))
    parser.add_argument("--events", type=Path, default=Path("reports/real_data_phase3/event_manifest.json"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8")) if args.policy else None
    dataset, report = build_dataset(args.collection, args.benchmark, args.events, policy)
    write_staged(dataset, report, args.output)
    print(json.dumps({"status": "STAGING_ONLY", "output": str(args.output), "bars": len(dataset.bars),
        "competitors": report["competitor_count"], "build_blockers": len(report["blockers"]),
        "audit_status": report["dataset_audit"]["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
