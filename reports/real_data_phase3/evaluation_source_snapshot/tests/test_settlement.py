"""Verified hypothetical-account cash is never mislabeled observed cash."""
import copy

import pandas as pd
import pytest

from quant_research.execution import ExecutionBlockedError, run_backtest
from quant_research.settlement import RULE_MODE, rule_errors
from test_execution import fixture, decision, liquidation_events


def with_rule(action):
    return dict(action, settlement_mode=RULE_MODE, scheduled_pay_date=action["pay_date"],
        actual_pay_date=None, cash_settlement_verified=False, settlement_rule_verified=True,
        settlement_rule_source_url="https://example.test/TEST_ONLY_RULE",
        settlement_rule_event_types=[action["action_type"]],
        settlement_rule_effective_from="2010-01-01", settlement_rule_effective_to="2024-12-31",
        settlement_rule_available_at="2010-01-01T16:00:00+08:00",
        settlement_account_type="HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT")


def dividend_data():
    data = fixture()
    days = data["calendar"]
    action = dict(action_id="DIV", instrument_id="ETF_A", action_type="CASH_DIVIDEND",
        record_date=days[23], ex_date=days[24], cash_per_share=.2, pay_date=days[28],
        available_at=days[22] + "T16:00:00+08:00")
    data["actions"] = pd.DataFrame([with_rule(action)])
    return data


@pytest.mark.parametrize("delay", [0, 1, 3])
def test_dividend_rule_cash_never_precedes_registered_delay(delay):
    data = dividend_data()
    result = run_backtest(data, [decision(data)], 100000, cash_delay_sessions=delay)
    pay_day = data["calendar"][28 + delay]
    paid = result["cash_events"].query("event == 'DIVIDEND_PAID'").iloc[0]
    assert paid.date == pay_day and paid.modeled_pay_date == pay_day
    assert pd.isna(paid.actual_pay_date)
    assert paid.scheduled_pay_date == data["calendar"][28]
    assert result["rule_based_settlement"] is True
    assert result["confirmation_eligible"] is False
    nav = result["nav"].set_index("date")
    assert nav.loc[data["calendar"][27 + delay], "receivables"] > 0
    assert nav.loc[pay_day, "receivables"] == 0
    assert (nav.nav - nav.cash_total - nav.holdings_value - nav.receivables).abs().max() < 1e-7


def test_delayed_cash_beyond_sample_stays_receivable_without_opening_holdout():
    data = dividend_data()
    data["calendar"] = data["calendar"][:30]
    result = run_backtest(data, [decision(data)], 100000, cash_delay_sessions=3)
    assert result["cash_events"].query("event == 'DIVIDEND_PAID'").empty
    assert result["nav"].iloc[-1].receivables > 0
    assert result["cash_events"].query("event == 'DIVIDEND_RECEIVABLE'").modeled_pay_date.isna().all()


def test_custodian_transfer_is_not_investor_cash_and_delay_starts_after_model_credit():
    data = dividend_data()
    data["actions"]["settlement_rule_credit_basis"] = "NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER"
    data["actions"]["participant_transfer_date"] = data["calendar"][29]
    data["actions"]["modeled_cash_date"] = data["calendar"][30]
    result = run_backtest(data, [decision(data)], 100000, cash_delay_sessions=1)
    paid = result["cash_events"].query("event == 'DIVIDEND_PAID'").iloc[0]
    assert paid.date == data["calendar"][31]
    assert paid.scheduled_pay_date == data["calendar"][28]
    assert pd.isna(paid.actual_pay_date)
    assert result["nav"].query("date == @paid.scheduled_pay_date").iloc[0].receivables > 0
    data["actions"]["modeled_cash_date"] = data["calendar"][32]
    with pytest.raises(ExecutionBlockedError, match="one session"):
        run_backtest(data, [decision(data)], 100000)


@pytest.mark.parametrize("key,value", [
    ("settlement_rule_verified", "true"), ("actual_pay_date", "2020-02-10"),
    ("settlement_rule_event_types", ["LIQUIDATION_PAYMENT"]),
    ("settlement_rule_effective_from", "2021-01-01"),
    ("settlement_rule_available_at", "2026-01-01T16:00:00+08:00"),
    ("settlement_account_type", "OBSERVED_PERSONAL_ACCOUNT"),
])
def test_rule_does_not_generalize_to_wrong_event_time_or_actual_receipt(key, value):
    data = dividend_data()
    row = data["actions"].iloc[0].to_dict()
    row[key] = value
    assert rule_errors(row)
    data["actions"] = pd.DataFrame([row])
    with pytest.raises(ExecutionBlockedError):
        run_backtest(data, [decision(data)], 100000)


def test_liquidation_requires_its_own_rule_scope_and_preserves_receivable():
    data = fixture()
    actions = liquidation_events(data).to_dict("records")
    actions[1] = with_rule(actions[1])
    data["actions"] = pd.DataFrame(actions)
    result = run_backtest(data, [decision(data)], 100000, cash_delay_sessions=3)
    paid = result["cash_events"].query("event == 'LIQUIDATION_PAID'").iloc[0]
    assert paid.date == data["calendar"][31] and pd.isna(paid.actual_pay_date)
    wrong = copy.deepcopy(data)
    row = wrong["actions"].iloc[1].to_dict()
    row["settlement_rule_event_types"] = ["CASH_DIVIDEND"]
    wrong["actions"] = pd.DataFrame([actions[0], row, actions[2]])
    with pytest.raises(ExecutionBlockedError, match="event type"):
        run_backtest(wrong, [decision(wrong)], 100000)
