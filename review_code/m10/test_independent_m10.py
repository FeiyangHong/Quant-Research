"""Independent fixed-spec and synthetic contract probes; never real performance.

Expected values come from explicit Decimal arithmetic and the handoff, not
production outputs, author fixtures, NAV or expected-account tables.
"""
from copy import deepcopy
from decimal import Decimal
from itertools import product
from pathlib import Path
import json
import importlib.util
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.data import DataValidationError
from quant_research.equity_features import r2_factors

MODE = "A_PRICE_ALL_ISSUED_ORDINARY_SHARES_V1"
CUTOFF = "2024-05-31T21:00:00+08:00"
CALENDAR = ["2024-04-26", "2024-04-29", "2024-04-30", "2024-05-30", "2024-05-31", "2024-06-03"]


def financial_fixture():
    rows = []
    for period, field, value in [
        ("2023-12-31", "net_profit_parent_ytd", "-12"),
        ("2023-12-31", "operating_cashflow_ytd", "36"),
        ("2023-12-31", "total_assets", "140"),
        ("2022-12-31", "total_assets", "100"),
    ]:
        rows.append({"instrument_id": "TOY_AH", "period_end": period, "field": field,
                     "value": value, "report_scope": "consolidated", "currency": "CNY",
                     "revision_id": period + field, "supersedes_id": None,
                     "available_at": "2024-04-29T21:00:00+08:00",
                     "published_at": "2024-04-26T00:00:00+08:00", "publication_precision": "date_only",
                     "version_basis": "ORIGINAL_FILING", "source_document_hash": "a" * 64})
    return pd.DataFrame(rows)


def market_fixture():
    # 60 A + 25 B + 35 H = 120 ordinary shares; all at A reference price 2.5.
    return {"instrument_id": "TOY_AH", "date": "2024-05-31", "available_at": "2024-05-31T20:00:00+08:00",
            "market_cap": "300", "market_cap_scope": "A_PRICE_ALL_ISSUED_ORDINARY_PROXY",
            "valuation_convention": MODE, "price_share_class": "A_ORDINARY", "price_adjustment": "UNADJUSTED",
            "price_currency": "CNY", "shares_unit": "SHARES", "ordinary_share_scope": "ALL_ISSUED_ORDINARY_A_B_H_EX_PREFERRED",
            "ordinary_share_scope_verified": True, "preferred_shares_excluded": True,
            "treasury_share_treatment": "INCLUDED_IF_ISSUED", "price_date": "2024-05-31",
            "price_source_field": "toy.raw_close_cny", "shares_source_field": "toy.issued_ordinary_shares",
            "price_source_sha256": "b" * 64, "shares_source_sha256": "c" * 64,
            "filing_document_hash": None,
            "price_published_at": "2024-05-31T15:01:00+08:00", "price_available_at": "2024-05-31T19:00:00+08:00",
            "price_retrieved_at": "2026-11-16T07:00:00+08:00", "price_publication_precision": "minute",
            "shares_published_at": "2024-05-30T09:00:00+08:00", "shares_available_at": "2024-05-30T10:00:00+08:00",
            "shares_retrieved_at": "2026-11-16T07:00:00+08:00", "shares_publication_precision": "minute",
            "shares_effective_at": "2024-05-31T00:00:00+08:00",
            "unadjusted_A_close": "2.5", "a_shares": "60", "total_ordinary_shares": "120"}


def factors(market=None, *, facts=None, cutoff=CUTOFF, mode=MODE):
    market = [market_fixture()] if market is None else market
    facts = financial_fixture() if facts is None else facts
    return r2_factors(facts, pd.DataFrame(market), cutoff, CALENDAR, ["TOY_AH"], valuation_convention=mode).iloc[0]


def test_ordinary_share_denominator_negative_profit_and_no_admission():
    market = [market_fixture()]
    before = deepcopy(market)
    actual = factors(market)
    expected_cap = Decimal("2.5") * (Decimal("60") + Decimal("25") + Decimal("35"))
    assert expected_cap == Decimal("300")
    assert actual.F01 == pytest.approx(float(Decimal("-12") / expected_cap))
    assert actual.F02 == pytest.approx(float(Decimal("-12") / Decimal("120")))
    assert actual.F03 == pytest.approx(float(Decimal("36") / Decimal("120")))
    assert actual.valuation_cap == float(expected_cap)
    assert actual.all_three_valid
    assert not actual.formal_eligible
    assert "KERNEL_NOT_DATA_ADMISSION" in actual.formal_blockers
    assert market == before and market[0]["filing_document_hash"] is None
    assert market[0]["shares_source_sha256"] != financial_fixture().iloc[0].source_document_hash


