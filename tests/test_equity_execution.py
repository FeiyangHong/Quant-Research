"""Adversarial synthetic accounting cases; never stock performance evidence."""
from copy import deepcopy
from decimal import Decimal

import pandas as pd
import pytest

from quant_research.equity_accounting import (
    CashDividendTaxLedger, EquityAccountingBlocked, daily_limit_ratio, dividend_tax_rate,
)
from quant_research.execution import ExecutionBlockedError, _account_split_lots, _charges, run_backtest


SOURCE = "https://example.test/synthetic-evidence-not-a-legal-source"


def book():
    return CashDividendTaxLedger("DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE")


def record(ledger, day, action="D1", cash="1", category="ORDINARY_CASH_DIVIDEND"):
    ledger.record_dividend(action, "A", day, cash, tax_category=category,
                           terms_verified=True, source_url=SOURCE)


@pytest.mark.parametrize("acquired,sold,expected", [
    ("2020-01-15", "2020-02-14", ".20"),
    ("2020-01-15", "2020-02-15", ".20"),
    ("2020-01-15", "2020-02-16", ".10"),
    ("2020-01-15", "2021-01-15", ".10"),
    ("2020-01-15", "2021-01-16", "0"),
    ("2019-12-15", "2020-01-15", ".20"),
    ("2019-12-15", "2020-01-16", ".10"),
])
def test_natural_month_year_inclusive_boundaries(acquired, sold, expected):
    assert dividend_tax_rate(acquired, sold, acquired) == Decimal(expected)


@pytest.mark.parametrize("acquired,sold", [("2020-01-31", "2020-02-28"), ("2020-02-29", "2021-03-01")])
def test_missing_calendar_anniversary_cannot_invent_registration_convention(acquired, sold):
    with pytest.raises(EquityAccountingBlocked, match="calendar anniversary"):
        dividend_tax_rate(acquired, sold, acquired)


def test_fifo_mixed_tenure_partial_sale_retains_unpaid_and_unsold_tax():
    ledger = book()
    old = ledger.buy("A", 100, "2018-01-15")
    mid = ledger.buy("A", 100, "2019-10-15")
    young = ledger.buy("A", 100, "2020-01-15")
    record(ledger, "2020-01-20")
    assert ledger.reserve("2020-01-21") == Decimal("30.00")
    event = ledger.sell("A", 250, "2020-01-21")
    assert event["lot_allocations"] == [(old, 100), (mid, 100), (young, 50)]
    assert event["amount"] == Decimal("20.00")
    assert event["actual_debit_date"] is None
    assert ledger.reserve("2020-01-22") == Decimal("30.00")
    ledger.settle_tax("T1", "2020-01-22", "20", terms_verified=True, source_url=SOURCE,
                      mode="RULE_BASED_SIMULATION")
    assert ledger.reserve("2020-01-23") == Decimal("10.00")
    assert ledger.tax_paid == Decimal("20.00")
    assert ledger.entitlements[-1]["remaining"] == 50
    assert ledger.entitlements[-1]["entitled_quantity"] == 100
    assert ledger.events[-1]["actual_debit_date"] is None


def test_record_rights_survive_sale_and_new_buys_never_inherit_old_dividends():
    ledger = book()
    ledger.buy("A", 100, "2020-01-02")
    record(ledger, "2020-01-03")
    assert ledger.sell("A", 100, "2020-01-06")["amount"] == 20
    ledger.buy("A", 100, "2020-01-07")
    assert ledger.sell("A", 100, "2020-01-08")["amount"] == 0
    assert ledger.entitlements[0]["entitled_quantity"] == 100
    assert ledger.tax_payable == 20


