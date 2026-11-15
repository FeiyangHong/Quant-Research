"""Run predeclared free equity source admission probes (no strategy returns)."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.providers.baostock import canonical, utc_now, write_immutable
from quant_research.providers.equity_audit import validate_query, sdk_worker, fetch_http


def probe_queries():
    result = [{"kind": "universe", "day": day} for day in ("2016-01-04", "2018-10-18", "2020-07-20", "2024-12-31")]
    for code, start, end in [("sz.000979", "2018-09-03", "2018-12-31"),
                             ("sz.300104", "2017-04-10", "2018-02-09"),
                             ("sz.300104", "2020-06-01", "2020-07-31"),
                             ("sh.600518", "2019-05-13", "2019-05-24"),
                             ("sz.300059", "2020-08-17", "2020-08-28"),
                             ("sh.600519", "2023-06-20", "2023-07-07")]:
        result.append(dict(kind="history", code=code, start_date=start, end_date=end))
    for code in ("sh.600518", "sz.000979", "sz.300059"):
        for day in ("2016-01-04", "2020-07-20", "2024-12-31"):
            result.append(dict(kind="industry", code=code, date=day))
    result += [dict(kind="dividend", code="sh.600519", year=2023, yearType="operate"),
               dict(kind="dividend", code="sz.300104", year=2016, yearType="operate"),
               dict(kind="adjust", code="sh.600519", start_date="2023-01-01", end_date="2023-12-31"),
               dict(kind="adjust", code="sz.300104", start_date="2016-01-01", end_date="2020-07-31")]
    for kind in ("profit", "balance", "cashflow"):
        for year in (2017, 2018):
            result.append(dict(kind=kind, code="sh.600518", year=year, quarter=4))
    return result


def collect_sdk(args):
    lock = ROOT / "data" / ".baostock_collection.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as stream:
        stream.write(str(os.getpid()))
    results = []
    try:
        for query in probe_queries():
            validate_query(query)
            key = hashlib.sha256(canonical(query)).hexdigest()[:20]
            cache = args.output / "query_manifests" / (key + ".json")
            if cache.exists():
                results.append(json.loads(cache.read_bytes()))
                continue
            started = utc_now()
            config = dict(query=query, sdk_path=str(args.sdk_path.resolve()))
            try:
                options = dict(input=canonical(config), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=30, check=False, cwd=str(ROOT))
                if sys.platform == "win32":
                    options["creationflags"] = subprocess.CREATE_NO_WINDOW
                process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"], **options)
                payload = json.loads(process.stdout)
            except subprocess.TimeoutExpired:
                payload = dict(status="TIMEOUT", fields=[], rows=[], error="Killed after 30 seconds")
            except Exception as exc:
                payload = dict(status="FAILED", fields=[], rows=[], error=str(exc))
            payload.update(query=query, requested_at=started, ingested_at=utc_now(),
                           source="BaoStock", availability_mode="AUDIT_ONLY_NOT_PIT", available_at=None,
                           vendor_first_seen_at=None, performance_evidence=False)
            sha = hashlib.sha256(canonical(payload)).hexdigest()
            raw = args.output / "raw" / (key + "_" + sha + ".json")
            write_immutable(raw, payload)
            record = dict(query=query, status=payload["status"], row_count=len(payload["rows"]),
                          raw_path=raw.as_posix(), sha256=sha)
            write_immutable(cache, record)
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            time.sleep(1)
    finally:
        lock.unlink()
    write_immutable(args.output / "sdk_probe_manifest.json", dict(schema_version="equity-admission-probe-1.0", queries=results,
                    final_holdout_locked=True, requested_through="2024-12-31", performance_evidence=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--sdk-path", type=Path, default=ROOT / "work/data_probe/baostock_sdk")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw_equity_admission")
    args = parser.parse_args()
    if args.worker:
        sys.stdout.buffer.write(canonical(sdk_worker(json.load(sys.stdin))))
    else:
        collect_sdk(args)


if __name__ == "__main__":
    main()
