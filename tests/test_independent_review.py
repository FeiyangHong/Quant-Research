"""Independent adversarial checks. All paths are invented engineering fixtures.

These tests establish neither historical returns nor out-of-sample evidence.
"""
import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation import paired_inference
from quant_research.execution import ExecutionBlockedError, run_backtest
from test_execution import decision, fixture


@pytest.mark.parametrize("capital", [float("nan"), float("inf"), -float("inf"), True, 0, -1])
def test_independent_invalid_capital_cannot_become_significant(capital):
    rng = np.random.default_rng(7)
    candidate = pd.Series(rng.normal(-.001, .01, 500))
    with pytest.raises(ValueError):
        paired_inference(candidate, candidate * 0, annual_incremental_cost=1000,
                         primary_capital=capital, repetitions=99)


def test_independent_known_delisting_uses_remaining_legal_exit_window():
    data = fixture()
    calendar = data["calendar"]
    revision = data["instruments"].iloc[[0]].copy()
    revision["available_at"] = calendar[22] + "T18:00:00+08:00"
    revision["delisted_on"] = calendar[27]
    data["instruments"] = pd.concat([data["instruments"], revision], ignore_index=True)
    result = run_backtest(data, [decision(data)], 100000)
    sales = result["fills"].query("side == 'SELL'")
    assert len(sales) == 1
    assert sales.iloc[0].date == calendar[23]
    assert sales.iloc[0].quantity == result["fills"].query("side == 'BUY'").quantity.sum()
    assert not result["positions"].query("date >= @calendar[27] and quantity > 0").shape[0]


def _dividend(data, record_index=21, ex_index=25):
    calendar = data["calendar"]
    return dict(action_id="independent_dividend", instrument_id="ETF_A",
                action_type="CASH_DIVIDEND", announcement_date=calendar[19],
                record_date=calendar[record_index], ex_date=calendar[ex_index],
                pay_date=calendar[28], cash_per_share=1., share_factor=1.,
                recovery_per_share=None, available_at=calendar[19] + "T18:00:00+08:00")


def test_independent_dividend_stays_with_record_date_holder_after_sale():
    data = fixture()
    data["actions"] = pd.DataFrame([_dividend(data)])
    result = run_backtest(data, [decision(data), decision(data, 22, {})], 100000)
    receipts = result["cash_events"].query("event == 'DIVIDEND_RECEIVABLE'")
    buys = result["fills"].query("side == 'BUY'")
    assert receipts.amount.sum() == buys.quantity.sum() * 1.
    assert result["cash_events"].query("event == 'DIVIDEND_PAID'").amount.sum() == receipts.amount.sum()


def test_independent_purchase_after_record_date_does_not_gain_dividend():
    data = fixture()
    data["actions"] = pd.DataFrame([_dividend(data)])
    result = run_backtest(data, [decision(data, 22)], 100000)
    assert result["cash_events"].query("event == 'DIVIDEND_RECEIVABLE'").empty


def test_independent_future_action_revision_cannot_rewrite_prior_nav():
    data = fixture()
    calendar = data["calendar"]
    original = _dividend(data, record_index=22, ex_index=23)
    data["actions"] = pd.DataFrame([original])
    baseline = run_backtest(data, [decision(data)], 100000)
    revised = dict(original, record_date=calendar[26], ex_date=calendar[27],
                   available_at=calendar[25] + "T18:00:00+08:00")
    data["actions"] = pd.DataFrame([original, revised])
    try:
        result = run_backtest(data, [decision(data)], 100000)
    except ExecutionBlockedError as error:
        # An explicit unsupported-history block is safe for this limited MVP.
        assert "revision" in str(error).lower() or "action" in str(error).lower()
        return
    cutoff = calendar[25]
    before = baseline["nav"].query("date < @cutoff").reset_index(drop=True)
    after = result["nav"].query("date < @cutoff").reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


def test_independent_stock_unknown_status_cannot_be_bought_with_valid_tax_rules():
    data = fixture()
    data["instruments"]["asset_type"] = "STOCK"
    data["instruments"]["board"] = "MAIN"
    data["instruments"] = data["instruments"].drop(columns=["status", "is_st"], errors="ignore")
    rules = [dict(effective_from="2020-01-01", effective_to="2020-12-31",
                  stamp_duty_sell=.001, transfer_fee_both=.00002, verified=True,
                  source_url="https://example.test/invented-tax-rule")]
    result = run_backtest(data, [decision(data, weights={"ETF_A": .04})], 100000,
                          tax_rules=rules)
    assert result["fills"].empty
    assert not result["rejected_orders"].empty
