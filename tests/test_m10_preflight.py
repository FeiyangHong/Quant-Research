"""No market observations, accounts or human approvals are created here."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_research.equity_features import M10_VALUATION_CONVENTION, r2_factors

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("m10_preflight", ROOT / "scripts/m10_preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def fixture():
    calendar = pd.bdate_range("2019-01-01", "2024-12-31").strftime("%Y-%m-%d").tolist()
    facts = []
    for period, assets, published in (("2019-12-31", 1800, "2020-04-28"), ("2020-12-31", 2000, "2021-04-28")):
        for field, value in (("total_assets", assets), ("net_profit_parent_ytd", 100), ("operating_cashflow_ytd", 150)):
            facts.append(dict(instrument_id="INVENTED_AH", field=field, period_end=period, value=value,
                report_scope="consolidated", currency="CNY", revision_id=period+field, supersedes_id=None,
                available_at=published+"T21:00:00+08:00", published_at=published+"T18:00:00+08:00",
                publication_precision="second", version_basis="ORIGINAL_FILING", source_document_hash="a"*64))
    cap = dict(instrument_id="INVENTED_AH", date="2021-04-30", available_at="2021-04-30T21:00:00+08:00",
        market_cap=1000, market_cap_scope="A_PRICE_ALL_ISSUED_ORDINARY_PROXY", valuation_convention=M10_VALUATION_CONVENTION,
        price_date="2021-04-30", unadjusted_A_close=10, price_share_class="A_ORDINARY", price_adjustment="UNADJUSTED",
        price_currency="CNY", a_shares=80, total_ordinary_shares=100, shares_unit="SHARES",
        ordinary_share_scope="ALL_ISSUED_ORDINARY_A_B_H_EX_PREFERRED", ordinary_share_scope_verified=True,
        preferred_shares_excluded=True, treasury_share_treatment="NO_TREASURY_SHARES",
        shares_effective_at="2020-01-01T00:00:00+08:00")
    for source, published in (("price", "2021-04-30T15:00:00+08:00"), ("shares", "2019-12-31T18:00:00+08:00")):
        cap.update({source+"_source_field": "invented.explicit_field", source+"_source_sha256": "b"*64,
            source+"_published_at": published, source+"_available_at": published,
            source+"_publication_precision": "second", source+"_retrieved_at": "2026-11-16T00:00:00+08:00"})
    return pd.DataFrame(facts), cap, calendar


def compute(facts, market, calendar, **kwargs):
    return r2_factors(facts, pd.DataFrame(market), "2021-04-30T21:00:00+08:00", calendar,
        ["INVENTED_AH"], valuation_convention=M10_VALUATION_CONVENTION, **kwargs)


def test_all_ordinary_reference_price_is_not_venue_summed_or_free_float_and_is_not_admission():
    facts, cap, calendar = fixture()
    row = compute(facts, [cap], calendar).iloc[0]
    assert row.F01 == pytest.approx(.1)
    assert row.valuation_cap == 1000
    assert (row.F02, row.F03) == pytest.approx((100/1900, 150/1900))
    assert row.all_three_valid and not row.formal_eligible
    assert "KERNEL_NOT_DATA_ADMISSION" in row.formal_blockers
    for wrong_cap in (800, 900):
        invalid = compute(facts, [dict(cap, market_cap=wrong_cap)], calendar).iloc[0]
        assert invalid.F01 is None and not invalid.all_three_valid


@pytest.mark.parametrize("change", [
    {"total_ordinary_shares": True}, {"total_ordinary_shares": float("nan")},
    {"total_ordinary_shares": 99.5}, {"a_shares": 101}, {"preferred_shares_excluded": False},
    {"price_adjustment": "FORWARD_ADJUSTED"}, {"shares_unit": "TEN_THOUSAND_SHARES"},
    {"shares_source_sha256": None}, {"shares_source_field": ""},
    {"shares_effective_at": "2021-05-01T00:00:00+08:00"},
    {"shares_available_at": "2021-04-30T21:01:00+08:00"},
    {"shares_published_at": "2020-01-01"},
    {"price_published_at": "2021-04-30T14:00:00+08:00"},
    {"price_publication_precision": "date_only"},
])
def test_invalid_semantics_or_clocks_do_not_make_F01(change):
    facts, cap, calendar = fixture()
    row = compute(facts, [dict(cap, **change)], calendar).iloc[0]
    assert row.F01 is None and not row.all_three_valid
    assert row.F02 == pytest.approx(100/1900)
    assert any(reason.startswith("INVALID_M10_VALUATION:") for reason in row.missing_reasons)


def test_future_cap_revision_does_not_change_past_and_legacy_contract_stays_closed_to_proxy():
    facts, cap, calendar = fixture()
    original = compute(facts, [cap], calendar)
    future = dict(cap, available_at="2021-05-03T21:00:00+08:00", total_ordinary_shares=True)
    pd.testing.assert_frame_equal(original, compute(facts, [cap, future], calendar))
    legacy = r2_factors(facts, pd.DataFrame([cap]), "2021-04-30T21:00:00+08:00", calendar, ["INVENTED_AH"]).iloc[0]
    assert legacy.F01 is None and "INVALID_TOTAL_EQUITY_MARKET_CAP" in legacy.missing_reasons


def test_draft_inspection_never_authorizes_and_rejects_critical_mutations():
    registry = json.loads((ROOT / "reports/m10_r2/EXPERIMENT_REGISTRY.json").read_text(encoding="utf-8"))
    baseline = preflight.inspect_draft(registry, ROOT)
    assert baseline["draft_valid"] and baseline["strategy_runs_permitted"] is False
    for path, value in [(("authorization", "strategy_runs_permitted"), True),
                        (("authorization", "human_approvals_verified"), 20),
                        (("primary", "M9_quadratic_utility"), True),
                        (("execution", "stock_slippage_bp_each_side"), 3),
                        (("bootstrap", "predefined_interval_count"), 12),
                        (("periods", "development"), ["2020-01-01", "2021-12-31"])]:
        changed = deepcopy(registry)
        changed[path[0]][path[1]] = value
        result = preflight.inspect_draft(changed, ROOT)
        assert not result["draft_valid"] and result["strategy_runs_permitted"] is False
    duplicate = deepcopy(registry)
    duplicate["experiments"][-1] = deepcopy(duplicate["experiments"][0])
    assert not preflight.inspect_draft(duplicate, ROOT)["draft_valid"]