def test_multiple_dividends_tax_once_and_reserve_is_not_a_cash_debit():
    ledger = book()
    ledger.buy("A", 100, "2020-01-02")
    record(ledger, "2020-01-03", cash=".125")
    record(ledger, "2020-01-06", action="D2", cash=".075")
    assert ledger.reserve("2020-01-07") == Decimal("4.00")
    assert ledger.tax_payable == ledger.tax_paid == 0
    assert ledger.sell("A", 100, "2020-01-07")["amount"] == Decimal("4.00")
    assert ledger.reserve("2020-01-08") == Decimal("4.00")
    ledger.settle_tax("T1", "2020-01-08", "4", terms_verified=True, source_url=SOURCE,
                      mode="VERIFIED_ACCOUNT_DEBIT")
    assert ledger.reserve("2020-01-09") == 0
    with pytest.raises(EquityAccountingBlocked):
        ledger.settle_tax("T1", "2020-01-09", "4", terms_verified=True, source_url=SOURCE,
                          mode="VERIFIED_ACCOUNT_DEBIT")


def test_fifo_failure_is_atomic_and_missing_cash_is_not_zero():
    ledger = book()
    ledger.buy("A", 100, "2020-01-31")
    record(ledger, "2020-02-03")
    before = deepcopy((ledger.lots, ledger.entitlements, ledger.events))
    with pytest.raises(EquityAccountingBlocked, match="calendar anniversary"):
        ledger.sell("A", 100, "2020-02-04")
    assert before == (ledger.lots, ledger.entitlements, ledger.events)
    with pytest.raises(EquityAccountingBlocked, match="finite amount"):
        record(ledger, "2020-02-05", action="D2", cash=None)


def test_future_replay_duplicate_record_unsupported_tax_class_and_tplus_blocked():
    ledger = book()
    ledger.buy("A", 100, "2020-01-02")
    with pytest.raises(EquityAccountingBlocked, match=r"T\+1"):
        ledger.sell("A", 100, "2020-01-02")
    record(ledger, "2020-01-03")
    for call in (lambda: record(ledger, "2020-01-03"),
                 lambda: ledger.buy("A", 100, "2020-01-03"),
                 lambda: ledger.buy("A", 100, "2019-12-31"),
                 lambda: record(ledger, "2020-01-06", action="D2", category="CAPITAL_RESERVE"),
                 lambda: ledger.buy("A", 100, "2025-01-02")):
        with pytest.raises(EquityAccountingBlocked):
            call()


def regime(**updates):
    values = dict(board="CHINEXT", day="2020-08-24", is_st=False, listed_on="2010-01-01",
                  listing_session=2000, ipo_regime="APPROVAL")
    values.update(updates)
    return daily_limit_ratio(**values)


def test_chinext_reform_st_and_legacy_delisting_exception():
    assert regime(day="2020-08-21") == Decimal(".10")
    assert regime(day="2020-08-21", is_st=True) == Decimal(".05")
    assert regime() == regime(is_st=True) == Decimal(".20")
    assert regime(board="MAIN", is_st=True) == Decimal(".05")
    assert regime(delisting_started_on="2020-08-03") == Decimal(".10")
    with pytest.raises(EquityAccountingBlocked, match="transition"):
        regime(delisting_started_on="2020-08-24")


@pytest.mark.parametrize("board,listing", [("MAIN", "2023-04-10"), ("CHINEXT", "2020-08-24")])
def test_registration_ipo_first_five_are_explicitly_unbounded(board, listing):
    sessions = pd.bdate_range(listing, periods=6).strftime("%Y-%m-%d").tolist()
    for session in (1, 5):
        assert regime(board=board, day=sessions[session - 1], listed_on=listing, listing_session=session,
                      ipo_regime="REGISTRATION") is None
    assert regime(board=board, day=sessions[5], listed_on=listing, listing_session=6,
                  ipo_regime="REGISTRATION") == (Decimal(".10") if board == "MAIN" else Decimal(".20"))


def test_unknown_status_special_session_and_legacy_ipo_cannot_default_ten_percent():
    for changes in (dict(is_st=None), dict(special_session=True), dict(listing_session=1),
                    dict(ipo_regime="REGISTRATION"), dict(delisting_started_on="2020-08-25")):
        with pytest.raises(EquityAccountingBlocked):
            regime(**changes)


