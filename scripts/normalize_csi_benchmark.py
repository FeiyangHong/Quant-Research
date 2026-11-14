"""Normalize a saved CSI H00300 HTTP response into immutable STAGING ONLY data.

Raw input is the unmodified response body previously downloaded from the CSI
endpoint below. No network request or historical publication-time inference is
performed. A verified BaoStock collection supplies the full trading calendar.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_research.providers.csi import ENDPOINT, START, END, normalize_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog="Original raw endpoint: " + ENDPOINT)
    parser.add_argument("--raw", type=Path, required=True, help="Unmodified saved CSI response body")
    parser.add_argument("--calendar-collection", type=Path, required=True, help="Existing BaoStock collection root")
    parser.add_argument("--output", type=Path, required=True, help="New immutable staging directory")
    parser.add_argument("--expected-sha256", help="Expected SHA256 of the exact raw response bytes")
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    args = parser.parse_args()
    try:
        manifest = normalize_benchmark(args.raw, args.calendar_collection, args.output, args.expected_sha256,
                                       args.start, args.end)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": manifest["status"], "records": manifest["record_count"],
                      "excluded_non_sessions": manifest["excluded_non_session_count"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
