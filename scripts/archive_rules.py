"""Archive explicitly named official public rules; not a market data provider."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = [
    ("szse_2026", "https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf", "2026-04-24", "2026-07-06"),
    ("sse_2026", "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml", "2026-04-24", "2026-07-06"),
    ("mof_stamp_2023", "https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm", "2023-08-27", "2023-08-28"),
]


def main():
    destination = Path("data/raw_rules")
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for name, url, published, effective in SOURCES:
        item = dict(rule_id=name, source_url=url, published_on=published, effective_on=effective,
                    retrieved_at=datetime.now(timezone.utc).isoformat())
        try:
            with urlopen(Request(url, headers={"User-Agent": "QuantResearch/0.1 public-rule-archiver"}), timeout=20) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
            suffix = ".pdf" if body.startswith(b"%PDF") else ".html"
            sha = hashlib.sha256(body).hexdigest()
            path = destination / (name + "-" + sha[:12] + suffix)
            if not path.exists():
                path.write_bytes(body)
            item.update(status="ARCHIVED_NOT_FULLY_VALIDATED", sha256=sha, content_type=content_type,
                        local_object=str(path), bytes=len(body))
        except Exception as error:
            item.update(status="DOWNLOAD_FAILED", error=str(error))
        records.append(item)
    report = Path("reports/m0_m1/rule_manifest.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(dict(coverage="PARTIAL_NOT_A_COMPLETE_HISTORICAL_RULE_TABLE", rules=records),
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({r["rule_id"]: r["status"] for r in records}))


if __name__ == "__main__":
    main()