@pytest.mark.parametrize("changes", [
    {"total_ordinary_shares": None}, {"total_ordinary_shares": True},
    {"total_ordinary_shares": "119.5", "market_cap": "298.75"},
    {"a_shares": "121"}, {"a_shares": "0"},
    {"total_ordinary_shares": "Infinity"}, {"market_cap": "150"},
    {"shares_unit": "TEN_THOUSAND_SHARES"}, {"preferred_shares_excluded": False},
    {"ordinary_share_scope_verified": None}, {"price_adjustment": "FORWARD_ADJUSTED"},
    {"price_share_class": "H_ORDINARY"}, {"treasury_share_treatment": "UNKNOWN"},
    {"shares_source_field": ""}, {"shares_source_sha256": None},
    {"shares_effective_at": "2024-06-03T00:00:00+08:00"},
    {"shares_published_at": "2024-05-31T21:01:00+08:00"},
    {"shares_available_at": "2024-05-31T21:01:00+08:00"},
    {"shares_retrieved_at": None},
    {"shares_retrieved_at": "2024-05-29T10:00:00+08:00"},
    {"shares_publication_precision": "date_only"},
    {"price_published_at": "2024-05-31T14:59:00+08:00"},
    {"price_published_at": "2024-05-30T15:01:00+08:00"},
    {"price_available_at": "2024-05-31T20:30:00+08:00"},
    {"price_date": "2024-05-30"},
])
def test_unknown_invalid_scope_or_clock_blocks_f01(changes):
    market = market_fixture()
    market.update(changes)
    actual = factors([market])
    assert actual.F01 is None
    assert actual.valuation_cap is None
    assert not actual.all_three_valid and not actual.formal_eligible


def test_future_market_revision_does_not_change_prefix():
    old = market_fixture()
    future = deepcopy(old)
    future.update(available_at="2024-06-03T21:00:00+08:00", market_cap="999999", shares_source_sha256=None)
    assert factors([old, future]).to_dict() == factors([old]).to_dict()


def test_legitimate_date_only_share_clock_and_collection_after_cutoff():
    market = market_fixture()
    market.update(shares_publication_precision="date_only", shares_published_at="2024-05-30T00:00:00+08:00", shares_available_at=CUTOFF, available_at=CUTOFF)
    assert factors([market]).F01 == pytest.approx(-0.04)


def test_legacy_mode_is_explicitly_separate():
    market = {"instrument_id": "TOY_AH", "date": "2024-05-31", "available_at": CUTOFF,
              "market_cap": 150.0, "market_cap_scope": "TOTAL_EQUITY"}
    assert factors([market], mode="LEGACY_TOTAL_EQUITY").F01 == pytest.approx(-0.08)
    actual = factors([market])
    assert actual.F01 is None and not actual.formal_eligible
    with pytest.raises(DataValidationError):
        factors([market], mode="LATEST_REVISED_PROVIDER")


def test_holdout_and_provider_row_disguise_are_rejected():
    with pytest.raises(DataValidationError, match="holdout"):
        factors(cutoff="2025-01-02T21:00:00+08:00")
    facts = financial_fixture()
    facts["version_basis"] = "LATEST_REVISED_PROVIDER"
    with pytest.raises(DataValidationError, match="provider history"):
        factors(facts=facts)