def stock_fixture(start="2020-01-01"):
    calendar = pd.bdate_range(start, periods=40).strftime("%Y-%m-%d").tolist()
    instruments = pd.DataFrame([dict(instrument_id="A", asset_type="STOCK", board="MAIN",
        listed_on="2010-01-01", delisted_on=None, available_at="2010-01-01T00:00:00+08:00",
        account_verified=True, industry="IND", lot_size=100, tick_size=.01, t_plus=1,
        status="NORMAL", is_st=False)])
    bars = pd.DataFrame([dict(date=day, instrument_id="A", open=10., high=11., low=9., close=10.,
        volume=1e7, amount=1e8, upper_limit=11., lower_limit=9., suspended=False,
        available_at=day + "T16:00:00+08:00") for day in calendar])
    return dict(calendar=calendar, instruments=instruments, bars=bars, actions=pd.DataFrame())


def decision(data, index=20, weight=.04):
    return dict(decision_date=data["calendar"][index], execution_date=data["calendar"][index + 1],
                weights={"A": weight} if weight else {}, reference_prices={"A": 10.}, adv20={"A": 1e8})


def rules():
    return [dict(effective_from="2016-01-01", effective_to="2024-12-31", stamp_duty_sell=.001,
                 transfer_fee_both=.00002, verified=True, source_url=SOURCE)]


@pytest.mark.parametrize("permission", [None, "true", 1])
def test_stock_account_permission_requires_true_boolean(permission):
    data = stock_fixture()
    data["instruments"]["account_verified"] = permission
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result["fills"].empty
    assert "STOCK_PERMISSION_UNVERIFIED" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("flag", [True, None, pd.NA, float("nan"), 0, 1, 0., 1., "0", "1", "False", "True"])
def test_stock_st_flag_requires_explicit_boolean_false(flag):
    data = stock_fixture()
    data["instruments"]["is_st"] = pd.Series([flag], dtype=object)
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result["fills"].empty
    assert "INSTRUMENT_STATUS_DENIED" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("status", [None, pd.NA, float("nan"), "", "ST", "*ST", "DELISTING", "UNKNOWN", 0, False])
def test_stock_false_st_flag_does_not_override_unknown_or_conflicting_status(status):
    data = stock_fixture()
    data["instruments"]["status"] = pd.Series([status], dtype=object)
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result["fills"].empty
    assert "INSTRUMENT_STATUS_DENIED" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("missing", ["is_st", "status"])
def test_stock_missing_status_field_has_no_synthetic_or_real_compatibility_bypass(missing):
    for synthetic in (True, False):
        data = stock_fixture()
        data["manifest"] = {"synthetic": synthetic}
        data["instruments"] = data["instruments"].drop(columns=missing)
        result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
        assert result["fills"].empty
        assert "INSTRUMENT_STATUS_DENIED" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("blocked_sale", [False, True])
def test_invalid_st_revision_triggers_pit_defensive_exit_retaining_unfilled_shares(blocked_sale):
    data = stock_fixture()
    update = data["instruments"].iloc[0].to_dict()
    update.update(is_st="1", available_at=data["calendar"][23] + "T20:00:00+08:00")
    data["instruments"] = pd.concat([data["instruments"], pd.DataFrame([update])], ignore_index=True)
    if blocked_sale:
        data["bars"].loc[data["bars"].date >= data["calendar"][24], "suspended"] = True
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    buy = result["fills"].query("side == 'BUY'").iloc[0]
    assert buy.date == data["calendar"][21]  # Later malformed metadata cannot rewrite the prior buy.
    exits = result["orders"].query("intent_type == 'RISK_EXIT'")
    assert exits.iloc[0].decision_date == data["calendar"][23]
    assert exits.iloc[0].execution_date == data["calendar"][24]
    assert set(exits.risk_reason) == {"INSTRUMENT_STATUS_DENIED"}
    sales = result["fills"].query("side == 'SELL'")
    if blocked_sale:
        assert sales.empty and list(exits.attempt) == [1, 2, 3, 4, 5]
        assert result["positions"].iloc[-1].quantity == buy.quantity
        assert "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS" in set(result["rejected_orders"].reason)
    else:
        assert sales.iloc[0].date == data["calendar"][24]
        assert sales.quantity.sum() == buy.quantity


