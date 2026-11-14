"""Admit exact independently reviewed inputs; preserve all original staging evidence."""
import argparse
import json
from pathlib import Path
from quant_research.admission import admit_samples

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(admit_samples(args.stage, args.attestation, args.output, args.repo), ensure_ascii=False))
