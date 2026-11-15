"""Create the documentary R1 build overlay; this never admits a dataset.

Run from the repository root. Inputs are versioned explicitly, local evidence is
hash checked, and output is deterministic for the same source bytes. No network
access, market corrections, strategy runs, or retrospective broker observations.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.settlement import RULE_MODE, rule_errors

COLLECTION = "data/raw_r1_universe/r1_2010_2024"
MASTER = "data/raw_r1_actions/listing_110/master_records.json"
MASTER_SHA = "745fa808b5e7b5ab64bf75d8b8a1e3f1b8843a2b8329cc81e169e7338bf23487"
EVENTS = "reports/real_data_phase3/event_manifest.json"
BENCHMARK = "data/normalized_csi/h00300_2010_2024_v1"
POLICY_EVIDENCE = "reports/real_data_phase3/policy_evidence.json"
START_EVIDENCE = "work/policy_rule_probe/szse_start_20200814.json"
CALENDAR_EVIDENCE = "reports/real_data_phase3/availability_calendar_boundary.json"
SZ_SETTLEMENT_CAPTURE = "data/raw_policy/sz_settlement/fetch_manifest_cf314812a6cccbbea41a12741adf2a98ae1de94bcf2b9975219d710e7485d6cd.json"
SZ_SETTLEMENT_EVIDENCE = "reports/real_data_phase3/sz_settlement_evidence.json"


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def previous_day(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def build_policy():
    evidence = {}

    def bind(path, expected=None):
        path = Path(path).as_posix()
        actual = digest(path)
        if expected and actual != expected:
            raise ValueError("Source hash mismatch: " + path)
        evidence[path] = actual
        return actual

    bind(MASTER, MASTER_SHA)
    master = read_json(MASTER)
    documentary = read_json(COLLECTION + "/documentary_manifest_v6.json")
    for field in ("candidates", "inventory"):
        bind(COLLECTION + "/" + documentary[field + "_path"], documentary[field + "_sha256"])
    for path in (COLLECTION + "/documentary_manifest_v6.json", COLLECTION + "/provisional_dependencies_v6.json",
                 POLICY_EVIDENCE, EVENTS, CALENDAR_EVIDENCE, START_EVIDENCE, BENCHMARK + "/manifest.json",
                 SZ_SETTLEMENT_CAPTURE, SZ_SETTLEMENT_EVIDENCE, "data/raw_csi/h00300_2010_2024_v1/manifest.json"):
        bind(path)
    sz_review = read_json(SZ_SETTLEMENT_EVIDENCE)
    for source in sz_review["sources"]:
        if source.get("evidence_use") != "NOT_EVIDENCE_REDIRECTED_TO_CURRENT_HOMEPAGE":
            bind(source["local_path"], source["sha256"])
            if source.get("fetch_manifest_path"):
                bind(source["fetch_manifest_path"], source["fetch_manifest_sha256"])
    calendar_evidence = read_json(CALENDAR_EVIDENCE)
    bind(calendar_evidence["raw_path"], calendar_evidence["sha256"])
    benchmark_manifest = read_json(BENCHMARK + "/manifest.json")
    for path, expected in benchmark_manifest["files"].items():
        bind(BENCHMARK + "/" + path, expected)
    sessions = [row["date"] for row in read_json(BENCHMARK + "/observations.json")["records"]]
    availability_sessions = sorted(set(sessions + calendar_evidence["additional_sessions"]))

    def available_after(day):
        return availability_sessions[bisect_right(availability_sessions, day)] + "T21:00:00+08:00"

    sources = {s["source_id"]: s for s in read_json(POLICY_EVIDENCE)["sources"]}
    sources["szse_start_20200814"] = read_json(START_EVIDENCE)
    sz_settlement = next(s for s in read_json(SZ_SETTLEMENT_CAPTURE) if s["source_id"] == "chinaclear_sz_etf_2022")
    sources["chinaclear_sz_etf_2022"] = dict(sz_settlement,
        local_path="data/raw_policy/sz_settlement/" + sz_settlement["raw_path"],
        publication_date=sz_review["applicable_rule"]["published_on"],
        available_at=sz_review["applicable_rule"]["available_at_under_project_policy"],
        effective_from=sz_review["applicable_rule"]["effective_from"],
        effective_to=previous_day(sz_review["applicable_rule"]["effective_to_exclusive"]),
        documentary_identity="ChinaClear Shenzhen2022-12 guide, notice73; archived2024URL is not original publication date")
    used_ids = ["sse_rules_2014", "szse_rules_2013", "szse_rules_2016_notice", "szse_rules_2016",
                "sse_rules_2020_notice", "sse_rules_2020", "sse_20pct_2020",
                "szse_rules_2023_archive", "szse_20pct_list_20200824", "szse_start_20200814",
                "sse_rules_2023", "sse_rules_2023_full", "szse_rules_2023_notice", "szse_rules_2023_full",
                "baostock_help_home", "baostock_revisions", "csi_disclaimer_script", "csi_method_2023",
                "chinaclear_sz_etf_2022"]
    for key in used_ids:
        bind(sources[key]["local_path"], sources[key]["sha256"])

    captures = {}
    for source_root in sorted({r["source_root"] for r in master}):
        for path in sorted((ROOT / source_root / "captures").glob("*.json")):
            capture = json.loads(path.read_text(encoding="utf-8"))
            if capture.get("sha256") and capture.get("fetched_at"):
                captures[capture["sha256"]] = (capture["fetched_at"], path.relative_to(ROOT).as_posix())

    records, by_sid = [], defaultdict(list)
    for original in master:
        row = dict(original)
        captured = []
        for path_key, hash_key in [("source_path", "raw_object_hash"), ("benchmark_source_path", "benchmark_source_hash")]:
            if path_key == "benchmark_source_path" and not (ROOT / row["source_root"] / row[path_key]).is_file():
                # Later delisting records inherit original benchmark evidence
                # from the listing collection, not from the delisting capture.
                original_path = ROOT / "data/raw_r1_actions/listing_110/raw" / (row[hash_key] + ".bin")
                row[path_key] = Path(os.path.relpath(original_path, ROOT / row["source_root"])).as_posix()
            bind(str(Path(row["source_root"]) / row[path_key]), row[hash_key])
            if row[hash_key] not in captures:
                raise ValueError("Original source lacks an actual capture timestamp: " + row[hash_key])
            fetched_at, capture_path = captures[row[hash_key]]
            captured.append(fetched_at)
            bind(capture_path)
        if row["benchmark_source_available_at"] > row["available_at"]:
            raise ValueError("Benchmark evidence postdates declared master availability: " + row["instrument_id"])
        row.update(asset_type="ETF", board="ETF", industry="BROAD_MARKET", status="NORMAL",
                   lot_size=100, tick_size=0.001, t_plus=1,
                   account_verified=True, actual_broker_permission_observed=False,
                   account_permission_basis="HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT",
                   historical_metadata_verified=True, availability_mode="historical_public_asof",
                   source="Official original listing/prospectus/conversion/delisting notice",
                   endpoint=row["source_url"], source_record_id=row["revision_id"],
                   vendor_first_seen_at=None, ingested_at=max(captured), processed_at=max(captured),
                   quality_status="provisional", license_profile_id="PRIVATE_LOCAL_NONCOMMERCIAL_RESEARCH_ONLY",
                   trading_attribute_basis="ORIGINAL_DOMESTIC_EQUITY_ETF_IDENTITY_AND_DATED_EXCHANGE_RULES")
        records.append(row)
        by_sid[row["instrument_id"]].append(row)
    if len(by_sid) != documentary["candidate_count"]:
        raise ValueError("Original master and documentary candidate counts differ")

    # These are exchange-rule terms, not observations of a particular account.
    # Later versions corroborate unchanged ordinary terms; they are never the
    # evidence timestamp for an earlier period. All effective-price regimes are
    # split at the date when the operative 10/20 percent limit actually changes.
    rules = []
    for sid, versions in sorted(by_sid.items()):
        versions.sort(key=lambda r: (r["effective_from"], r["available_at"]))
        identity_changes = []
        for row in versions:
            if not identity_changes or row["benchmark_id"] != identity_changes[-1]["benchmark_id"]:
                identity_changes.append(row)
        listed = versions[0]["listed_on"]
        final_day = min(["2024-12-31"] + [previous_day(r["delisted_on"]) for r in versions if r.get("delisted_on")])
        exchange = sid[:2]
        boundary = "2020-08-21" if exchange == "sh" else "2020-08-24"
        breakpoints = {max("2016-01-01", listed), boundary, "2023-04-10"}
        if exchange == "sh":
            breakpoints.add("2020-03-17")  # Same unchanged terms; new text is conservatively known.
        else:
            breakpoints.add("2016-05-09")
        breakpoints.update(r["effective_from"] for r in identity_changes)
        breakpoints = sorted(x for x in breakpoints if max("2016-01-01", listed) <= x <= final_day)
        for index, begin in enumerate(breakpoints):
            end = previous_day(breakpoints[index + 1]) if index + 1 < len(breakpoints) else final_day
            identity = max((r for r in identity_changes if r["effective_from"] <= begin), key=lambda r: r["effective_from"])
            qualifying = identity["benchmark_id"].startswith(("CHINEXT", "STAR"))
            ratio = 0.2 if qualifying and begin >= boundary else 0.1
            general = "sse_rules_2014" if exchange == "sh" else "szse_rules_2013"
            general_day = "2014-09-26" if exchange == "sh" else "2013-11-30"
            if exchange == "sh" and begin >= "2020-03-17":
                general, general_day = "sse_rules_2020", "2020-03-13"
            if exchange == "sz" and begin >= "2016-05-09":
                general, general_day = "szse_rules_2016", "2016-04-28"
            if begin >= "2023-04-10":
                general, general_day = ("sse_rules_2023_full" if exchange == "sh" else "szse_rules_2023_full"), "2023-02-17"
            decisive = [general]
            known = available_after(general_day)
            if ratio == 0.2 and begin < "2023-04-10":
                decisive += ["sse_20pct_2020"] if exchange == "sh" else ["szse_rules_2023_archive", "szse_start_20200814"]
                known = max(known, available_after("2020-08-21" if exchange == "sh" else "2020-08-14"))
            known = max(known, identity["benchmark_source_available_at"])
            if known >= begin + "T09:30:00+08:00":
                raise ValueError("Rule not known at regime's first open: " + sid + " " + begin)
            rule_id = sid + "_" + begin + "_" + str(int(ratio * 100)) + "PCT"
            rules.append(dict(rule_id=rule_id, instrument_id=sid, benchmark_id=identity["benchmark_id"],
                effective_from=begin, effective_to=end, available_at=known,
                limit_ratio=ratio, lot_size=100, tick_size=0.001, t_plus=1,
                source_url=sources[decisive[-1]]["url"], source_ids=decisive,
                source_hashes=[sources[k]["sha256"] for k in decisive],
                identity_source_hash=identity["benchmark_source_hash"],
                first_listing_day_included=True, limit_reference="PROVIDER_PRECLOSE_EX_RIGHTS_REFERENCE",
                price_rounding="DECIMAL_ROUND_HALF_UP_TO_0.001",
                scope="DOMESTIC_EQUITY_ETF_SECONDARY_MARKET_ONLY"))

    events = read_json(EVENTS)
    overrides, blockers = {}, []
    for action in events["canonical_actions"]:
        if action.get("type", action.get("action_type")) not in ("DIVIDEND", "CASH_DIVIDEND"):
            continue
        if action["instrument_id"] == "sh.512320":
            continue
        proofs = [p for p in action.get("settlement_notice_evidence", [])
                  if p.get("account_type") == "DESIGNATED_BROKER_ORDINARY_ETF_HOLDER"
                  and p.get("pdf_page") and p.get("statement")]
        if action["action_id"] == "sz.159922_DIV_2024-12-02":
            # Issuer's Dec3 is a custodial transfer, never a broker cash receipt.
            # Guide3.3.1.4: R+2 closing clearing, next session transfer to
            # participants. One further session is a prespecified model lag.
            guide = sources["chinaclear_sz_etf_2022"]
            record_index = sessions.index(action["record_date"])
            participant, modeled = sessions[record_index + 3], sessions[record_index + 4]
            pay = action["scheduled_pay_date"]
            overlay = dict(settlement_mode=RULE_MODE, actual_pay_date=None, scheduled_pay_date=pay,
                settlement_account_type="HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT",
                settlement_rule_verified=True, settlement_rule_event_types=["CASH_DIVIDEND"],
                settlement_rule_source_url=guide["url"], settlement_rule_source_hash=guide["sha256"],
                settlement_rule_available_at=guide["available_at"],
                settlement_rule_effective_from=guide["effective_from"], settlement_rule_effective_to=guide["effective_to"],
                settlement_rule_id="CHINACLEAR_SZ_2022_3.3.1.4_WITH_MODELED_INVESTOR_LAG",
                settlement_rule_credit_basis="NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER",
                participant_transfer_date=participant, modeled_cash_date=modeled,
                participant_transfer_date_kind="RULE_SCHEDULE_CONDITIONAL_ON_TIMELY_FULL_FUNDING_NOT_OBSERVED_TRANSACTION",
                settlement_model_assumption=sz_review["event_application"]["model_assumption"],
                settlement_model_limit=sz_review["event_application"]["model_limit"],
                settlement_rule_evidence=[dict(pdf_page=29, printed_page=21, clause="3.3.1.4",
                    rule="R+2 11:00 prefunding; R+2 EOD clearing; next session transfer to participants",
                    investor_credit_model="One additional exchange session after participant transfer; not a verified receipt")],
                actual_account_receipt_observed=False)
            errors = rule_errors(dict(action, **overlay, action_type="CASH_DIVIDEND", pay_date=pay))
            if errors:
                raise ValueError(action["action_id"] + ": " + "; ".join(errors))
            overrides[action["action_id"]] = overlay
            continue
        if not proofs:
            blockers.append(dict(scope=action["action_id"], reason="INVESTOR_CASH_DAY_DOCUMENTARY_RULE_REQUIRED"))
            continue
        pay = action["scheduled_pay_date"]
        overlay = dict(settlement_mode=RULE_MODE, actual_pay_date=None, scheduled_pay_date=pay,
            settlement_account_type="HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT",
            settlement_rule_verified=True, settlement_rule_event_types=["CASH_DIVIDEND"],
            settlement_rule_source_url=action["source_url"], settlement_rule_source_hash=action["source_sha256"],
            settlement_rule_available_at=action["available_at"],
            settlement_rule_effective_from=action["announcement_date"], settlement_rule_effective_to=pay,
            settlement_rule_id=action["action_id"] + "_ISSUER_DESIGNATED_BROKER_CASH_DAY",
            settlement_rule_evidence=proofs, actual_account_receipt_observed=False)
        errors = rule_errors(dict(action, **overlay, action_type="CASH_DIVIDEND", pay_date=pay))
        if errors:
            raise ValueError(action["action_id"] + ": " + "; ".join(errors))
        overrides[action["action_id"]] = overlay

    declared_union = read_json(COLLECTION + "/provisional_dependencies_v6.json")["required_full_history_instruments"]
    waivers, full_history = [], []
    for sid in declared_union:
        listed = by_sid[sid][0]["listed_on"]
        age = sum(listed <= day <= "2024-12-31" for day in sessions)
        if age < 252:
            waivers.append(dict(instrument_id=sid, reason="NEVER_REACHES_252_LISTED_SESSIONS",
                listed_on=listed, observed_exchange_sessions=age, minimum_sessions=252,
                retained_in_representative_selection=True, retained_in_inventory=True,
                performance_inspected=False, independent_dependency_audit_required=True))
        else:
            full_history.append(sid)
    market = dict(mode="historical_public_asof", available_clock="21:00:00",
        publication_precision="reconstructed_market_close", vendor_first_seen_at=None,
        reconstruction_basis="EXCHANGE_SCHEDULED_CLOSE_D15_RECONSTRUCTED_PUBLIC_ASOF_D21_NOT_VENDOR_VINTAGE",
        source_url=sources["sse_rules_2014"]["url"])
    benchmark = dict(mode="historical_public_asof", available_clock="21:00:00",
        publication_precision="date_only", published_at_template="{date}", vendor_first_seen_at=None,
        reconstruction_basis="DATED_CSI_DAILY_TOTAL_RETURN_OBSERVATION_NEXT_EXCHANGE_SESSION_21_CLOCK_UNKNOWN",
        source_url=benchmark_manifest["source_endpoint"])
    policy = dict(schema_version="r1-build-policy-1.0", policy_version="documentary-v6",
        status="STAGING_PENDING_INDEPENDENT_REVIEW", synthetic=False, strategy_runs_permitted=False,
        returns_inspected=False, historical_vintage_claimed=False,
        candidates_file="candidates_documentary_v6.json", inventory_file="inventory_documentary_v6.json",
        documentary_manifest_file="documentary_manifest_v6.json", instrument_records=records,
        account_scenario=dict(label="HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT",
            account_type="HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT", actual_broker_check=False,
            product_qualified_instruments=sorted(by_sid), secondary_market_only=True,
            direct_stock_board_permissions=dict(MAIN=True, CHINEXT=True, STAR=False, BSE=False),
            etf_permission_independent_of_constituent_stock_board=True,
            authorization_basis="USER_ORDINARY_A_SHARE_ACCOUNT_RESEARCH_SCENARIO",
            qualification_basis="ORIGINAL_OFFICIAL_DOMESTIC_EQUITY_ETF_PRODUCT_IDENTITIES"),
        historical_rules=rules, rule_sources={key: sources[key] for key in used_ids},
        market_availability=market, benchmark_availability=benchmark,
        benchmark_ingested_at=read_json("data/raw_csi/h00300_2010_2024_v1/manifest.json")["ingested_at"],
        availability_extra_sessions=calendar_evidence["additional_sessions"],
        availability_calendar_evidence=calendar_evidence, signal_release_delay=1,
        representative_union=declared_union, required_full_history_instruments=full_history,
        dependency_scope_waivers=waivers, action_overrides=overrides, policy_blockers=blockers,
        execution_limit_coverage_start="2016-01-01", tr_coverage_start="2015-01-01", account_start="2016-01-01",
        license_profile_id="PRIVATE_LOCAL_NONCOMMERCIAL_RESEARCH_ONLY",
        source_use=dict(public_raw_redistribution=False, commercial_license_claimed=False,
                        local_noncommercial_analysis_only=True),
        cost_scenario=dict(commission_rate=0.0003, minimum_commission_cny=5,
            commission_basis="COUNTERFACTUAL_RESEARCH_SCENARIO_NOT_HISTORICAL_BROKER_INVOICE",
            minimum_applies_per_actual_order=True, etf_stamp_duty_rate=0, etf_stock_transfer_fee_rate=0,
            hidden_corporate_action_charges_assumed=False, historical_broker_cost_verified=False),
        evidence_gates_status="PENDING_INDEPENDENT_REVIEW",
        source_evidence_files=[dict(path=p, sha256=h) for p, h in sorted(evidence.items())])
    return policy


def rule_mapping(policy):
    count = len(policy["account_scenario"]["product_qualified_instruments"])
    gaps = "\n".join("- `" + x["scope"] + "`: " + x["reason"] for x in policy["policy_blockers"]) or "- None identified by this generator; independent admission remains pending."
    return f"""# R1 documentary rule mapping