@pytest.mark.parametrize("status", ["NORMAL", "ACTIVE"])
def test_explicit_nonst_status_can_trade(status):
    data = stock_fixture()
    data["instruments"]["status"] = status
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert list(result["fills"].side) == ["BUY"]


def test_even_integral_stock_splits_block_and_cash_dividend_still_blocks():
    for kind, reason in [("SPLIT", "tax classification"), ("CASH_DIVIDEND", "Stock dividend")]:
        data = stock_fixture()
        ex = data["calendar"][23]
        data["actions"] = pd.DataFrame([dict(action_id="X", instrument_id="A", action_type=kind,
            ex_date=ex, available_at=ex + "T08:00:00+08:00", share_factor=2.)])
        with pytest.raises(ExecutionBlockedError, match=reason):
            run_backtest(data, [decision(data)], 100000, tax_rules=rules())


def test_delisted_unknown_recovery_retains_shares_and_explicit_uncertainty():
    data = stock_fixture()
    ex = data["calendar"][24]
    data["actions"] = pd.DataFrame([dict(action_id="X", instrument_id="A", action_type="DELISTING",
        ex_date=ex, available_at=ex + "T08:00:00+08:00", recovery_per_share=None)])
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result["positions"].iloc[-1].quantity == result["fills"].iloc[0].quantity
    assert result["positions"].iloc[-1].delisted_rights
    assert result["positions"].iloc[-1].market_value == 0
    assert result["nav"].iloc[-1].valuation_status == "CONSERVATIVE_UNPRICED_RIGHTS"
    assert not result["accounting_timing_eligible"]


def test_missing_stock_quote_carries_value_but_is_not_verified_valuation():
    data = stock_fixture()
    data["bars"] = data["bars"].loc[data["bars"].date < data["calendar"][24]]
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result["positions"].iloc[-1].price == 10.
    assert result["positions"].iloc[-1].stale_days == 16
    assert result["nav"].iloc[-1].valuation_status == "STALE_STOCK_MARK"
    assert not result["accounting_timing_eligible"]


def test_future_fee_rule_cannot_authorize_trade_and_real_requires_rule_availability():
    # M6 validates the unique applicable row after scope selection. Its future
    # publication now has an explicit reason; the no-fill guard remains intact.
    for real, known, expected in [(False, "2030-01-01T00:00:00+08:00", "STOCK_TAX_RULE_NOT_KNOWN_AT_OPEN"),
                                   (True, None, "STOCK_TAX_RULE_AVAILABILITY_REQUIRED")]:
        data = stock_fixture()
        data["manifest"] = {"synthetic": not real}
        rate_rows = rules()
        rate_rows[0]["available_at"] = known
        result = run_backtest(data, [decision(data)], 100000, tax_rules=rate_rows)
        assert result["fills"].empty
        assert expected in set(result["rejected_orders"].reason)


def test_integer_buys_tplus_and_historical_fees_are_cash_accounted():
    data = stock_fixture()
    result = run_backtest(data, [decision(data), decision(data, 22, 0)], 100000, tax_rules=rules())
    buy, sell = result["fills"].iloc[0], result["fills"].iloc[1]
    assert buy.quantity % 100 == 0 and buy.quantity == sell.quantity
    pos = result["positions"].query("date == @buy.date").iloc[0]
    assert pos.locked_quantity == buy.quantity and pos.sellable_quantity == 0
    assert buy.stamp_duty == 0 and sell.stamp_duty > 0
    assert buy.transfer_fee > 0 and sell.transfer_fee > 0
    assert result["nav"].iloc[-1].nav == pytest.approx(100000 - result["fills"].fees.sum()
                                                                    - result["fills"].slippage_cost.sum())


def test_statutory_fees_never_follow_commission_stress_and_decimal_half_cent():
    normal = _charges(12345.67, False, (.0005, .00001), 1)
    stress = _charges(12345.67, False, (.0005, .00001), 3)
    assert normal == (5., 6.17, .12)
    assert stress == (15., 6.17, .12)
    assert _charges(10., False, (.0005, .00001), 1)[1] == .01


