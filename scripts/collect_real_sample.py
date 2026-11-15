"""Collect a bounded real ETF audit sample, never an admitted strategy dataset."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_research.providers.baostock import BaoStockAdapter, Query, normalize_history, write_immutable


CODES = ["sh.510300", "sh.510330", "sh.510500", "sh.512100", "sz.159915", "sh.588000", "sh.512320"]
SNAPSHOTS = ["2019-12-31", "2020-12-31", "2021-03-31", "2021-12-31", "2022-03-31", "2022-12-30",
             "2023-03-31", "2023-12-29", "2024-03-29", "2024-06-28", "2024-09-30", "2024-12-31"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sdk-path", type=Path, help="Optional isolated verified baostock0.9.4 package directory")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--min-interval", type=float, default=1)
    args = parser.parse_args()
    output = (args.output or Path("data/raw_baostock") / ("r1_audit_2019_2024_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new empty collection directory; previous collections are immutable")
    adapter = BaoStockAdapter(output, args.sdk_path, args.timeout, args.max_retries, args.min_interval)
    queries = [Query("calendar", start="2019-01-01", end="2024-12-31")]
    queries += [Query("history", code=code, start="2019-01-01", end="2024-12-31") for code in CODES]
    queries += [Query("universe", date=day) for day in SNAPSHOTS]
    queries += [Query("master", code=code) for code in CODES]
    collection = {"schema_version": "baostock-collection-1.0", "status": "STAGING_ONLY",
                  "research_admission": "NOT_DATASET_GATE", "performance_evidence": False, "synthetic": False,
                  "started_at": datetime.now(timezone.utc).isoformat(), "history_end_cap": "2024-12-31",
                  "scope": "Seven selected ETF histories, twelve historical universe snapshots, calendar and current master queries; not complete R1 universe",
                  "query_results": [], "known_missing": ["verified_full_lifecycle", "corporate_actions", "historical_available_at", "revision_chain", "price_limits", "total_return", "full_license_acceptance"]}
    collection["request_plan_sha256"] = write_immutable(output / "request_plan.json", {
        "queries": [query.__dict__ for query in queries], "collection": collection})
    for query in queries:
        result = adapter.collect(query)
        if result["status"] == "SUCCESS" and query.kind in {"history", "universe"}:
            payload = json.loads((output / result["raw_path"]).read_text(encoding="utf-8"))
            normalized = normalize_history(payload)
            name = query.code or query.date
            path = Path("normalized") / (query.kind + "_" + name + ".json")
            result["normalized_sha256"] = write_immutable(output / path, normalized)
            result["normalized_path"] = path.as_posix()
            result["normalization_issue_rows"] = sum(bool(row["normalization_issues"]) for row in normalized["records"])
        collection["query_results"].append(result)
        print(json.dumps({"kind": query.kind, "code": query.code, "date": query.date,
                          "status": result["status"], "row_count": result["row_count"]}), flush=True)
    collection["finished_at"] = datetime.now(timezone.utc).isoformat()
    collection["collection_complete"] = all(item["status"] == "SUCCESS" for item in collection["query_results"])
    digest = write_immutable(output / "collection.json", collection)
    print(json.dumps({"collection_path": str(output / "collection.json"), "sha256": digest,
                      "status": collection["status"], "collection_complete": collection["collection_complete"]}), flush=True)
    return 0 if collection["collection_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
