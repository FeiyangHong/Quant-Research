"""Local-only non-author comparisons; never emit licensed source values."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "work/m10_activation/campus_sample_01"
FIELD_MAP = {
    "net_profit_parent": "net_profit_parent_company",
    "operating_cash_flow": "cash_flow_from_operating_activities",
    "total_assets": "total_assets",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def records(name):
    data = read(SAMPLE / "raw" / (name + ".json"))
    if data is None:
        return []
    return [(tuple(index), dict(zip(data["columns"], row)))
            for index, row in zip(data["index"], data["data"])]


def cents(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def main():
    inventory = read(ROOT / "reports/m10_r2/case_inventory.json")
    originals = read(ROOT / "reports/m10_activation/CAMPUS_MINIMUM_ORIGINALS.json")
    receipt = read(SAMPLE / "receipt.json")
    checks = {}
    checks["13_official_original_hashes_match"] = len(originals["files"]) == 13 and all(
        hashlib.sha256(Path(row["proposed_local_path"]).read_bytes()).hexdigest() == row["expected_sha256"]
        for row in originals["files"])
    checks["26_response_hashes_match"] = len(receipt["request_results"]) == 26 and all(
        hashlib.sha256((SAMPLE / "raw" / (row["id"] + ".json")).read_bytes()).hexdigest() == row["source_payload_hash"]
        for row in receipt["request_results"])
    cases = {}
    for card in inventory["documentary_cards"]:
        sid = card["instrument_id"].split(".")[-1]
        if sid not in {"600518", "002857", "002729", "300632"}:
            continue
        year, month, _ = map(int, card["period_end"].split("-"))
        quarter = f"{year}q{month // 3}"
        valid = []
        for phase, suffix in [("original", "original"), ("revision", "corrected")]:
            target = card[phase]
            matches = [(key, row) for key, row in records(sid + "_" + suffix)
                       if key[0].startswith(sid) and key[1] == quarter
                       and row["info_date"][:10] == target["published_date"]
                       and all(cents(row[vendor]) == cents(target["values"][field])
                               for field, vendor in FIELD_MAP.items())]
            valid.append(len(matches) == 1)
        old = records(sid + "_original")
        repeated = records(sid + "_repeat_original")
        later_old = [(key, row) for key, row in records(sid + "_corrected")
                     if row["info_date"][:10] <= card["original"]["published_date"]]
        def canonical(rows):
            return sorted(json.dumps([key, {k: v for k, v in row.items() if k != "rice_create_tm"}], sort_keys=True)
                          for key, row in rows)
        cases[sid] = {"two_versions_match_exact_cents_and_identity": all(valid),
                      "before_publication_empty": not records(sid + "_before"),
                      "repeat_all_fields_identical": old == repeated,
                      "append_preserves_old_fields_excluding_ingestion": canonical(old) == canonical(later_old)}
    arithmetic = {}
    for sid, current, previous, annual, cutoff, case_id in [
        ("600518", "2017q4", "2016q4", None, "2018-04-27", "KANGMEI_2017_ORIGINAL_TO_2019_RESTATEMENT"),
        ("002857", "2023q3", "2022q3", "2022q4", "2023-10-27", "sz.002857_2023-09-30")]:
        rows = records(sid + "_warmup")
        def choose(quarter):
            visible = [(key, row) for key, row in rows if key[0].startswith(sid)
                       and key[1] == quarter and row["info_date"][:10] < cutoff]
            latest_date = max(row["info_date"] for _, row in visible)
            latest = [row for _, row in visible if row["info_date"] == latest_date]
            assert len({tuple(cents(row[k]) for k in FIELD_MAP.values()) for row in latest}) == 1
            return latest[0]
        now, prior = choose(current), choose(previous)
        full_year = choose(annual) if annual else None
        average_assets = (cents(now["total_assets"]) + cents(prior["total_assets"])) / 2
        profit, cash = [cents(now[k]) + (cents(full_year[k]) - cents(prior[k]) if full_year else 0)
                        for k in ("net_profit_parent_company", "cash_flow_from_operating_activities")]
        oracle = next(x for x in inventory["m5_independent_decimal_checks"] if x["case_id"] == case_id)
        arithmetic[sid] = {
            "profit_ttm_exact_cents": profit == Decimal(oracle["profit_ttm"]),
            "cfo_ttm_exact_cents": cash == Decimal(oracle["cashflow_ttm"]),
            "average_assets_exact": average_assets == Decimal(oracle["average_assets"]),
            "F02_matches_1e12": abs(profit / average_assets - Decimal(oracle["F02_independent"])) < Decimal("1e-12"),
            "F03_matches_1e12": abs(cash / average_assets - Decimal(oracle["F03_independent"])) < Decimal("1e-12"),
        }
    result = {"reviewer": "NON_AUTHOR_AI_NOT_HUMAN", "source_values_emitted": False,
              "source_hash_checks": checks, "four_fixed_case_checks": cases,
              "two_local_arithmetic_checks": arithmetic,
              "not_verified": ["full_pool_PIT", "production_adapter", "F01", "human_acceptance",
                               "PDF_table_row_semantics_independent_visual_review", "actual_vendor_wire_payload"]}
    target = ROOT / "reports/m10_activation/CAMPUS_INDEPENDENT_CHECKS.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("INDEPENDENT_LOCAL_CHECK_FAILED_NO_RAW_OUTPUT") from None
