"""Read licensed share samples locally; emit only schema/count/boolean evidence."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


def check(root):
    sample = root / "work/m10_activation/alternative_share_anchor_01"
    payload = json.loads((sample / "raw.json").read_text())
    receipt = json.loads((sample / "receipt.json").read_text())
    rows = [dict(zip(payload["columns"], values), security=ix[0], quarter=ix[1])
            for ix, values in zip(payload["index"], payload["data"])]
    source = json.loads((root / "reports/m10_activation/OFFLINE_ALTERNATIVES_ORIGINAL_RECEIPT.json").read_text())
    case = next(c for c in json.loads((root / "reports/m5_market_cap/coverage_summary.json").read_text())["cases"]
                if c["instrument_id"] == "sh.600519")
    expected = case["original_document_fact"]
    matched = [r for r in rows if r["security"] == "600519.XSHG" and r["quarter"] == "2019q4"
               and r["info_date"][:10] == expected["published"]]
    total_match = bool(matched) and all(Decimal(str(r["total_shares"])) == Decimal(str(expected["total"])) for r in matched)
    a_match = bool(matched) and all(Decimal(str(r["total_a_shares"])) == Decimal(str(expected["a"])) for r in matched)
    pages = (root / "work/m10_activation/alternative_moutai_original_01.txt").read_text(encoding="utf-8").split("\f")
    normalized = re.sub(r"\s+", "", pages[1]).replace(",", "")
    pdf_amount_matches = str(Decimal(str(expected["total"])) / Decimal(10000)) in normalized
    ordinary_no_change = "普通股股份总数及股本结构未发生变化" in re.sub(r"\s+", "", pages[33])
    output = dict(scope="LIMITED_PIT_SHARE_ANCHOR_NOT_DAILY_EVENT_CHAIN",
        response_hash_match=hashlib.sha256((sample / "raw.json").read_bytes()).hexdigest() == receipt["source_payload_hash"],
        official_pdf_hash_match=hashlib.sha256(Path(source["local_path"]).read_bytes()).hexdigest() == source["expected_sha256"],
        rows=len(rows), security_count=len({r["security"] for r in rows}),
        all_info_dates_within_explicit_cutoff=all(r["info_date"][:10] <= "2020-07-31" for r in rows),
        field_non_null_counts={c: sum(r[c] is not None for r in rows) for c in payload["columns"]},
        row_coverage=[dict(security=r["security"], quarter=r["quarter"], info_date=r["info_date"][:10],
                          total_shares_present=r["total_shares"] is not None,
                          total_a_shares_present=r["total_a_shares"] is not None) for r in rows],
        moutai_2019q4=dict(original_info_date=expected["published"], total_shares_matches_original=total_match,
                          a_shares_matches_original=a_match, original_page2_share_unit_token_matches=pdf_amount_matches,
                          original_page34_ordinary_shares_no_change_in_2019=ordinary_no_change,
                          author_visually_checked_physical_pages=[2, 5, 34],
                          source_publication_basis="Prior recorded official publication metadata; this turn rechecks PDF identity/contents, not publication page",
                          availability_basis="Existing date-only rule yields 2020-04-23T21:00:00+08:00; not vendor-first-seen evidence"),
        alternative_path="PIT_SHARE_ANCHOR_ACTUALLY_RETURNED_AND_ONE_ORIGINAL_MATCHED",
        unverified=["other four issuers share-class/unit originals", "all preferred/treasury treatment and quantities",
            "all necessary share-changing events between anchors", "historical per-field revision and event prefix invariance",
            "full-pool share chain", "industry publication and classification transitions"],
        no_null_filled_with_zero=True, quarterly_missing_shares_not_filled=True,
        raw_vendor_values_published=False, full_sample_admission=False, complete_cards=0,
        human_acceptances=0, actual_r2_accounts=0, performance_metrics=None)
    assert output["response_hash_match"] and output["official_pdf_hash_match"]
    assert output["all_info_dates_within_explicit_cutoff"]
    assert total_match and a_match and pdf_amount_matches and ordinary_no_change
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = check(Path(args.root).resolve())
    with Path(args.output).open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(dict(rows=result["rows"], securities=result["security_count"],
        original_anchor_match=True, full_sample_admission=False)))
