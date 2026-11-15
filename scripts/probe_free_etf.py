"""Small stdlib-only compatibility probe; NOT_DATASET_GATE, never a backtest.

No SDK downloads, installs, credentials, rate-limit bypass, or automatic retries.
Raw responses stay in the selected local directory; do not publish data without
checking the provider's applicable use and redistribution terms.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request


def run(output: Path, timeout: float = 15):
    output.mkdir(parents=True, exist_ok=True)
    base = "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
    fields = "&klt=101&fqt=0&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    endpoints = [
        ("active_etf", base + "secid=1.510300&beg=20231201&end=20231208" + fields),
        ("delisted_etf", base + "secid=1.512320&beg=20240301&end=20240308" + fields),
        ("delisting_notice", "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-04-11/512320_20240411_TJ7L.pdf"),
    ]
    summary = {"status": "NOT_DATASET_GATE", "performance_evidence": False,
               "historical_queries_end_before": "2025-01-01", "probes": []}
    for label, url in endpoints:
        item = {"id": label, "url": url, "requested_at": datetime.now(timezone.utc).isoformat()}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "QuantResearchDataAudit/0.1 (small public compatibility probe)"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Probe exceeds maximum payload")
                item["http_status"] = response.status
            sha = hashlib.sha256(raw).hexdigest()
            path = output / (label + "_" + sha + (".pdf" if raw.startswith(b"%PDF") else ".json"))
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(raw)
            item.update(status="FETCHED", sha256=sha, raw_path=str(path.resolve()), bytes=len(raw))
            if label != "delisting_notice":
                parsed = json.loads(raw)
                data = parsed.get("data")
                rows = data.get("klines", []) if isinstance(data, dict) else []
                if any(row.split(",", 1)[0] >= "2025-01-01" for row in rows):
                    raise ValueError("Unexpected holdout data in historical response")
                item.update(application_rc=parsed.get("rc"), rows=len(rows), data_is_null=data is None)
        except Exception as exc:
            item.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        summary["probes"].append(item)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = output / ("probe_" + stamp + ".json")
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    summary["manifest_path"] = str(manifest_path.resolve())
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/provider_probes/http"))
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error("timeout must be in (0, 30]")
    result = run(args.output, args.timeout)
    print(json.dumps({"status": result["status"], "manifest_path": result["manifest_path"],
                      "probes": [{key: row[key] for key in ("id", "status", "http_status", "application_rc", "rows", "sha256", "error_type") if key in row}
                                 for row in result["probes"]]}, ensure_ascii=False))
