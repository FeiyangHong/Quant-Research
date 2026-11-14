"""Independently reconcile actual execution output, including liquidation rights."""
import copy
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from quant_research.execution import run_backtest
from test_execution import decision, fixture, liquidation_events


_spec = importlib.util.spec_from_file_location(
    "ledger_summary", Path(__file__).resolve().parents[1] / "scripts" / "summarize_runs.py")
_summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_summary)

INITIAL_CASH = 100000
TABLE_NAMES = ("nav", "positions", "fills", "orders", "costs", "rejected_orders", "cash_events")


def tables_from(result):
    # Use the same exported tables consumed by summarize_run, without borrowing
    # the engine's own internal balances or right-valuation implementation.
    return {name: result[name].copy(deep=True) for name in TABLE_NAMES}


def assert_reconciled(tables):
    check = _summary.reconcile(tables, INITIAL_CASH)
    assert check["status"] == "PASS"
    assert all(error <= check["tolerance_cny"]
               for error in check["maximum_absolute_errors_cny"].values())


def payment_amount(quantity, per_share):
    return float((Decimal(int(quantity)) * Decimal(str(per_share))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize("pay,delist", [(28, 32), (31, 26)],
                         ids=["payment-before-delist", "payment-after-delist"])
def test_liquidation_reconciles_retirement_receivable_payment_and_delisting(pay, delist):
    data = fixture()
    data["actions"] = liquidation_events(data, pay=pay, delist=delist)
    result = run_backtest(data, [decision(data)], INITIAL_CASH)
    tables = tables_from(result)
    assert_reconciled(tables)

    nav = tables["nav"].set_index("date")
    events = tables["cash_events"]
    fill = tables["fills"].iloc[0]
    amount = payment_amount(fill.quantity, .77524)
    cash_after_buy = INITIAL_CASH - fill.notional - fill.fees
    retired, paid = data["calendar"][24], data["calendar"][pay]
    assert nav.loc[retired, "holdings_value"] == 0
    assert nav.loc[retired, "receivables"] == amount
    assert nav.loc[retired, "cash_total"] == pytest.approx(cash_after_buy)
    assert nav.loc[paid, "receivables"] == 0
    assert nav.loc[paid, "cash_total"] == pytest.approx(cash_after_buy + amount)
    assert nav.loc[retired:, "nav"].tolist() == pytest.approx(
        [cash_after_buy + amount] * len(nav.loc[retired:]), rel=0, abs=1e-6)
    assert events.loc[events.event.eq("LIQUIDATION_RIGHT_RECOGNIZED"), "amount"].tolist() == [0.]
    assert events.loc[events.event.eq("LIQUIDATION_PAID"), "amount"].tolist() == [amount]


def test_overlapping_installments_reconcile_outstanding_balance_through_delisting():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=25, pay=30, per_share=.5, final=False)
    second = data["actions"].loc[data["actions"].action_type.eq("LIQUIDATION_PAYMENT")].copy()
    second["action_id"], second["installment_id"] = "installment2", "distribution-2"
    second["cash_per_share"], second["is_final"] = .27524, True
    second["ex_date"] = second["recognition_date"] = data["calendar"][28]
    second["pay_date"] = data["calendar"][34]
    second["available_at"] = data["calendar"][28] + "T08:00:00+08:00"
    data["actions"] = pd.concat([data["actions"], second], ignore_index=True)
    result = run_backtest(data, [decision(data)], INITIAL_CASH)
    tables = tables_from(result)
    assert_reconciled(tables)

    fill = tables["fills"].iloc[0]
    first_amount, second_amount = [payment_amount(fill.quantity, rate) for rate in (.5, .27524)]
    nav = tables["nav"]
    assert nav.iloc[25].receivables == first_amount
    assert nav.iloc[28].receivables == pytest.approx(first_amount + second_amount)
    assert nav.iloc[30].receivables == nav.iloc[32].receivables == second_amount
    assert nav.iloc[34].receivables == 0
    assert nav.iloc[34].cash_total == pytest.approx(
        INITIAL_CASH - fill.notional - fill.fees + first_amount + second_amount)
    payments = tables["cash_events"].query("event == 'LIQUIDATION_PAID'")
    assert payments.installment_id.tolist() == ["distribution-1", "distribution-2"]
    assert payments.amount.tolist() == [first_amount, second_amount]
    assert result["rights"].iloc[-1].status == "PAID_FINAL"


@pytest.mark.parametrize("mode,recognize,pay,booked,valuation_status", [
    ("ASSUMED_SCHEDULED_CREDIT", 24, 28, 28, "ASSUMED_SCHEDULED_CREDIT"),
    ("LATE_RECOGNITION", 32, 28, 32, "OBSERVATION_TIME_REPLAY"),
])
def test_replay_modes_reconcile_without_backdating_or_claiming_confirmation(
        mode, recognize, pay, booked, valuation_status):
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=recognize, pay=pay, mode=mode)
    decisions = [decision(data)]
    result = run_backtest(data, decisions, INITIAL_CASH)
    tables = tables_from(result)
    assert_reconciled(tables)

    # Re-running only the history available before the cash entry gives the
    # same prior ledger, including its independently reconciled receivables.
    prefix = copy.deepcopy(data)
    prefix["calendar"] = prefix["calendar"][:booked]
    earlier = run_backtest(prefix, decisions, INITIAL_CASH)
    assert_reconciled(tables_from(earlier))
    pd.testing.assert_frame_equal(earlier["nav"], result["nav"].iloc[:booked].reset_index(drop=True))

    paid = tables["cash_events"].query("event == 'LIQUIDATION_PAID'").iloc[0]
    assert paid.date == data["calendar"][booked]
    assert result["nav"].iloc[booked].cash_total == pytest.approx(
        result["nav"].iloc[booked - 1].cash_total + paid.amount)
    assert result["nav"].iloc[-1].valuation_status == valuation_status
    assert result["nav"].iloc[-1].valuation_uncertainty
    assert result["accounting_timing_eligible"] is False
    assert result["confirmation_eligible"] is False
    if mode == "ASSUMED_SCHEDULED_CREDIT":
        assert pd.isna(paid.actual_pay_date)
        assert paid.scheduled_pay_date == data["calendar"][pay]
    else:
        assert paid.actual_pay_date == data["calendar"][pay]
        assert result["nav"].iloc[pay].cash_total == result["nav"].iloc[booked - 1].cash_total