def test_draft_matches_fixed_experiment_and_remains_unrunnable():
    draft = json.loads((ROOT / "reports/m10_r2/EXPERIMENT_REGISTRY.json").read_text(encoding="utf-8"))
    expected = set(product(["development", "validation"], ["VALUE", "QUALITY", "COMBINED"], ["base", "cost_2x", "cost_3x", "delay_1_session"]))
    observed = [(r["period"], r["arm"], r["path"]) for r in draft["experiments"]]
    assert len(observed) == 24 and set(observed) == expected
    assert draft["status"] == "DRAFT_NOT_AUTHORIZED"
    assert draft["real_experiments_registered"] == draft["real_experiments_run"] == 0
    assert draft["performance_metrics"] is None
    assert all(r["status"] == "DRAFT_NOT_AUTHORIZED" and r["actual_run_id"] is None and r["initial_cash_cny"] == 100000 for r in draft["experiments"])
    authorization = draft["authorization"]
    assert not any(authorization[k] for k in ["strategy_runs_permitted", "data_admission", "execution_admission", "whole_pool_period_version_chain_verified"])
    assert authorization["human_approvals_verified"] == 0
    assert all(authorization[k] is None for k in ["actual_code_hash", "actual_data_hash", "actual_rules_hash", "actual_run_registration"])
    assert draft["periods"] == {"development": ["2016-01-01", "2021-12-31"], "validation": ["2022-01-01", "2024-12-31"]}
    assert draft["arms"] == {"VALUE": "Z1", "QUALITY": "(Z2+Z3)/2", "COMBINED": "0.50*Z1+0.25*Z2+0.25*Z3"}
    assert draft["valuation"]["name"] == MODE
    assert draft["portfolio"]["target_count"] == 30 and draft["portfolio"]["retention_rank_at_most"] == 45
    assert draft["portfolio"]["original_PIT_first_level_industry_max_stocks"] == 6
    assert draft["pool"]["size_bottom_fraction_excluded"] == 0.30
    assert draft["pool"]["minimum_listed_trading_sessions"] == 252
    assert draft["pool"]["minimum_median_raw_turnover_cny"] == 30000000
    assert draft["primary"]["candidate"] == "COMBINED" and draft["primary"]["baseline"] == "VALUE"
    assert draft["primary"]["measure"] == "mean_net_daily_return_difference"
    assert draft["bootstrap"]["main_block"] == 60 and draft["bootstrap"]["sensitivity_blocks"] == [20, 120]
    assert draft["bootstrap"]["repetitions"] == 5000 and draft["bootstrap"]["seed"] == 20261114
    assert draft["bootstrap"]["predefined_interval_count"] == 6
    assert not draft["bootstrap"]["stress_CI"] and not draft["bootstrap"]["QUALITY_CI"]
    assert draft["execution"]["stock_slippage_bp_each_side"] == 10
    assert draft["execution"]["commission_bp_each_side"] == 3 and draft["execution"]["minimum_commission_cny"] == 5
    assert draft["execution"]["statutory_rate_stress_multiplier"] == 1
    assert draft["paths"]["cost_2x"]["minimum_commission_multiplier"] == 2
    assert draft["paths"]["cost_3x"]["slippage_multiplier"] == 3
    assert draft["paths"]["delay_1_session"]["additional_execution_delay_sessions"] == 1
    assert draft["scope_limits"]["final_holdout"] == "LOCKED"
    assert draft["scope_limits"]["no_m9_rerun"] and draft["scope_limits"]["stop_after_fixed_24"]


def inspect(registry):
    spec = importlib.util.spec_from_file_location("independent_subject_preflight", ROOT / "scripts/m10_preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inspect_draft(registry, ROOT)


def draft():
    return json.loads((ROOT / "reports/m10_r2/EXPERIMENT_REGISTRY.json").read_text(encoding="utf-8"))


def test_preflight_valid_draft_is_not_run_permission():
    result = inspect(draft())
    assert result["draft_valid"], result["errors"]
    assert result["strategy_runs_permitted"] is False
    assert result["real_accounts_run"] == 0 and result["performance_metrics"] is None
    assert result["status"] == "NOT_RUN_BLOCKED_ADMISSION"


def test_forged_human_and_data_authorizations_never_open_preflight():
    forged = draft()
    forged["status"] = "READY_FOR_HUMAN_REVIEW"
    forged["authorization"].update(strategy_runs_permitted=True, data_admission=True,
                                  execution_admission=True, whole_pool_period_version_chain_verified=True,
                                  human_approvals_verified=20, actual_data_hash="0" * 64)
    result = inspect(forged)
    assert not result["draft_valid"]
    assert result["strategy_runs_permitted"] is False and result["real_accounts_run"] == 0
    assert result["performance_metrics"] is None


def test_wrong_endpoint_period_cost_and_binding_rejected_together():
    changed = draft()
    changed["periods"]["development"][0] = "2020-01-01"
    changed["primary"]["baseline"] = "QUALITY"
    changed["execution"]["stock_slippage_bp_each_side"] = 3
    changed["definition_sources"]["docs/STRATEGY_SPEC.md"] = "0" * 64
    changed["experiments"][0]["actual_run_id"] = "FAKE"
    result = inspect(changed)
    assert not result["draft_valid"] and result["strategy_runs_permitted"] is False
    assert {"PERIODS_CHANGED", "PRIMARY_ENDPOINT_CHANGED", "STOCK_COSTS_CHANGED", "DEFINITION_HASH_CHANGED:docs/STRATEGY_SPEC.md"} <= set(result["errors"])
