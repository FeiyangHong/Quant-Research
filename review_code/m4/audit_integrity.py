"""Read-only hashes and internal counts; no source extraction/admission claim."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


issues = []
manifest = read("reports/m4_data/source_manifest.json")
for item in manifest["raw_objects"]:
    path = ROOT / item["path"]
    if not path.is_file() or sha(path) != item["sha256"]:
        issues.append({"source_hash_mismatch": item["path"]})
    elif path.stat().st_size != item["byte_count"]:
        issues.append({"source_byte_mismatch": item["path"]})
    if item.get("expected_sha256") and item["sha256"] != item["expected_sha256"]:
        issues.append({"manifest_hash_disagreement": item["path"]})
pool = read("reports/m4_data/full_pool_2020-07-31.json")["rows"]
coverage = read("reports/m4_data/coverage_summary.json")
if len(pool) != coverage["main_chinext_denominator"] or len({r["instrument_id"] for r in pool}) != len(pool):
    issues.append({"pool_count_or_identity_disagreement": len(pool)})
boards = dict(Counter(row["board_scope"] for row in pool))
if boards != coverage["boards"]:
    issues.append({"board_counts_disagreement": boards})
cards = read("reports/m4_data/financial_vintage_cases.json")
card_counts = dict(Counter(card["case_status"] for card in cards["cases"]))
if sum(card["case_status"] == "COMPLETE_DOCUMENTARY_PAIR" for card in cards["cases"]) != cards["complete_documentary_pairs"]:
    issues.append({"card_count_disagreement": card_counts})
if cards["independent_human_accepted_cases"] != 0 or cards["full_pool_vintage_gate"] != "BLOCKED":
    issues.append({"unexpected_data_admission_claim": True})
engineering = read("reports/m4_correctness/engineering_replay/provenance.json")
for name, expected in engineering["artifact_sha256"].items():
    path = ROOT / "reports/m4_correctness/engineering_replay" / name
    if not path.is_file() or sha(path) != expected:
        issues.append({"engineering_hash_mismatch": name})
for name, expected in engineering.get("source_sha256", {}).items():
    if sha(ROOT / name) != expected:
        issues.append({"engineering_source_hash_mismatch": name})
for case in engineering["cases"]:
    if case["status"] != "PASS" or case["real_market_evidence"] is not False:
        issues.append({"engineering_case_status": case["case"]})
report = dict(status="PASS" if not issues else "FAIL", issues=issues,
    raw_data_objects_checked=len(manifest["raw_objects"]), full_pool_rows=len(pool),
    board_counts=boards, financial_card_counts=card_counts,
    human_accepted_cases=cards["independent_human_accepted_cases"],
    engineering_artifact_hashes_checked=len(engineering["artifact_sha256"]),
    engineering_source_hashes_checked=len(engineering.get("source_sha256", {})),
    engineering_cases=len(engineering["cases"]),
    limits="Integrity/count checks only. This reviewer did not re-extract original financial PDFs or independently establish historical full-pool completeness.",
    input_report_hashes={p: sha(ROOT/p) for p in ["reports/m4_data/source_manifest.json",
        "reports/m4_data/coverage_summary.json", "reports/m4_data/full_pool_2020-07-31.json",
        "reports/m4_data/financial_vintage_cases.json", "reports/m4_correctness/engineering_replay/provenance.json"]})
(ROOT / "work/m4_independent/artifact_integrity.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(bool(issues))