Status: **STAGING / PENDING INDEPENDENT REVIEW**. This policy admits no dataset and reports no returns.

Generate with `.venv/Scripts/python.exe scripts/create_r1_build_policy.py`. The generator uses fixed v6 inventory/candidate names, checks the frozen 117-row master SHA256, checks every referenced raw source, and records source hashes in `configs/r1_build_policy.json`. Re-running against identical inputs produces identical output. New event evidence requires regeneration and review.

The master contains {count} funds and {len(policy['instrument_records'])} dated identity revisions, including 159908's 2018 index conversion and six later delisting announcements. Original prospectus/index evidence stays separate from retrospective completeness reports. Historical availability is reconstructed from publication dates; source ingestion uses actual capture timestamps.

| Rule | Mapping and evidence |
|---|---|
| Account | Hypothetical ordinary A-share designated account, domestic equity ETF secondary trading. `account_verified` is a scenario mask, with `actual_broker_permission_observed=false`. MAIN/CHINEXT direct-stock authorization is separate from STAR/BSE direct-stock denial and ETF qualification. |
| Buy lot / tick / sellability | 100 units / CNY0.001 / next-session sellability for secondary-market domestic equity ETF buys. Original product documents and SSE2014/SZ2013 general rules support this scope; dated later texts corroborate unchanged terms. Primary-market creation/redemption and cross-border/bond/cash ETFs are outside this mapping. |
| Ordinary limit | 10%, including ordinary ETF first listing day. Historical exchange texts are attached by source hash; stock IPO exceptions are not applied to ETFs. |
| Qualifying index ETF limit | 20% for indices comprising STAR/ChiNext or other20%-limit shares, SSE from2020-08-21, SZ from2020-08-24. Product identity is dated. Original SZ2020-06-12 special rules plus Aug14 launch announcement are decisive before Aug24; Aug21 list corroborates159915/159949 and is not backdated. SSE's first relevant ETF listing is later than its rule availability. |
| Rule revisions | SSE2020 text is used once conservatively known (Mar17; unchanged ordinary terms bridge Mar13–16); SZ2016 fromMay9. 2023 rules are used only fromApr10. No2023 document is treated as a2020 publication. |
| Limits rounding | Decimal HALF_UP to0.001 using retained provider `preclose` as ex-rights reference, never a guessed yesterday-close replacement. Required execution coverage starts2016. Null warmup limits are permitted only outside execution dependencies. |
| Ordinary dividends | 17 per-event Shanghai issuer notices support `RULE_BASED_SIMULATION` for the hypothetical designated account. Each issuer rule expires at that event's scheduled payment date; actual receipt remains null. No later ChinaClear guide is backdated. Special512320 liquidation is not assigned ordinary-dividend treatment. |
| Shenzhen159922 cash | Original scheduled issuer transfer remains2024-12-03. Applicable ChinaClear2022 guide3.3.1.4 provides R+2 closing clearing and next-session participant transfer: Dec4, conditional on timely full funding. Explicit modeled investor credit is the following exchange session, Dec5, assuming normal settlement/broker processing. It is neither an observed receipt nor a guaranteed worst-case deadline. Actual receipt remains null. |
| Cash stress | Modeled base cash day and predeclared+1/+3 exchange-session delays remain distinct from observed investor receipts. Broker timing is not proved by an issuer transfer date alone. |
| Market clock | Scheduled session endD15, reconstructed public-asofD21, `published_at=null`, unknown vendor first-seen. This is not an original data-vintage assertion. |
| Benchmark clock | CSI observation is datedD; unknown intraday publication conservatively becomes availableD+1 session21. AnchorD → decisionD+1 → executionD+2; delayed executionD+3. |
| Boundary calendar | Official2024-12-23 holiday notice supplies2025-01-02 solely to timestamp the retained2024-12-31 observation. No2025 price or simulation execution is added. |
| Costs | 3bp/minimumCNY5 per actual order is a counterfactual research commission, not an observed historical broker tariff. ETF stamp/stock-transfer components are zero in this scope. |
| Use rights | Private local noncommercial research only; no public raw redistribution or commercial-license claim. CSI/BaoStock evidence remains hash-bound and subject to independent review. |

