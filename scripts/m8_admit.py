"""Admit only independently reviewed M8 holding data, with separate accounts."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.liquid_runner import admit_liquid_samples


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--attestation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('Admission output must be new; retain previous dataset versions')
    print(admit_liquid_samples(args.stage, args.attestation, args.output, ROOT))
