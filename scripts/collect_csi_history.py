"""Capture official CSI total-return observations, with final holdout locked."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_research.providers.csi import validate_window
from quant_research.providers.baostock import write_immutable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate_window(args.start, args.end)
    if args.output.exists():
        parser.error("Choose a new immutable collection directory")
    endpoint = ("https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=H00300&startDate="
                + args.start.replace("-", "") + "&endDate=" + args.end.replace("-", ""))
    args.output.mkdir(parents=True)
    manifest = {"schema_version": "csi-capture-1.0", "status": "REQUESTED", "source_url": endpoint,
                "start": args.start, "end": args.end, "index_code": "H00300",
                "requested_at": datetime.now(timezone.utc).isoformat(), "historical_first_seen": None,
                "research_admission": "NOT_DATASET_GATE"}
    write_immutable(args.output / "request.json", manifest)
    try:
        with urlopen(Request(endpoint, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}), timeout=20) as response:
            content = response.read(8_000_001)
            manifest["http_status"] = response.status
        if len(content) > 8_000_000:
            raise ValueError("Response exceeded bounded capture size")
        (args.output / "response.payload").write_bytes(content)
        manifest.update(status="CAPTURED_NOT_VALIDATED", bytes=len(content),
                        sha256=hashlib.sha256(content).hexdigest(), raw_path="response.payload")
    except Exception as error:
        manifest.update(status="FAILED", error_type=type(error).__name__, error=str(error))
    manifest["ingested_at"] = datetime.now(timezone.utc).isoformat()
    write_immutable(args.output / "manifest.json", manifest)
    print(json.dumps(manifest))
    return 0 if manifest["status"] == "CAPTURED_NOT_VALIDATED" else 1


if __name__ == "__main__":
    sys.exit(main())