The provisional amount-only representative union retains {len(policy['representative_union'])} instruments. Full accounting/feature history currently applies to {len(policy['required_full_history_instruments'])};159573 remains in the selector/inventory, but its247 listed sessions through2024 never meet the predeclared252-session entry age. Its unresolved2023 split-proof gap is retained under the independently checked dependency waiver; no substitute ETF is selected.

Current documentary gaps:

{gaps}

Key official sources: [SSE2014 full rules](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988782.shtml), [SZ2013 full rules](https://docs.static.szse.cn/www/disclosure/notice/W020180328432928783546.pdf), [SZ2020 special rules, original June12 dated text](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf), [Aug14 launch announcement](https://www.szse.cn/aboutus/trends/news/t20200814_580660.html), [Aug24 ETF list](https://docs.static.szse.cn/www/aboutus/trends/news/W020200821764606607644.pdf), [SSE20% notice](https://etf.sse.com.cn/ruleguide/business/c/5287913.shtml). Per-instrument and per-event original URLs, dates, captures, and hashes are in the JSON overlay.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="configs/r1_build_policy.json")
    parser.add_argument("--report", default="reports/real_data_phase3/RULE_MAPPING.md")
    args = parser.parse_args()
    policy = build_policy()
    for path, content in [(args.output, json.dumps(policy, ensure_ascii=False, indent=2) + "\n"),
                          (args.report, rule_mapping(policy))]:
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(json.dumps(dict(output=args.output, sha256=digest(args.output), master_rows=len(policy["instrument_records"]),
        rules=len(policy["historical_rules"]), dividend_rules=len(policy["action_overrides"]),
        full_history=len(policy["required_full_history_instruments"]), blockers=policy["policy_blockers"]), indent=2))


if __name__ == "__main__":
    main()
