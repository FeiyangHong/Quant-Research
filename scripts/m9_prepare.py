"""Write the immutable initial risk anchor, without running an account."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.data import load_dataset
from quant_research.provenance import write_json
from quant_research.risk_budget import initialize_fixed_scale
from quant_research.risk_runner import read_json, validate_registry, verify_data_binding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--binding", type=Path, default=ROOT / "reports/m9_risk/DATA_BINDING.json")
    parser.add_argument("--registry", type=Path, default=ROOT / "reports/m9_risk/EXPERIMENT_REGISTRY.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/m9_risk/INITIAL_RISK_ANCHOR.json")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Initializer already exists and is immutable; verify rather than overwrite")
    validate_registry(read_json(args.registry), ROOT / "docs/M9_PLAN.md")
    dataset = load_dataset(args.dataset_root / "development")
    verify_data_binding(dataset, read_json(args.binding), "development", args.evidence_root)
    initializer = initialize_fixed_scale(dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        import json
        json.dump(initializer, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print("INITIALIZER_ONLY", initializer["anchor_date"], initializer["c"], initializer["initializer_hash"])


if __name__ == "__main__":
    main()
