"""Bounded secondary-source raw ETF price checks; never a Dataset admission.

The requested identities come from the pre-return representative proof. Failed
or empty retired-product requests remain in the manifest, never drop a fund.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def parse_payload(content, code, start, end):
    payload = json.loads(content)
    if payload.get("rc") != 0:
        raise ValueError("Eastmoney application error")
    data = payload.get("data")
    if data is None:
        return []
    if str(data.get("code")) != code.split(".")[1]:
        raise ValueError("Wrong instrument identity")
    rows, seen = [], set()
    for line in data.get("klines", []):
        values = line.split(",")
        if len(values) != 11:
            raise ValueError("Unexpected Eastmoney row width")
        day = values[0]
        if not start <= day <= end or day >= "2025-01-01" or day in seen:
            raise ValueError("Out-of-window/holdout/duplicate observation")
        seen.add(day)
        row = dict(zip(("date", "open", "close", "high", "low", "volume_lots", "amount",
                        "amplitude", "pct_change", "change", "turnover_rate"), values))
        for key in ("open", "close", "high", "low", "volume_lots", "amount"):
            if not Decimal(row[key]).is_finite() or Decimal(row[key]) < 0:
                raise ValueError("Invalid numeric observation")
        row["volume"] = str(Decimal(row["volume_lots"]) * 100)
        rows.append(row)
    return sorted(rows, key=lambda row: row["date"])


def collect(code, output, start="2010-01-01", end="2024-12-31"):
    if end >= "2025-01-01" or start > end or not code.startswith(("sh.", "sz.")):
        raise ValueError("Explicit pre-2025 domestic ETF window required")
    params = dict(secid=("1." if code.startswith("sh.") else "0.") + code[3:],
        beg=start.replace("-", ""), end=end.replace("-", ""), klt=101, fqt=0, lmt=10000,
        fields1="f1,f2,f3,f4,f5,f6", fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urlencode(params)
    item = dict(code=code, start=start, end=end, url=url,
        requested_at=datetime.now(timezone.utc).isoformat(), status="PENDING")
    try:
        request = Request(url, headers={"User-Agent": "QuantResearchDataAudit/0.1"})
        with urlopen(request, timeout=20) as response:
            raw = response.read(4_000_001)
            item["http_status"] = response.status
        if len(raw) > 4_000_000:
            raise ValueError("Payload exceeds bound")
        digest = hashlib.sha256(raw).hexdigest()
        path = output / "raw" / (digest + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        item.update(raw_path=path.relative_to(output).as_posix(), raw_sha256=digest)
        rows = parse_payload(raw, code, start, end)
        normalized = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        nsha = hashlib.sha256(normalized).hexdigest()
        target = output / "normalized" / (nsha + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(normalized)
        item.update(status="SUCCESS" if rows else "EMPTY_RESPONSE", row_count=len(rows),
                    normalized_path=target.relative_to(output).as_posix(), normalized_sha256=nsha)
    except Exception as error:
        item.update(status="FAILED", error_type=type(error).__name__, error=str(error))
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = args.output / ("collection_" + stamp + ".json")
    manifest = dict(status="SECONDARY_SOURCE_ONLY", strategy_returns_observed=False,
                    adjustment="UNADJUSTED", end_cap="2024-12-31", queries=[])
    for code in sorted(set(args.codes)):
        item = collect(code, args.output)
        manifest["queries"].append(item)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: item[k] for k in ("code", "status", "row_count", "error") if k in item}), flush=True)
        time.sleep(1)
    print(str(path))


if __name__ == "__main__":
    main()
