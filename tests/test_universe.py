"""Historical identity discovery must not silently become a current-winner pool."""
import pytest
import pandas as pd

from quant_research.providers.universe import (build_inventory, classify_name, collect_metadata,
                                             quarter_sessions, documented_benchmarks, reconcile_inventory)
from quant_research.providers.universe import provisional_amount_representatives


def test_quarter_end_uses_real_last_session_not_civil_quarter_end():
    days = ["2023-03-30", "2023-03-31", "2023-06-29", "2023-06-30", "2023-09-27", "2023-09-28"]
    assert quarter_sessions(days) == ["2023-03-31", "2023-06-30", "2023-09-28"]


def test_holdout_dates_never_reach_metadata_worker(tmp_path):
    with pytest.raises(ValueError):
        quarter_sessions(["2025-01-02"])
    with pytest.raises(ValueError):
        collect_metadata(tmp_path, "names_asof", None, "2025-01-02")
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("name,category", [
    ("华泰柏瑞沪深300ETF", "CSI300"), ("南方中证500ETF", "CSI500"), ("中证1000ETF", "CSI1000"),
    ("易方达创业板ETF", "CHINEXT"), ("华安创业板50ETF", "CHINEXT50"),
    ("创业板200ETF", "CHINEXT200"), ("创业板300ETF", "CHINEXT300"),
    ("创业板大盘ETF", "CHINEXT_LARGE_CAP"), ("创业板综合ETF", "CHINEXT_COMPOSITE"),
    ("科创板50成份ETF", "STAR50"), ("科创100ETF", "STAR100"), ("科创200ETF", "STAR200"),
    ("中证科创创业50ETF", "STAR_CHINEXT50"), ("双创50ETF", "STAR_CHINEXT50"),
    ("中银证券中证500ETF", "CSI500"), ("中银证券创业板ETF", "CHINEXT"),
    ("红土创新中证500ETF", "CSI500"),
    ("诺安中证500交易型开放式指数证券投资基金", "CSI500"),
])
def test_broad_market_variants_retained_for_exact_index_review(name, category):
    result = classify_name(name)
    assert result["category"] == category
    assert result["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"


@pytest.mark.parametrize("name", ["沪深300非银ETF", "沪深300ESGETF", "中证500增强ETF", "创业板成长ETF", "科创50芯片ETF"])
def test_name_screens_do_not_promote_style_or_sector_to_plain_index(name):
    assert classify_name(name)["classification_status"] == "RELATED_EXCLUDED_OR_REVIEW"


def test_unenumerated_broad_indices_do_not_expand_scope():
    assert classify_name("中证A500ETF")["classification_status"] == "OUTSIDE_NAMED_R1B_GROUPS"
    assert classify_name("上证50ETF")["classification_status"] == "OUTSIDE_NAMED_R1B_GROUPS"


def test_historical_dead_fund_retained_and_current_only_fund_not_backfilled():
    universe = [{"status": "SUCCESS", "fields": ["date", "code"], "rows": [["2014-12-31", "sh.510999"]]}]
    metadata = [
        {"status": "SUCCESS", "kind": "master_all", "date": None,
         "fields": ["code", "code_name", "ipoDate", "outDate"], "rows": [["sh.510888", "新沪深300ETF", "2026-01-01", ""]]},
        {"status": "SUCCESS", "kind": "names_asof", "date": "2014-12-31", "fields": ["code", "tradeStatus", "code_name"],
         "rows": [["sh.510999", "0", "旧沪深300ETF"]]},
    ]
    result = build_inventory(universe, metadata)
    assert [row["code"] for row in result] == ["sh.510999"]
    assert result[0]["current_master"] is None
    assert result[0]["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"
    assert result[0]["account_verified"] is False
    assert result[0]["official_lifecycle_verified"] is False


def test_missing_name_remains_explicit_identity_not_removed():
    result = build_inventory([{"status": "SUCCESS", "fields": ["date", "code"], "rows": [["2020-12-31", "sh.512320"]]}], [])
    assert len(result) == 1
    assert result[0]["classification_status"] == "UNRESOLVED_NAME"


def test_changed_benchmark_name_is_flagged_not_silently_overwritten():
    universe = [{"status": "SUCCESS", "fields": ["date", "code"], "rows": [["2014-12-31", "sh.510999"]]}]
    metadata = [{"status": "SUCCESS", "kind": "names_asof", "date": day, "fields": ["code", "code_name"],
                 "rows": [["sh.510999", name]]} for day, name in [("2014-12-31", "沪深300ETF"), ("2018-12-28", "中证500ETF")]]
    row = build_inventory(universe, metadata)[0]
    assert row["classification_conflict"]
    assert row["name_changed_between_observations"]
    assert len(row["names"]) == 2


@pytest.mark.parametrize("text", ["中证500沪市指数(代码000802)", "中证500深市价格指数", "沪深300非银行金融指数", "沪深300等权重指数"])
def test_exact_disclosed_index_does_not_merge_regional_style_or_sector(text):
    assert documented_benchmarks(text) == []


def test_pdf_repeated_heading_can_interrupt_an_exact_index_name():
    assert documented_benchmarks("标的指数为中证科创业绩比较基准创业50指数") == ["STAR_CHINEXT50"]


def test_retired_official_benchmark_added_without_backdating_disclosure():
    inventory = build_inventory([{"status": "SUCCESS", "fields": ["date", "code"],
                                  "rows": [["2018-12-28", "sh.510520"]]}], [])
    evidence = {"candidate": {"code": "sh.510520"}, "identity_evidence": {
        "name": "诺安中证500交易型开放式指数证券投资基金", "benchmark": "中证500指数收益率",
        "publication_date": "2019-03-27", "listed_on_evidence": "2014-03-10"}}
    row = reconcile_inventory(inventory, [evidence])[0]
    assert row["candidate_for_history_collection"]
    assert row["documented_index_categories"] == ["CSI500"]
    assert row["documented_listing_dates"] == ["2014-03-10"]
    assert row["official_identity_evidence"][0]["publication_date"] == "2019-03-27"
    assert not row["benchmark_evidence_is_historical_effective_interval"]
    assert not row["account_verified"]
    assert "official_identity_evidence" not in inventory[0]


def test_official_out_of_scope_retired_fund_still_preserved_in_inventory():
    inventory = build_inventory([{"status": "SUCCESS", "fields": ["date", "code"],
                                  "rows": [["2018-12-28", "sh.510440"]]}], [])
    evidence = {"candidate": {"code": "sh.510440"}, "identity_evidence": {
        "name": "中证500沪市交易型开放式指数证券投资基金", "benchmark": "中证500沪市指数(代码000802)"}}
    row = reconcile_inventory(inventory, [evidence])[0]
    assert not row["candidate_for_history_collection"]
    assert row["documented_index_categories"] == []
    assert row["code"] == "sh.510440"


def test_final_listing_notice_date_overrides_typo_without_discarding_source():
    inventory = build_inventory([{"status": "SUCCESS", "fields": ["date", "code"],
                                  "rows": [["2018-12-28", "sh.510500"]]}], [])
    records = [{"listed_on": "2012-03-15", "is_final_version": False, "benchmark_id": "CSI500"},
               {"listed_on": "2013-03-15", "is_final_version": True, "benchmark_id": "CSI500"}]
    row = reconcile_inventory(inventory, [{"candidate": {"code": "sh.510500"}, "listing_evidence": records}])[0]
    assert row["documented_listing_dates"] == ["2013-03-15"]
    assert len(row["official_listing_evidence"]) == 2


def amount_fixture():
    days = pd.bdate_range("2020-01-01", "2020-04-01").strftime("%Y-%m-%d").tolist()
    candidates = [{"code": code, "category": "CSI300", "documented_index_categories": ["CSI300"],
                   "documented_listing_dates": [days[0]], "snapshot_dates": ["2020-03-31"]}
                  for code in ["sh.510300", "sh.510330"]]
    histories = {code: [{"date": d, "amount": "20.0001", "suspended": False} for d in days]
                 for code in ["sh.510300", "sh.510330"]}
    return days, candidates, histories


def test_amount_selector_uses_exact_tie_order_and_no_252_monthly_entry_filter():
    days, candidates, histories = amount_fixture()
    result = provisional_amount_representatives(days, candidates, histories)
    assert result["required_full_history_instruments"] == ["sh.510300"]
    assert result["schedule"][-1]["by_exact_index"]["CSI300"]["adv60"] == "20.0001"
    assert not result["depends_on_returns"]


def test_amount_selector_does_not_impute_missing_turnover_or_ignore_suspension():
    days, candidates, histories = amount_fixture()
    histories["sh.510300"][-2]["suspended"] = True
    assert provisional_amount_representatives(days, candidates, histories)["required_full_history_instruments"] == ["sh.510330"]
    histories["sh.510330"][-3]["amount"] = None
    assert provisional_amount_representatives(days, candidates, histories)["required_full_history_instruments"] == []


def test_amount_selector_refuses_partial_histories():
    days, candidates, histories = amount_fixture()
    histories.pop("sh.510330")
    with pytest.raises(ValueError, match="partial histories"):
        provisional_amount_representatives(days, candidates, histories)


def test_amount_selector_refuses_empty_success_history():
    days, candidates, histories = amount_fixture()
    histories["sh.510330"] = []
    with pytest.raises(ValueError, match="Empty history"):
        provisional_amount_representatives(days, candidates, histories)


def test_endpoint_membership_conflict_cannot_be_silently_filtered_out():
    days, candidates, histories = amount_fixture()
    candidates[0]["snapshot_dates"] = []
    result = provisional_amount_representatives(days, candidates, histories)
    assert result["required_full_history_instruments"] == ["sh.510300"]
    assert result["endpoint_membership_conflicts"] == [{"code": "sh.510300", "date": "2020-03-31",
                                                       "reason": "NORMAL_RAW_BAR_ABSENT_ENDPOINT_MEMBERSHIP"}]


def test_original_index_change_uses_effective_date_and_publication_cutoff():
    days, candidates, histories = amount_fixture()
    master = [{"instrument_id": c["code"], "listed_on": days[0], "effective_from": days[0],
               "available_at": "2019-12-30T21:00:00+08:00", "benchmark_id": "CSI300", "strategy_universe": "R1B"}
              for c in candidates]
    master[0]["strategy_universe"] = "OUTSIDE"
    master.append({**master[0], "strategy_universe": "R1B", "effective_from": "2020-04-02",
                   "available_at": "2020-03-20T21:00:00+08:00"})
    assert provisional_amount_representatives(days, candidates, histories, master)["required_full_history_instruments"] == ["sh.510330"]
    master[-1]["effective_from"] = "2020-03-25"
    assert provisional_amount_representatives(days, candidates, histories, master)["required_full_history_instruments"] == ["sh.510300"]
    master[-1]["benchmark_source_available_at"] = "2020-04-02T21:00:00+08:00"
    assert provisional_amount_representatives(days, candidates, histories, master)["required_full_history_instruments"] == ["sh.510330"]
