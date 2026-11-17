"""Read-only M3-M6 evidence review; no production imports or network access.

Writes only M10 review/inventory outputs. Original private bytes stay in place.
The calendar is existing evidence, not an independent exchange-calendar audit.
"""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = Path("F:/QuantTrade/Quant-Research")


def read(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_check(doc):
    path = Path(doc["raw_path"])
    exists = path.is_file()
    blob = path.read_bytes() if exists else b""
    actual = hashlib.sha256(blob).hexdigest() if exists else None
    return {
        "path": str(path), "expected_sha256": doc["sha256"],
        "observed_sha256": actual, "exists": exists,
        "hash_matches": exists and actual == doc["sha256"],
        "pdf_magic": blob.startswith(b"%PDF-"), "bytes": len(blob),
        "url": doc.get("url"), "retrieved_at": doc.get("ingested_at"),
    }


def main():
    queue_path = "reports/m3_equity_admission/revision_candidate_queue.json"
    vintage_path = "reports/m4_data/financial_vintage_cases.json"
    queue = read(queue_path)["cases"]
    vintage = read(vintage_path)["cases"]
    facts = read("reports/m5_financial/canonical_facts.json")
    calendar = read("tests/fixtures/m5_verified_calendar_2015_2024.json")["trading_dates"]
    card_files = sorted((ROOT / "reports/m5_financial/human_review").glob("*.json"))
    clock_checks, documentary_cards, source_results = [], [], {}
    for card_file in card_files:
        card = json.loads(card_file.read_text(encoding="utf-8"))
        case = card["case"]
        human = card["human_review"]
        blank = all(not human.get(k) for k in ("reviewer", "reviewed_at", "decision", "signature"))
        selected = {k: case[k] for k in ("case_id", "instrument_id", "period_end", "case_status")}
        selected.update({
            "card_path": card_file.relative_to(ROOT).as_posix(), "card_sha256": digest(card_file),
            "human_fields_blank": blank, "human_accepted": card.get("human_accepted", False),
            "existing_agent_status": card["agent_documentary_status"],
            "m10_complete_review_card": False,
            "missing_for_m10": ["exhaustive version and latest-report coverage", "same-clock common-share valuation cap and complete F01-F03 impact", "M10 extraction/as-of comparison for all required inputs", "independent human acceptance"],
            "source_clock_precision": case["publication_precision"],
            "vendor_first_seen_at": case.get("vendor_first_seen_at"),
            "revision_chain_scope": case["revision_chain_scope"],
            "original": case["original"], "revision": case["revision"],
        })
        for version in ("original", "revision"):
            v = case[version]
            later = [d for d in calendar if d > v["published_date"]]
            expected_available = later[0] + "T21:00:00+08:00" if later else None
            expected_execution = later[1] if len(later) > 1 else None
            clock_checks.append({
                "case_id": case["case_id"], "version": version,
                "published_date": v["published_date"], "available_at": v["available_at"],
                "expected_available_at": expected_available,
                "earliest_execution": v["earliest_execution"], "expected_execution": expected_execution,
                "available_matches": v["available_at"] == expected_available if expected_available else None,
                "execution_matches": v["earliest_execution"] == expected_execution if expected_execution else None,
                "verification_status": "CHECKED_PRE_2025" if expected_execution else "OUTSIDE_CLOSED_HOLDOUT_NOT_REVERIFIED",
                "admissible_in_pre2025_window": v["available_at"][:10] <= "2024-12-31",
                "precision": "date_only", "retrieved_at": v["document"].get("ingested_at"),
            })
            for doc in [v["document"], v.get("supporting_correction_document")]:
                if doc:
                    source_results[doc["sha256"]] = source_check(doc)
        documentary_cards.append(selected)

    queue_inventory = []
    for position, candidate in enumerate(queue, 1):
        linked = [c for c in vintage if c.get("queue_position") == position]
        assert len(linked) <= 1
        case = linked[0] if linked else None
        checked = source_check(candidate["source"])
        source_results[candidate["source"]["sha256"]] = checked
        gaps = (["resolve retained original/revised source conflicts"] if case and case["case_status"].startswith("QUARANTINED") else [])
        if not case:
            gaps += ["identify report periods and original filings", "original/revision pages, row/column, amounts, scope and units", "conservative original/revision as-of comparison"]
        gaps += ["exhaustive version-chain and latest-report coverage", "F01-F03 input/impact and production comparison", "independent human signature bound to card/document hashes"]
        queue_inventory.append({
            "queue_position": position, "security_id": candidate["instrument_id"],
            "announcement_id": candidate["announcement_id"], "correction_publication_date": candidate["publication_date"],
            "title": candidate["title"], "original_queue_status": candidate["case_status"],
            "current_documentary_status": case["case_status"] if case else "CORRECTION_PDF_ONLY_UNPAIRED",
            "report_period": case["period_end"] if case else None,
            "linked_case_id": case["case_id"] if case else None,
            "original_case_path": "reports/m4_data/financial_cases/" + case["case_id"] + ".json" if case else None,
            "correction_source_check": checked, "conflicts": case.get("conflicts", []) if case else [],
            "completion_gaps": gaps, "human_accepted": False, "m10_complete_review_card": False,
            "planned_checks": ["original/correction", "comparative restatement", "date precision and cutoff", "YTD versus TTM", "currency/amount units", "negative profits retained", "A/B/H ordinary-share denominator"],
        })

    page_checks, fact_clocks = [], []
    page_cache = {}
    for fact in facts:
        raw = EVIDENCE_ROOT / fact["source_document_path"]
        h = fact["source_document_hash"]
        source_results[h] = source_check({"raw_path": str(raw), "sha256": h, "url": fact["source_url"]})
        key = (str(raw), fact["source_page"])
        if key not in page_cache:
            proc = subprocess.run(["pdftotext", "-f", str(key[1]), "-l", str(key[1]), "-layout", str(raw), "-"], capture_output=True, check=False)
            page_cache[key] = (proc.returncode, proc.stdout.decode("utf-8", errors="replace"))
        code, content = page_cache[key]
        token = fact["source_value"].replace(",", "")
        page_checks.append({"revision_id": fact["revision_id"], "source_hash": h, "page": fact["source_page"], "text_extraction_exit": code, "source_value_token_present": token in content.replace(",", ""), "scope": "token check only; not new visual row/column validation"})
        later = [d for d in calendar if d > fact["published_at"][:10]]
        fact_clocks.append({"revision_id": fact["revision_id"], "available_at": fact["available_at"], "expected_available_at": later[0] + "T21:00:00+08:00", "matches": fact["available_at"] == later[0] + "T21:00:00+08:00"})

    # Independent Decimal oracle uses source-transcribed values, not production factors.
    factor_checks = []
    exports = read("reports/m5_financial/factor_cases.json")
    with localcontext() as ctx:
        ctx.prec = 40
        for case in exports:
            out = case["factor"]
            visible = {}
            for fact in sorted(facts, key=lambda r: r["available_at"]):
                if fact["instrument_id"] == out["instrument_id"] and fact["available_at"] <= out["asof"]:
                    visible[(fact["period_end"], fact["field"])] = Decimal(fact["value"])
            target = out["period_end"]
            year = int(target[:4])
            previous = str(year - 1) + target[4:]
            def ttm(field):
                value = visible[(target, field)]
                return value if target.endswith("12-31") else value + visible[(str(year - 1) + "-12-31", field)] - visible[(previous, field)]
            profit, cash = ttm("net_profit_parent_ytd"), ttm("operating_cashflow_ytd")
            assets = (visible[(target, "total_assets")] + visible[(previous, "total_assets")]) / Decimal(2)
            f02, f03 = profit/assets, cash/assets
            factor_checks.append({"case_id": case["case_id"], "asof": out["asof"], "profit_ttm": str(profit), "cashflow_ttm": str(cash), "average_assets": str(assets), "F02_independent": str(f02), "F03_independent": str(f03), "F02_matches": abs(float(f02)-out["F02"]) < 1e-14, "F03_matches": abs(float(f03)-out["F03"]) < 1e-14, "F01_still_null": out["F01"] is None, "formal_eligible": out["formal_eligible"], "latest_period_status": out["latest_period_status"], "uses_production_function": False})

    event_results = read("reports/m6_stock_execution/results.json")
    inventory = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "authorship": "M10 independent AI reviewer; not original M3-M6 author; not human acceptance",
        "status": "NOT_READY_FOR_HUMAN_REVIEW",
        "scope": "existing local evidence only; no collection, no performance, no holdout, no original-file writes",
        "queue_frozen_from": {"path": queue_path, "sha256": digest(ROOT / queue_path)},
        "counts": {"fixed_correction_candidate_pdfs": len(queue), "fixed_candidate_pdfs_hash_verified": sum(c["correction_source_check"]["hash_matches"] and c["correction_source_check"]["pdf_magic"] for c in queue_inventory), "existing_complete_documentary_pairs": len(documentary_cards), "queue_members_with_documentary_pair": sum(c["current_documentary_status"] == "COMPLETE_DOCUMENTARY_PAIR" for c in queue_inventory), "existing_supplemental_kangmei_pair": 1, "quarantined_queue_cases": sum(c["current_documentary_status"].startswith("QUARANTINED") for c in queue_inventory), "unpaired_queue_cases": sum(c["current_documentary_status"] == "CORRECTION_PDF_ONLY_UNPAIRED" for c in queue_inventory), "m5_main_factor_cases_overlapping_pairs": len(exports), "m10_complete_review_cards": 0, "verified_human_acceptances": sum(c["human_accepted"] and not c["human_fields_blank"] for c in documentary_cards)},
        "human_count_basis": "Inspected all five existing human card name/date/decision/signature fields and accepted flags; all empty/false. Canonical fact flags also inspected. No other human receipt supplied in this task. Not inferred from a filename count.",
        "canonical_fact_human_signoffs": sum(bool(f.get("independent_human_signoff")) for f in facts),
        "documentary_cards": documentary_cards,
        "fixed_difficult_queue": queue_inventory,
        "case_clock_checks": clock_checks, "fact_clock_checks": fact_clocks,
        "source_checks": sorted(source_results.values(), key=lambda s: s["expected_sha256"]),
        "m5_page_token_checks": page_checks, "m5_independent_decimal_checks": factor_checks,
        "m6_saved_event_states": event_results["cases"],
        "m6_scope": "Saved engineering replay states checked; not rerun; no actual broker ledger verified. No zero-fill Moutai replay promoted to a dividend pass.",
        "remaining_global_dependencies": ["usable licensed full-period primary source", "full historical identities/status/industry/common-share lineage", "complete original/revised financial histories and latest-report/freshness contract", "full corporate-action/rights/rates coverage and integrated R2 execution", "at least 20 complete unique review cards and independent human acceptances"],
    }
    target = ROOT / "reports/m10_r2/case_inventory.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"counts": inventory["counts"], "source_hashes_match": all(s["hash_matches"] for s in source_results.values()), "unique_sources_checked": len(source_results), "pre2025_case_clocks_match": all(c["available_matches"] and c["execution_matches"] for c in clock_checks if c["verification_status"] == "CHECKED_PRE_2025"), "outside_holdout_clocks_not_reverified": sum(c["verification_status"] != "CHECKED_PRE_2025" for c in clock_checks), "fact_clocks_match": all(c["matches"] for c in fact_clocks), "page_tokens_match": all(c["source_value_token_present"] for c in page_checks), "decimal_factors_match": all(c["F02_matches"] and c["F03_matches"] for c in factor_checks)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
