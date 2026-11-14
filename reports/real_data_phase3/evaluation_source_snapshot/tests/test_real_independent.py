"""Independent adversarial review. All injected records are synthetic fixtures.

These checks do not estimate real returns or promote staging to a Dataset.
"""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data import audit_dataset, synthetic_dataset
from quant_research.execution import ExecutionBlockedError, run_backtest
from quant_research.providers.baostock import BaoStockAdapter, Query, write_immutable
from quant_research.real_data import audit_collection
from test_execution import decision, fixture, liquidation_events
from test_real_data import collection_fixture


def test_independent_partial_calendar_response_cannot_hide_missing_history(tmp_path):
    """An omitted session in both calendar and history must not look complete."""
    response = {"status": "SUCCESS", "fields": ["calendar_date", "is_trading_day"],
                "rows": [["2024-04-01", "1"], ["2024-04-03", "1"]]}
    adapter = BaoStockAdapter(tmp_path, worker=lambda *_: copy.deepcopy(response), min_interval=0)
    result = adapter.collect(Query("calendar", start="2024-04-01", end="2024-04-03"))
    assert result["status"] == "RESPONSE_REJECTED"
    saved = json.loads((tmp_path / result["raw_path"]).read_bytes())
    assert saved["rows"] == response["rows"]


def test_independent_collection_cannot_omit_a_planned_query(tmp_path):
    collection = collection_fixture(tmp_path)
    planned = [{key: item[key] for key in ("kind", "code", "start", "end", "date")}
               for item in collection["query_results"]]
    plan_path = tmp_path / "request_plan.json"
    if not plan_path.exists():
        write_immutable(plan_path, {"queries": planned, "collection": copy.deepcopy(collection)})
    # The unchanged request plan still requires this instrument history.
    collection["query_results"] = collection["query_results"][:1]
    (tmp_path / "collection.json").write_text(json.dumps(collection), encoding="utf-8")
    result = audit_collection(tmp_path)
    assert result["integrity_status"] == "FAIL"
    assert result["status"] == "BLOCKED_DATA"
    assert result["strategy_runs_permitted"] is False


def test_independent_posteffective_action_identity_correction_blocks():
    data = fixture()
    data["actions"] = liquidation_events(data)
    revised = data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT"].copy()
    revised["available_at"] = data["calendar"][30] + "T08:00:00+08:00"
    revised["instrument_id"] = "ETF_B"
    data["actions"] = pd.concat([data["actions"], revised], ignore_index=True)
    with pytest.raises(ExecutionBlockedError, match="Post-effective corporate-action revision"):
        run_backtest(data, [decision(data)], 100000)


def test_independent_future_action_identity_correction_preserves_prior_prefix():
    data = fixture()
    data["actions"] = liquidation_events(data)
    revised = data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT"].copy()
    revised["available_at"] = "2030-01-01T08:00:00+08:00"
    revised["instrument_id"] = "ETF_B"
    baseline = run_backtest(data, [decision(data)], 100000)
    data["actions"] = pd.concat([data["actions"], revised], ignore_index=True)
    replay = run_backtest(data, [decision(data)], 100000)
    pd.testing.assert_frame_equal(baseline["nav"], replay["nav"])
    pd.testing.assert_frame_equal(baseline["rights"], replay["rights"])


@pytest.mark.parametrize("mode", ["SCHEDULED", "ASSUMED_SCHEDULED_CREDIT", "LATE_RECOGNITION"])
def test_independent_liquidation_cash_and_rights_reconcile_without_double_counting(mode):
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=30 if mode == "LATE_RECOGNITION" else 24,
                                          pay=28, mode=mode)
    result = run_backtest(data, [decision(data)], 100000)
    nav = result["nav"].set_index("date")
    cash_events = result["cash_events"]
    actual_cash = cash_events.loc[cash_events.event.isin(["BUY", "SELL", "DIVIDEND_PAID", "LIQUIDATION_PAID"])]
    changes = actual_cash.groupby("date").amount.sum().reindex(nav.index, fill_value=0)
    np.testing.assert_allclose(nav.cash_total, 100000 + changes.cumsum(), atol=1e-7)
    np.testing.assert_allclose(nav.nav, nav.cash_total + nav.holdings_value + nav.receivables, atol=1e-7)
    rights = result["rights"].set_index("date")
    np.testing.assert_allclose(rights.outstanding_receivable,
                               rights.recognized_amount - rights.paid_amount, atol=1e-7)
    assert rights.iloc[-1].status == "PAID_FINAL"
    assert rights.iloc[-1].carrying_value == 0
    assert len(actual_cash.loc[actual_cash.event == "LIQUIDATION_PAID"]) == 1
    assert result["accounting_timing_eligible"] is (mode == "SCHEDULED")
    assert result["confirmation_eligible"] is False


def test_independent_fresh_account_cannot_receive_old_liquidation_rights():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=30, pay=32)
    start = data["calendar"][28]
    result = run_backtest(data, [decision(data, index=28)], 100000, start_date=start)
    assert result["fills"].empty
    assert result["rights"].empty
    assert result["nav"].cash_total.eq(100000).all()
    assert "ECONOMICALLY_RETIRED_INSTRUMENT" in set(result["rejected_orders"].reason)


def test_independent_known_liquidation_receivable_is_not_spendable_cash():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=24, pay=32)
    result = run_backtest(data, [decision(data)], 100000)
    before = result["nav"].iloc[23]
    recognized = result["nav"].iloc[24]
    assert recognized.receivables > 0
    assert recognized.cash_available == before.cash_available
    assert recognized.cash_withdrawable == before.cash_withdrawable
    assert recognized.holdings_value == 0


def test_independent_rejected_holdout_response_is_retained_but_never_normalized(tmp_path):
    fields = ["calendar_date", "is_trading_day"]
    bad = {"status": "SUCCESS", "fields": fields, "rows": [["2025-01-02", "1"]]}
    adapter = BaoStockAdapter(tmp_path, worker=lambda *_: copy.deepcopy(bad), min_interval=0)
    result = adapter.collect(Query("calendar", start="2024-12-31", end="2024-12-31"))
    assert result["status"] == "RESPONSE_REJECTED"
    assert json.loads((tmp_path / result["raw_path"]).read_bytes())["rows"] == bad["rows"]
    assert not (tmp_path / "normalized").exists()


@pytest.mark.parametrize("verified", [None, False, "true"])
def test_independent_ordinary_dividend_schedule_does_not_admit_real_cash(verified):
    data = synthetic_dataset()
    data.manifest["synthetic"] = False
    data.actions = data.actions.loc[data.actions.action_type == "CASH_DIVIDEND"].copy()
    data.actions["cash_settlement_verified"] = verified
    report = audit_dataset(data)
    assert "dividend: actual account cash settlement unverified" in report["blockers"]
    assert report["status"] == "BLOCKED_DATA"
    assert report["performance_evidence"] is False