@pytest.fixture(scope="module")
def ordinary_liquidation_tables():
    data = fixture()
    data["actions"] = liquidation_events(data)
    result = run_backtest(data, [decision(data)], INITIAL_CASH)
    tables = tables_from(result)
    assert_reconciled(tables)
    return tables


@pytest.mark.parametrize("corruption", ["duplicate-payment", "missing-receivable", "wrong-receivable"])
def test_reconciliation_rejects_corrupted_payment_or_receivable_events(
        ordinary_liquidation_tables, corruption):
    tables = {name: table.copy(deep=True) for name, table in ordinary_liquidation_tables.items()}
    events = tables["cash_events"]
    if corruption == "duplicate-payment":
        payment = events.loc[events.event.eq("LIQUIDATION_PAID")]
        tables["cash_events"] = pd.concat([events, payment], ignore_index=True)
    elif corruption == "missing-receivable":
        tables["cash_events"] = events.loc[~events.event.eq("LIQUIDATION_RECEIVABLE")].copy()
    else:
        events.loc[events.event.eq("LIQUIDATION_RECEIVABLE"), "amount"] += .01
    with pytest.raises(ValueError, match="Ledger reconciliation failed:.*receivables"):
        _summary.reconcile(tables, INITIAL_CASH)


def test_reconciliation_rejects_double_cash_credit_even_when_nav_identity_balances(
        ordinary_liquidation_tables):
    tables = {name: table.copy(deep=True) for name, table in ordinary_liquidation_tables.items()}
    paid = tables["cash_events"].query("event == 'LIQUIDATION_PAID'").iloc[0]
    nav = tables["nav"]
    columns = ["cash_total", "cash", "cash_available", "cash_withdrawable", "nav"]
    nav.loc[nav.date.ge(paid.date), columns] += paid.amount
    # A mere NAV = cash + holdings + receivables assertion cannot catch this.
    assert nav.nav.to_numpy() == pytest.approx((nav.cash_total + nav.holdings_value + nav.receivables).to_numpy())
    with pytest.raises(ValueError, match="Ledger reconciliation failed:.*cash"):
        _summary.reconcile(tables, INITIAL_CASH)


@pytest.mark.parametrize("amount", [.01, -.01, float("nan")])
def test_right_recognition_must_be_zero_even_when_cash_and_nav_are_unchanged(
        ordinary_liquidation_tables, amount):
    tables = {name: table.copy(deep=True) for name, table in ordinary_liquidation_tables.items()}
    events = tables["cash_events"]
    events.loc[events.event.eq("LIQUIDATION_RIGHT_RECOGNIZED"), "amount"] = amount
    with pytest.raises(ValueError, match="Right recognition cannot create cash or receivable amounts"):
        _summary.reconcile(tables, INITIAL_CASH)
