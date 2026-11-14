"""Compare independently captured unadjusted observations without return tests."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def verified(root, item, key="normalized"):
    path = (root / item[key + "_path"]).resolve()
    path.relative_to(root.resolve())
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != item[key + "_sha256"]:
        raise ValueError("Source hash mismatch: " + str(path))
    return json.loads(content)


def reconcile(primary_root, secondary_root):
    primary = {}
    for path in sorted((primary_root / "query_cache").glob("*.json")):
        item = json.loads(path.read_bytes())
        if item.get("kind") == "history" and item.get("status") == "SUCCESS":
            primary[item["code"]] = item
    secondary = {}
    for path in sorted(secondary_root.glob("collection_*.json")):
        for item in json.loads(path.read_bytes())["queries"]:
            secondary[item["code"]] = item
    report = {"scope": "UNADJUSTED_PRICE_VENDOR_COMPARISON", "performance_evidence": False,
        "tolerances": {"price": "0.00005 CNY (below half minimum tick)",
                       "volume": "99 fund units (secondary rounds to lots)",
                       "amount": "max(1 CNY, 0.000001 * primary amount)"}, "instruments": []}
    for code, item in sorted(secondary.items()):
        row = dict(instrument_id=code, secondary_status=item["status"], comparisons=0,
                   mismatches=[], secondary_only_dates=[], primary_only_traded_dates=[])
        if item["status"] != "SUCCESS" or code not in primary:
            row["status"] = "UNRESOLVED_SOURCE_COVERAGE"
            report["instruments"].append(row)
            continue
        left = {x["date"]: x for x in verified(primary_root, primary[code])["records"]}
        right = {x["date"]: x for x in verified(secondary_root, item)}
        verified(primary_root, primary[code], "raw")
        verified(secondary_root, item, "raw")
        row.update(primary_raw_sha256=primary[code]["raw_sha256"], secondary_raw_sha256=item["raw_sha256"])
        row["secondary_only_dates"] = sorted(set(right) - set(left))
        row["primary_only_traded_dates"] = sorted(day for day in set(left) - set(right)
                                                  if not left[day]["suspended"] and Decimal(str(left[day]["volume"])) > 0)
        row["primary_only_open_zero_turnover_dates"] = sorted(day for day in set(left) - set(right)
            if not left[day]["suspended"] and Decimal(str(left[day]["volume"])) == 0
            and Decimal(str(left[day]["amount"])) == 0)
        row["primary_suspended_absent_secondary"] = sorted(day for day in set(left) - set(right) if left[day]["suspended"])
        for day in sorted(set(left) & set(right)):
            for field in ("open", "high", "low", "close", "volume", "amount"):
                a, b = Decimal(str(left[day][field])), Decimal(str(right[day][field]))
                tolerance = (Decimal("99") if field == "volume" else
                    max(Decimal("1"), abs(a) * Decimal("0.000001")) if field == "amount" else Decimal("0.00005"))
                row["comparisons"] += 1
                if abs(a - b) > tolerance:
                    row["mismatches"].append(dict(date=day, field=field, primary=str(a), secondary=str(b), difference=str(a-b)))
        row["status"] = "MATCHED" if not any(row[k] for k in ("mismatches", "secondary_only_dates", "primary_only_traded_dates")) else "REQUIRES_REVIEW"
        report["instruments"].append(row)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.primary, args.secondary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError("Use a new audit version")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([dict(code=r['instrument_id'], status=r['status'], comparisons=r['comparisons'],
        mismatches=len(r['mismatches']), missing=len(r['primary_only_traded_dates'])) for r in result['instruments']]))
