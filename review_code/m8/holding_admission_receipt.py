"""Issue only the completed independent full-holding scope, never all-cash waiver."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
from independent_accounts import ROOT,read,sha,load_stage
from independent_signals import calculate

STAGE=ROOT/"data/m8_rotation/stage_v1"
report=ROOT/"reports/m8_review"
manifest=read(STAGE/"manifest.json")
source=load_stage(STAGE)
selection=read(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")
assert sha(STAGE/"manifest.json")=="2c21eb27ed214a07cc9062b1db87934d201ba2b7c2a60104b1a85c05a7ca1c15"
assert manifest["cohort_selection_sha256"]==sha(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")
assert read(report/"independent_holding_stage.json")["decision"]=="PASS_NORMALIZED_HOLDING_DATA_RAW_AND_TR"
assert read(report/"independent_holding_stage.json")["stage_manifest_sha256"]==sha(STAGE/"manifest.json")
assert read(report/"independent_action_documents.json")["decision"]=="PASS_ORIGINAL_ACTION_TERMS_AND_ANNUAL_COMPLETENESS"
assert read(report/"independent_holding_lifecycle.json")["decision"]=="PASS_BOUNDED_HOLDING_LIFECYCLE"
assert read(report/"independent_holding_rules.json")["policy_sha256"]==sha(ROOT/"reports/m8_rotation/HOLDING_RULE_POLICY.json")
products={r["instrument_id"]:r["product_evidence"] for r in selection["ETF_candidate_rows"]}
assert len(source["instruments"])==11 and {r["instrument_id"] for r in source["instruments"]}==set(selection["selected_instruments"])
for row in source["instruments"]:
    assert row["vendor_first_seen_at"] is None and row["actual_broker_permission_observed"] is False
    assert row["account_permission_basis"]=="HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT"
    assert row["status"]=="NORMAL" and row["benchmark_id"]==products[row["instrument_id"]]["exact_index_id"]
    if row["supersedes_id"] is None:
        product=products[row["instrument_id"]]
        assert row["available_at"]==max(product["available_at"],product.get("index_contract_available_at",product["available_at"]))
    else:
        assert row["instrument_id"]=="sh.512760" and row["effective_from"]=="2020-06-16"
        assert row["available_at"]=="2020-06-12T21:00:00+08:00"
opportunities=calculate(source,selection,"E0",1,"2020-01-01","2024-12-31")
registered=manifest["liquid_dependencies"]["schedule"]
assert len(opportunities)==len(registered)==60
for expected,actual in zip(opportunities,registered):
    assert expected["anchor"]==actual["anchor_date"] and expected["eligible"]==actual["eligible"]
    assert expected["eligible_count"]==actual["eligible_count"] and expected["execution"]==actual["execution_date"]
opportunity_summary=dict(decision="PASS_INDEPENDENT_PRE_ACCOUNT_QUALIFICATION",stage_manifest_sha256=sha(STAGE/"manifest.json"),
    scheduled_anchors=60,preformation_cash_anchors=1,N_ge4_anchors=sum(len(x["eligible"])>=4 for x in opportunities),
    trend_on_anchors=sum(x["trend"] is True for x in opportunities),all10_competitors_in_scope=True,
    account_returns_read=False,ledger_accounts_run=0,method="Independent Decimal monthly20 median and original listing-calendar age252; all N>=3 competitors have complete raw-action TR.")
(report/"independent_pre_account_qualification.json").write_text(json.dumps(opportunity_summary,indent=2)+"\n",encoding="utf-8")
evidence_names=["FORMATION_INDEPENDENT_REVIEW.json","independent_raw_bars.json","independent_holding_stage.json",
    "independent_action_documents.json","independent_holding_lifecycle.json","independent_holding_rules.json",
    "benchmark_calendar_source_review.json","holding_title_archive_review.json","independent_pre_account_qualification.json"]
evidence_files={"reports/m8_review/"+name:sha(report/name) for name in evidence_names}
for path,digest in read(report/"independent_holding_rules.json")["license_source_hashes"].items(): evidence_files[path]=digest
gates={
    "source":["independent_raw_bars.json","independent_holding_stage.json"],
    "license":["independent_holding_rules.json"],
    "calendar":["benchmark_calendar_source_review.json"],
    "historical_coverage":["independent_raw_bars.json","independent_pre_account_qualification.json"],
    "point_in_time":["independent_holding_stage.json","benchmark_calendar_source_review.json","independent_holding_lifecycle.json"],
    "lifecycle":["independent_holding_lifecycle.json","holding_title_archive_review.json"],
    "corporate_actions":["independent_action_documents.json","independent_holding_stage.json"],
    "total_return":["independent_holding_stage.json"],
    "historical_rules":["independent_holding_rules.json"],
    "historical_fees":["independent_holding_rules.json"],
    "account_permissions":["independent_holding_rules.json"],
    "dual_source_reconciliation":["independent_holding_stage.json"]}
now=datetime.now(timezone.utc).isoformat()
output=dict(schema_version=1,decision="ADMIT_DAILY_SCREEN",author_role="INDEPENDENT_REVIEWER",reviewer="/root/m8_independent",
    reviewed_at=now,research_scope="R1I_HISTORICAL_LIQUID_V1",admission_scope="FULL_HOLDING_DEPENDENCIES",
    stage_manifest_sha256=sha(STAGE/"manifest.json"),evidence_files=evidence_files,
    evidence_gates={key:dict(status="VERIFIED",reviewer="/root/m8_independent",reviewed_at=now,evidence=["reports/m8_review/"+n for n in names]) for key,names in gates.items()},
    qualifications=[
        "All10 formed competitors:13,737 raw bars, five source-confirmed economic events,60 annual fund-year action proofs, full raw-action proportional TR. No M7 all-cash or null-TR waiver.",
        "Historical public as-of reconstruction, not vendor vintage. Unknown first-seen timestamps remain null. Market-close21:00 and benchmark next-exchange-session21:00 are labeled conservative research clocks.",
        "Calendar comes from actual BaoStock exchange-session query, corroborated by CSI membership; it is not represented as an exchange-issued primary calendar. Pre2019 calendar proves listing age only; fixed2019 prices cover every registered warmup.",
        "2024 annual reports published2025 are retrospective action-completeness evidence only. Exact historical plans, not annual publication backfill, supply event terms and clocks. No2025–26 market/factor/strategy observations admitted.",
        "Ordinary domestic equity ETF account and3bp/min5 commission are hypothetical research scenarios. ETF statutory stock-tax and stock-transfer nonapplication is source-scoped; SSE stamp exclusion is an explicit national-law scope inference, not a direct SSE-specific exemption claim.",
        "Announced cash-dividend dates are rule-based designated-broker credit simulation, not observed investor receipts. No actual user broker permissions inferred.",
        "Ordinary10% limits follow historical sector-index product scope and closed lifecycle evidence, not a certified per-day constituent matrix or exchange product-limit feed; source conflicts would block.",
        "Private local noncommercial research only; no raw-data redistribution or commercial/live license asserted. Tencent OHLC only corroborates primary raw prices; primary share/CNY units are separately validated.",
        "This is source admission only. Eight real base accounts still require independent source-based accounting gate before registered24 stress paths; profitability is never the gate."],
    reviewed_counts=dict(bars=13737,actions=5,master_revisions=11,benchmark=3643,source_snapshot_files=544),
    production_edits_by_reviewer=0,new_network_requests_by_reviewer=0)
(report/"HOLDING_ADMISSION.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(output["decision"],output["admission_scope"],output["stage_manifest_sha256"])
