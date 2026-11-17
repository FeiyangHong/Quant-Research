"""Offline fixed-case audit; publishes comparisons/schema, never vendor values."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

FIELDS = {"net_profit_parent": "net_profit_parent_company",
          "operating_cash_flow": "cash_flow_from_operating_activities", "total_assets": "total_assets"}


def load_rows(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj is None:
        return []
    return [dict(zip(obj["columns"], values), _index=index) for index, values in zip(obj["index"], obj["data"])]


def matches(row, expected):
    return all(row.get(vendor) is not None and
               abs(Decimal(str(row[vendor])) - Decimal(str(expected[field]))) <= Decimal("0.01")
               for field, vendor in FIELDS.items())


def latest(rows, quarter, cutoff):
    visible = [r for r in rows if r["_index"][1] == quarter and r["info_date"][:10] <= cutoff]
    if not visible:
        raise ValueError("MISSING_VISIBLE_QUARTER")
    last = max(r["info_date"] for r in visible)
    tied = [r for r in visible if r["info_date"] == last]
    if len({tuple(r.get(k) for k in FIELDS.values()) for r in tied}) != 1:
        raise ValueError("AMBIGUOUS_VERSION")
    return tied[0]


def audit(sample_root, originals_manifest):
    sample = Path(sample_root)
    raw = sample / "raw"
    receipt = json.loads((sample / "receipt.json").read_text())
    manifest = json.loads(Path(originals_manifest).read_text(encoding="utf-8"))
    inventory = json.loads(Path("reports/m10_r2/case_inventory.json").read_text(encoding="utf-8"))
    local = {r["expected_sha256"]: Path(r["proposed_local_path"]) for r in manifest["files"]}
    source_hashes = {h: p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h for h, p in local.items()}
    response_hashes = {r["id"]: hashlib.sha256((raw / (r["id"] + ".json")).read_bytes()).hexdigest() == r["source_payload_hash"]
                       for r in receipt["request_results"] if r["status"] == "RETURNED"}
    if not all(source_hashes.values()) or not all(response_hashes.values()):
        raise ValueError("SOURCE_OR_RESPONSE_HASH_MISMATCH")
    cutoff_checks = {}
    for request in receipt["request_results"]:
        if request["endpoint"] == "get_pit_financials_ex" and request["status"] == "RETURNED":
            cutoff_checks[request["id"]] = all(
                r["info_date"][:10] <= request["params"]["date"]
                for r in load_rows(raw / (request["id"] + ".json")))
    checks = []
    for card in inventory["documentary_cards"]:
        sid = card["instrument_id"].split(".")[1]
        if sid not in ("600518", "002857", "002729", "300632"):
            continue
        original_rows = load_rows(raw / (sid + "_original.json"))
        corrected_rows = load_rows(raw / (sid + "_corrected.json"))
        orig_date = card["original"]["published_date"]
        append_visible = [r for r in corrected_rows if r["info_date"][:10] <= orig_date]
        strip_ingestion = lambda rows: sorted(json.dumps({k: v for k, v in r.items() if k != "rice_create_tm"}, sort_keys=True) for r in rows)
        c = dict(security_id=card["instrument_id"], period_end=card["period_end"],
                 before_original_empty=not load_rows(raw / (sid + "_before.json")),
                 repeated_old_cutoff_identical=(raw / (sid + "_original.json")).read_bytes() == (raw / (sid + "_repeat_original.json")).read_bytes(),
                 appended_later_versions_preserve_old_facts=strip_ingestion(original_rows) == strip_ingestion(append_visible), versions=[])
        for phase, rows in [("original", original_rows), ("revision", corrected_rows)]:
            v = card[phase]
            full = [r for r in rows if matches(r, v["values"]) and r["info_date"][:10] == v["published_date"]]
            doc = v["document"]
            page_text = ""
            for page in v["pages"]:
                p = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(local[doc["sha256"]]), "-"], capture_output=True, check=True)
                page_text += p.stdout.decode("utf-8")
            normalized = page_text.replace(",", "").replace("，", "").replace(" ", "")
            c["versions"].append(dict(version=phase, publication_date=v["published_date"], available_at=v["available_at"],
                matched_same_row_and_publication=bool(full), matching_rows=len(full),
                original_document_sha256=doc["sha256"], physical_pages=v["pages"],
                all_three_registered_value_tokens_present=all(str(v["values"][f]) in normalized for f in FIELDS),
                if_adjusted_is_not_used_as_correction_flag=True))
        c["status"] = "PASS_FIXED_THREE_FIELDS_AND_CLOCKS" if all([
            c["before_original_empty"], c["repeated_old_cutoff_identical"], c["appended_later_versions_preserve_old_facts"],
            all(ok for name, ok in cutoff_checks.items() if name.startswith(sid)),
            all(v["matched_same_row_and_publication"] and v["all_three_registered_value_tokens_present"] for v in c["versions"])
        ]) else "BLOCKED_FIXED_FINANCIAL_COMPARISON"
        checks.append(c)
    arithmetic = []
    for sid, cutoff, current_q, prior_q, annual_q, expected_case in [
        ("600518", "2018-04-27", "2017q4", "2016q4", None, "KANGMEI_2017_ORIGINAL_TO_2019_RESTATEMENT"),
        ("002857", "2023-10-27", "2023q3", "2022q3", "2022q4", "sz.002857_2023-09-30")]:
        rows = load_rows(raw / (sid + "_warmup.json"))
        current, prior = latest(rows, current_q, cutoff), latest(rows, prior_q, cutoff)
        annual = latest(rows, annual_q, cutoff) if annual_q else None
        profit = Decimal(str(current[FIELDS["net_profit_parent"]]))
        cfo = Decimal(str(current[FIELDS["operating_cash_flow"]]))
        if annual:
            profit += Decimal(str(annual[FIELDS["net_profit_parent"]])) - Decimal(str(prior[FIELDS["net_profit_parent"]]))
            cfo += Decimal(str(annual[FIELDS["operating_cash_flow"]])) - Decimal(str(prior[FIELDS["operating_cash_flow"]]))
        assets = (Decimal(str(current["total_assets"])) + Decimal(str(prior["total_assets"]))) / 2
        oracle = next(r for r in inventory["m5_independent_decimal_checks"] if r["case_id"] == expected_case)
        arithmetic.append(dict(security_id=sid, cutoff=cutoff, formula="FY_OR_CURRENT_YTD_PLUS_PRIOR_FY_MINUS_PRIOR_YTD",
            profit_ttm_matches=abs(profit - Decimal(oracle["profit_ttm"])) <= Decimal("0.01"),
            cashflow_ttm_matches=abs(cfo - Decimal(oracle["cashflow_ttm"])) <= Decimal("0.01"),
            average_assets_matches=abs(assets - Decimal(oracle["average_assets"])) <= Decimal("0.01"),
            F02_matches=abs(profit / assets - Decimal(oracle["F02_independent"])) < Decimal("1e-12"),
            F03_matches=abs(cfo / assets - Decimal(oracle["F03_independent"])) < Decimal("1e-12"),
            F01="NOT_COMPUTED_NO_ADMITTED_SAME_CLOCK_CAPITALIZATION", production_adapter=False))
    schemas = {}
    for name in ["shares_2020", "industry_2016-01-04", "industry_2020-07-31", "is_st_stock_kangmei", "is_suspended_kangmei", "moutai_dividends_2022"]:
        obj = json.loads((raw / (name + ".json")).read_text())
        schemas[name] = dict(rows=len(obj["data"]) if obj else 0, columns=obj["columns"] if obj else [])
    return dict(status="BLOCKED_DATA_CAPABILITY", reason="FIXED_STRUCTURAL_RESPONSES_DO_NOT_ESTABLISH_REQUIRED_PUBLIC_EFFECTIVE_VERSION_CLOCKS",
        source_hash_matches=sum(source_hashes.values()), sdk_response_hash_matches=sum(response_hashes.values()),
        explicit_financial_cutoff_checks=cutoff_checks,
        financial_case_checks=checks, warmup_and_arithmetic=arithmetic, structural_schemas=schemas,
        financial_scope="Four fixed 3-field comparisons only; not exhaustive financial history/latest-report coverage, adapter admission or human acceptance",
        missing_share_clocks_for=["000002.XSHE", "600028.XSHG", "000725.XSHE", "600519.XSHG", "002857.XSHE"],
        missing_share_fields=["published_at", "available_at", "event_effective_at", "historical_revision_identity", "documented_total_ordinary_ABH_preferred_treasury_semantics"],
        missing_industry_evidence=["historical_taxonomy_version_transition", "assignment_publication_time", "assignment_available_at"],
        additional_limitations=["identity date filters current instrument attributes; not historical names/boards", "000024 absent at fixed 2015-12-30; exclusion is not proof of missing delisted coverage", "ST/suspended booleans are not complete historical risk state", "dividend declaration is an INDEX, not absent; full taxes/rights/actual settlement unverified", "rice_create_tm is ingestion metadata, not historical first availability", "SDK get_shares fills missing preferred_shares with zero; returned zero is not independent no-preferred-share evidence", "source_payload_hash binds SDK-transformed dataframe serialization, not untouched server/wire payload"],
        complete_m10_cards=0, human_acceptances=0, real_r2_accounts=0, performance_metrics=None,
        raw_vendor_values_published=False, protocol_changed=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-root", required=True)
    parser.add_argument("--originals-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.sample_root, args.originals_manifest)
    with Path(args.output).open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
