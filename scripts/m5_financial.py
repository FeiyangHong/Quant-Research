"""Reproduce two registered documentary engineering cases, offline; never run alpha.

The transcriptions are agent-assisted and deliberately not advertised as a generic
automatic financial parser. Raw page tokens, positions, hashes and manual column
choices remain inspectable; no independent human acceptance is asserted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from decimal import Decimal, localcontext

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.data import date_only_available_at
from quant_research.equity_features import financial_asof, r2_factors

OUT = ROOT / "reports/m5_financial"
FIELD_MAP = {"net_profit_parent": "net_profit_parent_ytd",
             "operating_cash_flow": "operating_cashflow_ytd", "total_assets": "total_assets"}
LABELS = {"net_profit_parent_ytd": "归属于上市公司股东的净利润",
          "operating_cashflow_ytd": "经营活动产生的现金流量净额", "total_assets": "总资产"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def calendar():
    return sorted(set(load(ROOT / "data/admitted_r1/phase2_v1/development/calendar.json")
                      + load(ROOT / "data/admitted_r1/phase2_v1/validation/calendar.json")))


def page_text(path, page):
    result = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
                            check=True, capture_output=True)
    return result.stdout.decode("utf-8", errors="replace")


def make_fact(identity, period, field, value, document, published, page, column,
              revision_id, supersedes=None, table="主要会计数据和财务指标", note=""):
    path = Path(document["raw_path"])
    if digest(path) != document["sha256"]:
        raise ValueError("Raw source hash mismatch: " + str(path))
    text = page_text(path, page)
    token = str(value).replace(",", "")
    if token not in "".join(text.replace(",", "").split()):
        raise ValueError(f"Amount absent from declared physical page: {identity} {period} {field} {page} {token}")
    return dict(instrument_id=identity, period_end=period, field=field, value=token,
        report_scope="consolidated", currency="CNY", source_unit="CNY_yuan", normalized_unit="CNY_yuan",
        source_value=token, source_document_hash=document["sha256"], source_document_path=str(path.relative_to(ROOT)),
        source_url=document["url"], source_page=page, source_table=table, source_row=LABELS[field],
        source_column=column, source_position_basis="physical PDF page (1-based), named table/row/column",
        source_page_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        revision_id=revision_id, supersedes_id=supersedes,
        version_basis="CORRECTION_FILING" if supersedes else "ORIGINAL_FILING",
        published_at=published + "T00:00:00+08:00", publication_precision="date_only",
        available_at=date_only_available_at(published, calendar()),
        extraction_method="AGENT_ASSISTED_TRANSCRIPTION_WITH_PAGE_TOKEN_CHECK",
        independent_human_signoff=False, note=note)


def base_facts():
    records = []
    cards = [load(ROOT / "reports/m4_data/financial_cases" / (case + ".json")) for case in
             ("KANGMEI_2017_ORIGINAL_TO_2019_RESTATEMENT", "sz.002857_2023-09-30")]
    for card in cards:
        km = card["instrument_id"] == "sh.600518"
        for side in ("original", "revision"):
            src = card[side]
            for oldfield, field in FIELD_MAP.items():
                page = (7 if field == "total_assets" else 6) if km and side == "original" else 6 if km else 2 if side == "original" else 4
                if not km and side == "revision" and field == "net_profit_parent_ytd":
                    page = 3
                column = ("2017年末" if field == "total_assets" else "2017年") if km else ("本报告期末" if field == "total_assets" else "年初至报告期末")
                if side == "revision":
                    column += " / 调整后" if km else " / 更正后"
                suffix = ":" + field
                records.append(make_fact(card["instrument_id"], card["period_end"], field, src["values"][oldfield],
                    src["document"], src["published_date"], page, column, src["revision_id"] + suffix,
                    (src["supersedes_id"] + suffix) if src.get("supersedes_id") else None,
                    note=("Unchanged CFO explicitly displayed before on page 3 and after on page 4; same amount is not an inferred carry-forward."
                          if not km and side == "revision" and field == "operating_cashflow_ytd" else "")))
        if km:
            original, revision = card["original"], card["revision"]
            base_id = "KM2016_ASSET_COMPARATIVE_FIRST_OBSERVED_20180426"
            records.append(make_fact(card["instrument_id"], "2016-12-31", "total_assets", "54823896576.81",
                original["document"], original["published_date"], 7, "2016年末", base_id,
                note="First observed unchanged comparison in 2017 original; not backdated to 2016 report publication; full earlier chain unknown."))
            records.append(make_fact(card["instrument_id"], "2016-12-31", "total_assets", "53251762620.05",
                revision["document"], revision["published_date"], 6, "2016年末 / 调整后", "KM2016_ASSET_RESTATED_20190430", base_id))
            for field, value in zip(FIELD_MAP.values(), ("1135188498.44", "-3191529576.31", "74627937566.57")):
                records.append(make_fact(card["instrument_id"], "2018-12-31", field, value, revision["document"],
                    revision["published_date"], 6, "2018年末" if field == "total_assets" else "2018年", "KM2018_ORIGINAL:" + field,
                    note="Later financial report retained; cannot pretend revised 2017 is latest in 2019."))
    return records


def build_facts():
    rows = base_facts()
    extra = OUT / "dependency_transcriptions.json"
    for row in load(extra) if extra.exists() else []:
        rows.append(make_fact(**row))
    return pd.DataFrame(rows)


def numeric_reference(facts, identity, period, at):
    """Independent Decimal expression, only an arithmetic reference for target period.

    This does not choose the factor report period and never replaces r2_factors.
    """
    visible = financial_asof(facts, at, calendar())
    lookup = {(r["field"], r["period_end"]): r for r in visible.to_dict("records") if r["instrument_id"] == identity}
    year, suffix = int(period[:4]), period[4:]
    ends = [period] if suffix == "-12-31" else [period, f"{year-1}-12-31", f"{year-1}{suffix}"]
    required = [(f, e) for f in ("net_profit_parent_ytd", "operating_cashflow_ytd") for e in ends]
    required += [("total_assets", e) for e in (period, f"{year-1}{suffix}")]
    missing = [list(k) for k in required if k not in lookup]
    if missing:
        return {"status": "MISSING_INPUTS", "missing": missing, "target_period": period}
    with localcontext() as ctx:
        ctx.prec = 40
        amounts = {k: Decimal(lookup[k]["value"]) for k in required}
        flows = []
        for f in ("net_profit_parent_ytd", "operating_cashflow_ytd"):
            values = [amounts[f, e] for e in ends]
            flows.append(values[0] if len(values) == 1 else values[0] + values[1] - values[2])
        average = sum(amounts[k] for k in required[-2:]) / Decimal(2)
        return {"status": "ARITHMETIC_REFERENCE_NOT_LATEST_PERIOD_ADMISSION", "target_period": period,
                "profit_ttm": str(flows[0]), "cashflow_ttm": str(flows[1]), "average_assets": str(average),
                "F01": None, "F01_reason": "NO_PROVEN_SAME_DAY_SAME_SHARE_CLASS_MARKET_CAP",
                "F02": str(flows[0] / average), "F03": str(flows[1] / average),
                "inputs": [{"field": k[0], "period_end": k[1], "decimal": str(amounts[k]),
                            "revision_id": lookup[k]["revision_id"], "source_document_hash": lookup[k]["source_document_hash"],
                            "page": lookup[k]["source_page"], "column": lookup[k]["source_column"]} for k in required]}


def human_package():
    packet = OUT / "human_review"
    packet.mkdir(exist_ok=True)
    cards = load(ROOT / "reports/m4_data/financial_vintage_cases.json")["cases"]
    selected = [c for c in cards if c["case_status"] == "COMPLETE_DOCUMENTARY_PAIR"]
    assert len(selected) == 5
    for c in selected:
        wrapped = dict(case=c, agent_documentary_status="M4_INDEPENDENT_AGENT_REVIEW_COMPLETE",
                       human_review={"reviewer": "", "reviewed_at": "", "decision": "", "signature": "", "notes": ""},
                       required_checks=["Original and revised document hashes/pages", "Correct row and YTD/comparison columns",
                                        "Unit, currency, consolidated scope", "Revision chain and publication precision",
                                        "Conservative availability calendar", "Unchanged fields and disclosed scope limits"],
                       human_accepted=False, full_pool_admission=False)
        (packet / (c["case_id"] + ".json")).write_text(json.dumps(wrapped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (packet / "README.md").write_text("# Five M4 documentary pairs: blank human review package\n\n"
        "Agent review is separate from independent human acceptance. All five human signoffs remain blank; accepted count is 0. "
        "Three conflicting M4 cases remain quarantined and are not included as completed pairs. "
        "The two M5 factor cases remain fixed; these five review cards do not add factor cases. "
        "Each card retains absolute raw source paths, SHA256, pages, old/new values, clocks and chain limitations.\n", encoding="utf-8")


def main():
    facts = build_facts()
    write("canonical_facts.json", facts.to_dict("records"))
    facts.to_csv(OUT / "canonical_facts.csv", index=False, encoding="utf-8-sig")
    registration = load(OUT / "registration.json")
    coverage = load(OUT / "report_coverage.json")
    empty_market = pd.DataFrame(columns=["instrument_id", "date", "available_at", "market_cap", "market_cap_scope"])
    results = []
    for case in registration["cases"]:
        identity, at = case["instrument_id"], case["factor_cutoff"]
        contract = pd.DataFrame([r for r in coverage if r["instrument_id"] == identity and r["asof"] == at])
        options = dict(report_coverage=contract)
        before_facts = facts.loc[pd.to_datetime(facts.available_at, utc=True) <= pd.Timestamp(at)]
        before = r2_factors(before_facts, empty_market, at, calendar(), [identity], **options)
        after = r2_factors(facts, empty_market, at, calendar(), [identity], **options)
        pd.testing.assert_frame_equal(before, after)
        later = financial_asof(facts, case["later_fact_cutoff"], calendar())
        selected = later.loc[later.instrument_id.eq(identity) & later.period_end.eq(case["target_period"])]
        later_contract = pd.DataFrame([r for r in coverage if r["instrument_id"] == identity and r["asof"] == case["later_fact_cutoff"]])
        later_factor = r2_factors(facts, empty_market, case["later_fact_cutoff"], calendar(), [identity], report_coverage=later_contract)
        row = after.to_dict("records")[0]
        status = "BLOCKED_NEWER_REPORT_PERIOD" if row["period_end"] != case["target_period"] else "NUMERICAL_ENGINEERING_ONLY_LATEST_COVERAGE_UNVERIFIED" if row["latest_period_status"] == "UNVERIFIED" else "ENGINEERING_ONLY_FORMAL_ADMISSION_BLOCKED"
        results.append(dict(case_id=case["case_id"], status=status, factor=row, historical_prefix_invariant=True,
                            decimal_reference=numeric_reference(facts, identity, case["target_period"], at),
                            later_fact_cutoff=case["later_fact_cutoff"], later_selected_target_facts=selected.to_dict("records"),
                            later_factor_diagnostic=later_factor.to_dict("records")[0]))
    write("factor_cases.json", results)
    human_package()
    write("manifest.json", {"purpose": "ENGINEERING_NOT_STRATEGY_PERFORMANCE", "case_count": 2,
        "main_chain": "financial_asof -> r2_factors", "transcription": "AGENT_ASSISTED_NOT_GENERIC_PARSER",
        "human_accepted_cases": 0, "formal_R2": "BLOCKED_HUMAN_0_FULL_CHAIN_UNKNOWN", "freshness_policy": None,
        "alpha_registrations": 0, "alpha_runs": 0, "facts_count": len(facts),
        "source_hashes": sorted(facts.source_document_hash.unique().tolist()),
        "input_files": {str(p.relative_to(ROOT)): digest(p) for p in [OUT / "registration.json", OUT / "report_coverage.json", OUT / "dependency_transcriptions.json"]},
        "code_files": {str(p.relative_to(ROOT)): digest(p) for p in [Path(__file__), ROOT / "src/quant_research/equity_features.py"]}})
    print(json.dumps({"cases": len(results), "facts": len(facts), "statuses": [r["status"] for r in results]}))


if __name__ == "__main__":
    main()
