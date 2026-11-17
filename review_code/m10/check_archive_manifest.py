"""Independent rehash of enumerated existing M3-M6 archive references only."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
original = Path("F:/QuantTrade/Quant-Research")
report = repo / "reports/m10_r2/COVERAGE_REPORT.json"
payload = json.loads(report.read_text(encoding="utf-8"))
checks = []
for reference in payload["archive_hash_check"]["objects"]:
    path = Path(reference["path"])
    if not path.is_absolute():
        path = original / path
    path = path.resolve()
    path.relative_to(original.resolve())
    observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    checks.append({"path": reference["path"], "kind": reference["kind"], "expected_sha256": reference["expected_sha256"], "observed_sha256": observed, "matches": observed == reference["expected_sha256"]})
raw = [c for c in checks if c["kind"] == "RAW_ARCHIVE"]
result = {
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "reviewer": "M10 independent AI reviewer; not human signoff",
    "coverage_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    "source_scope": "Only enumerated existing files under original private project; no discovery/download",
    "total_references": len(checks), "matched": sum(c["matches"] for c in checks),
    "raw_references": len(raw), "raw_matched": sum(c["matches"] for c in raw),
    "missing": [c["path"] for c in checks if c["observed_sha256"] is None],
    "mismatches": [c for c in checks if not c["matches"]],
    "interpretation": "Historical code drift is separate from raw archive integrity; no code or bytes were restored or rewritten.",
    "checks": checks,
}
output = repo / "reports/m10_review/archive_hash_review.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "checks"}, indent=2))
