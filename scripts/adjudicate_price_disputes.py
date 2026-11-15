"""Third-vendor checks only for recorded discrepancies, preserving all sources.

The endpoint includes unsolicited quote fields. Store the whole response in
quarantine for integrity; never inspect or normalize anything except historical
`day` rows inside the explicit pre-2025 request window.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen, Request


def run(audit_path, root, output):
    audit = json.loads(audit_path.read_bytes())
    results = []
    for item in audit["instruments"]:
        differences = item["mismatches"]
        if not differences:
            continue
        code = item["instrument_id"].replace(".", "")
        start, end = min(r["date"] for r in differences), max(r["date"] for r in differences)
        if end >= "2025-01-01":
            raise ValueError("Holdout cannot enter discrepancy requests")
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + code + ",day," + start + "," + end + ",640,"
        result = dict(instrument_id=item["instrument_id"], url=url, start=start, end=end,
                      requested_at=datetime.now(timezone.utc).isoformat(), primary_modified=False)
        try:
            with urlopen(Request(url, headers={"User-Agent": "QuantResearchDataAudit/0.1"}), timeout=20) as response:
                content = response.read(4_000_001)
            if len(content) > 4_000_000:
                raise ValueError("Response exceeds bound")
            sha = hashlib.sha256(content).hexdigest()
            path = root / "quarantine" / (sha + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(content)
            result.update(raw_path=path.relative_to(root).as_posix(), raw_sha256=sha,
                          unused_fields_policy="UNSOLICITED_FIELDS_QUARANTINED_NOT_INSPECTED_OR_ADMITTED")
            payload = json.loads(content)
            if payload.get("code") != 0:
                raise ValueError("Third-vendor application error")
            bars = payload.get("data", {}).get(code, {}).get("day", [])
            if any(not start <= row[0] <= end for row in bars):
                raise ValueError("Historical rows exceed requested window")
            values = {row[0]: dict(zip(("open", "close", "high", "low"), row[1:5])) for row in bars}
            corroborated, unresolved = [], []
            for row in differences:
                actual = values.get(row["date"], {}).get(row["field"])
                evidence = dict(date=row["date"], field=row["field"])
                if actual is not None and Decimal(actual) == Decimal(row["primary"]):
                    corroborated.append(evidence)
                else:
                    unresolved.append(evidence)
            result.update(status="PRIMARY_CORROBORATED" if not unresolved else "UNRESOLVED",
                          corroborated_fields=corroborated, unresolved_fields=unresolved)
        except Exception as exc:
            result.update(status="FAILED", error=str(exc))
        results.append(result)
        print(json.dumps({k: result[k] for k in ("instrument_id", "status")}), flush=True)
    if output.exists():
        raise FileExistsError("Use a new audit version")
    output.write_text(json.dumps(dict(reconciliation_sha256=hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        results=results, policy="RETAIN_PREREGISTERED_PRIMARY_ONLY_IF_CORROBORATED; NO_AUTOMATIC_PRICE_EDITS"),
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.audit, args.root, args.output)