@pytest.mark.parametrize("start,buy_day,sell_day,buy_transfer,sell_transfer,stamp", [
    ("2022-03-25", "2022-04-28", "2022-04-29", ".00002", ".00001", ".001"),
    ("2023-07-25", "2023-08-25", "2023-08-28", ".00001", ".00001", ".0005"),
])
def test_dated_fee_boundary_is_execution_day_not_signal_day(start, buy_day, sell_day, buy_transfer, sell_transfer, stamp):
    data = stock_fixture(start)
    schedule = [dict(effective_from=a, effective_to=b, stamp_duty_sell=s, transfer_fee_both=t,
                     verified=True, source_url=SOURCE, available_at=known) for a, b, s, t, known in [
        ("2016-01-01", "2022-04-28", .001, .00002, "2015-07-09T21:00:00+08:00"),
        ("2022-04-29", "2023-08-27", .001, .00001, "2022-04-28T21:00:00+08:00"),
        ("2023-08-28", "2024-12-31", .0005, .00001, "2023-08-27T21:00:00+08:00"),
    ]]
    buy_i, sell_i = data["calendar"].index(buy_day), data["calendar"].index(sell_day)
    result = run_backtest(data, [decision(data, buy_i - 1), decision(data, sell_i - 1, 0)],
                          100000, tax_rules=schedule)
    buy, sell = result["fills"].iloc[0], result["fills"].iloc[1]
    assert buy.date == buy_day and sell.date == sell_day
    assert buy.transfer_fee == _charges(buy.notional, True, (stamp, buy_transfer), 1)[2]
    assert sell.transfer_fee == _charges(sell.notional, False, (stamp, sell_transfer), 1)[2]
    assert sell.stamp_duty == _charges(sell.notional, False, (stamp, sell_transfer), 1)[1]


def test_unpaid_tax_is_kept_when_remaining_lot_ages_into_exemption():
    ledger = book()
    ledger.buy("A", 200, "2020-01-15")
    record(ledger, "2020-01-20")
    assert ledger.sell("A", 100, "2020-01-21")["amount"] == 20
    assert ledger.reserve("2020-02-15") == 40
    assert ledger.reserve("2020-02-16") == 30
    assert ledger.reserve("2021-01-15") == 30
    assert ledger.reserve("2021-01-16") == 20


def test_reserve_covers_multiple_half_cent_action_liabilities():
    ledger = book()
    ledger.buy("A", 100, "2020-01-02")
    record(ledger, "2020-01-03", cash=".00025")
    record(ledger, "2020-01-06", action="D2", cash=".00025")
    assert ledger.reserve("2020-01-07") == Decimal(".02")
    assert ledger.sell("A", 100, "2020-01-07")["amount"] == Decimal(".02")


@pytest.mark.parametrize("kind", ["RIGHTS_ISSUE", "ABSORPTION_MERGER"])
def test_unsupported_equity_entitlements_never_turn_into_no_event(kind):
    data = stock_fixture()
    ex = data["calendar"][23]
    data["actions"] = pd.DataFrame([dict(action_id="X", instrument_id="A", action_type=kind,
        ex_date=ex, available_at=ex + "T08:00:00+08:00")])
    with pytest.raises(ExecutionBlockedError, match="Unsupported corporate action"):
        run_backtest(data, [decision(data)], 100000, tax_rules=rules())


def test_odd_share_allocation_preserves_locks_but_does_not_admit_stock_bonus_actions():
    lots = [dict(quantity=100, sellable_index=1, acquired_on="2020-01-02"),
            dict(quantity=100, sellable_index=2, acquired_on="2020-01-03")]
    changed, total, _ = _account_split_lots(lots, "1.005", "EXACT")
    assert total == 201
    assert [lot["quantity"] for lot in changed] == [100, 101]
    assert [lot["sellable_index"] for lot in changed] == [1, 2]
