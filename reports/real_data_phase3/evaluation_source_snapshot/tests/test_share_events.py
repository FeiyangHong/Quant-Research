"""Issuer-defined account rounding and share-unit time boundaries."""
import copy
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

import pandas as pd
import pytest

from quant_research.execution import ExecutionBlockedError, run_backtest
from test_execution import fixture, decision


def split_data(factor, rounding="CEIL", phase="EOD", index=23):
    data = fixture()
    day = data["calendar"][index]
    data["actions"] = pd.DataFrame([dict(action_id="conversion", instrument_id="ETF_A",
        action_type="SPLIT", share_factor=factor, rounding_policy=rounding,
        effective_phase=phase, action_status="CONFIRMED", record_date=day if phase == "EOD" else data["calendar"][index - 1],
        ex_date=day, available_at=data["calendar"][index - 2] + "T21:00:00+08:00",
        terms_verified=True, source_url="https://example.test/TEST_ONLY_ISSUER_ACCOUNT_ROUNDING")])
    after = data["bars"].date > day if phase == "EOD" else data["bars"].date >= day
    mask = after & data["bars"].instrument_id.eq("ETF_A")
    # Price is raw source price: EOD day's close remains on the old unit basis.
    for field in ("open", "close"):
        data["bars"].loc[mask, field] = round(10 / float(factor), 3)
    data["bars"].loc[mask, ["high", "upper_limit"]] = round(12 / float(factor), 3)
    data["bars"].loc[mask, ["low", "lower_limit"]] = round(8 / float(factor), 3)
    return data


@pytest.mark.parametrize("rounding,factor", [("FLOOR", ".509"), ("CEIL", ".501")])
def test_round_once_for_account_across_two_acquisition_lots(rounding, factor):
    data = split_data(factor, rounding)
    decisions = [decision(data, 20, {"ETF_A": .01}), decision(data, 22, {"ETF_A": .021})]
    result = run_backtest(data, decisions, 100000, cost_multiplier=0, slippage_multiplier=0)
    bought = result["fills"].query("side == 'BUY'")
    assert list(bought.quantity) == [100, 100]
    event = result["share_events"].iloc[0]
    expected = int((Decimal(200) * Decimal(factor)).to_integral_value(
        rounding=ROUND_FLOOR if rounding == "FLOOR" else ROUND_CEILING))
    assert event.old_quantity == 200 and event.new_quantity == expected == 101
    at = result["positions"].query("date == @event.date").iloc[0]
    assert at.quantity == expected
    assert at.price == pytest.approx(10 / float(factor))
    assert at.locked_quantity > 0  # the ex-day purchase retains its next-day lock
    assert at.sellable_quantity <= int(Decimal(100) * Decimal(factor))
    next_day = data["calendar"][24]
    assert result["positions"].query("date == @next_day").iloc[0].sellable_quantity == expected


@pytest.mark.parametrize("factor,rounding,phase", [(".28032483", "FLOOR", "BOD"),
    ("1.14539", "CEIL", "EOD"), (".36555", "CEIL", "BOD")])
def test_actual_ratios_integer_account_entitlement_and_rounding_value_report(factor, rounding, phase):
    # Engineering fixture uses a known-in-advance ratio. It does not assert
    # that the actual 2015 ratio was publicly known before its effective date.
    data = split_data(factor, rounding, phase)
    result = run_backtest(data, [decision(data)], 100000, cost_multiplier=0, slippage_multiplier=0)
    event = result["share_events"].iloc[0]
    expected = int((Decimal(3000) * Decimal(factor)).to_integral_value(
        rounding=ROUND_FLOOR if rounding == "FLOOR" else ROUND_CEILING))
    assert event.new_quantity == expected
    assert event.rounding_share_delta == pytest.approx(expected - 3000 * float(factor))
    assert abs(event.rounding_value_delta) < event.reference_price_after


def test_eod_conversion_permits_day_trading_and_next_target_uses_post_conversion_basis():
    data = split_data("2", phase="EOD")
    decisions = [decision(data, 22, {"ETF_A": .10}), decision(data, 23, {"ETF_A": .30})]
    result = run_backtest(data, decisions, 100000, cost_multiplier=0, slippage_multiplier=0)
    date = data["calendar"][23]
    day_fill = result["fills"].query("date == @date").iloc[0]
    assert day_fill.price == 10 and day_fill.quantity == 1000
    nav = result["nav"].query("date == @date").iloc[0]
    assert nav.holdings_value == 10000 and nav.nav == 100000
    next_intent = result["orders"].query("decision_date == @date").iloc[0]
    assert next_intent.source_reference_price == 10
    assert next_intent.reference_price == 5
    assert next_intent.reference_basis == "POST_EOD_ADJUSTED"
    assert next_intent.quantity == 4000
    assert next_intent.quantity * next_intent.reference_price == 20000
    final = result["positions"].iloc[-1]
    assert final.quantity == 6000 and final.market_value == 30000


def test_eod_conversion_then_dividend_uses_post_split_record_units_once():
    data = split_data("2.5", phase="EOD")
    record, ex, pay = [data["calendar"][i] for i in (23, 24, 26)]
    event = dict(action_id="cash_after_registration", instrument_id="ETF_A", action_type="CASH_DIVIDEND",
        record_date=record, ex_date=ex, pay_date=pay, cash_per_share=.1, share_factor=1.,
        available_at=data["calendar"][21] + "T21:00:00+08:00")
    data["actions"] = pd.concat([data["actions"], pd.DataFrame([event])], ignore_index=True)
    mask = data["bars"].instrument_id.eq("ETF_A") & data["bars"].date.ge(ex)
    for field in ("open", "high", "low", "close", "upper_limit", "lower_limit"):
        data["bars"].loc[mask, field] -= .1
    result = run_backtest(data, [decision(data)], 100000, cost_multiplier=0, slippage_multiplier=0)
    assert result["share_events"].iloc[0].new_quantity == 7500
    paid = result["cash_events"].query("event == 'DIVIDEND_PAID'")
    assert len(paid) == 1 and paid.iloc[0].amount == pytest.approx(750)
    assert result["nav"].iloc[-1].nav == pytest.approx(100000)


def test_eod_sale_precedes_conversion_and_odd_lot_remainder_can_be_fully_sold():
    data = split_data("1.14539", phase="EOD")
    decisions = [decision(data, 20), decision(data, 22, {"ETF_A": .10}), decision(data, 24, {})]
    result = run_backtest(data, decisions, 100000, cost_multiplier=0, slippage_multiplier=0)
    sales = result["fills"].query("side == 'SELL'")
    assert sales.iloc[0].date == data["calendar"][23] and sales.iloc[0].price == 10
    assert result["share_events"].iloc[0].old_quantity == 1000
    assert result["share_events"].iloc[0].new_quantity == 1146
    assert sales.iloc[1].quantity == 1146  # odd balance disposed as a whole
    assert result["nav"].iloc[-1].holdings_value == 0


def test_cancelled_plan_preserved_without_mutating_holdings_or_canceling_trades():
    data = fixture()
    day = data["calendar"][23]
    data["actions"] = pd.DataFrame([dict(action_id="canceled-original-plan", instrument_id="ETF_A",
        action_type="SPLIT", share_factor=.2, rounding_policy="CEIL", effective_phase="BOD",
        action_status="CANCELLED", ex_date=day, available_at=data["calendar"][21] + "T21:00:00+08:00",
        terms_verified=True, source_url="https://example.test/TEST_ONLY_CANCELLATION")])
    result = run_backtest(data, [decision(data, 22)], 100000, cost_multiplier=0, slippage_multiplier=0)
    assert result["fills"].iloc[0].date == day
    assert result["positions"].iloc[-1].quantity == 3000
    assert result["share_events"].iloc[0].status == "CANCELLED_NO_MUTATION"


def test_late_final_ratio_cannot_value_held_shares_even_while_suspended():
    data = split_data(".28032483", "FLOOR", "BOD")
    data["actions"]["available_at"] = data["calendar"][25] + "T21:00:00+08:00"
    data["bars"].loc[data["bars"].date.isin(data["calendar"][22:24]), "suspended"] = True
    with pytest.raises(ExecutionBlockedError, match="UNKNOWN_SPLIT_TERMS_AT_EFFECTIVE_TIME"):
        run_backtest(data, [decision(data, 20)], 100000)


def test_late_pre_account_split_preserved_without_inventing_warmup_holdings():
    data = split_data(".28032483", "FLOOR", "BOD")
    data["actions"]["available_at"] = data["calendar"][25] + "T21:00:00+08:00"
    result = run_backtest(data, [decision(data, 28)], 100000, start_date=data["calendar"][27])
    assert result["nav"].iloc[0].nav == 100000
    assert result["nav"].iloc[0].holdings_value == 0
    assert result["share_events"].iloc[0].status == "UNOWNED_PRE_ACCOUNT_EVENT"
    assert result["share_events"].iloc[0].date == data["calendar"][23]
    assert result["fills"].iloc[0].date == data["calendar"][29]


def test_late_unowned_split_blocks_entries_until_terms_known_and_is_prefix_invariant():
    data = split_data(".28032483", "FLOOR", "BOD")
    data["actions"]["available_at"] = data["calendar"][25] + "T21:00:00+08:00"
    decisions = [decision(data, 23), decision(data, 26)]
    result = run_backtest(data, decisions, 100000)
    assert "SHARE_TERMS_NOT_YET_KNOWN" in set(result["rejected_orders"].reason)
    assert result["fills"].iloc[0].date == data["calendar"][27]
    prefix = copy.deepcopy(data)
    prefix["calendar"] = prefix["calendar"][:25]
    shorter = run_backtest(prefix, [decisions[0]], 100000)
    pd.testing.assert_frame_equal(shorter["nav"], result["nav"].iloc[:25].reset_index(drop=True))


def test_eod_effective_terms_must_be_known_by_close_and_rounding_needs_evidence():
    data = split_data("1.14539", phase="EOD")
    data["actions"]["available_at"] = data["calendar"][23] + "T16:00:00+08:00"
    with pytest.raises(ExecutionBlockedError, match="UNKNOWN_SPLIT_TERMS_AT_EFFECTIVE_TIME"):
        run_backtest(data, [decision(data)], 100000)
    data = split_data("1.14539", phase="EOD")
    data["actions"]["terms_verified"] = False
    with pytest.raises(ExecutionBlockedError, match="verified issuer terms"):
        run_backtest(data, [decision(data)], 100000)


def test_pending_delayed_sale_is_rebased_once_including_issuer_rounded_extra_unit():
    data = split_data("1.14539", phase="EOD")
    result = run_backtest(data, [decision(data), decision(data, 22, {}, delay=4)],
                          100000, cost_multiplier=0, slippage_multiplier=0)
    assert "SHARE_ACTION_ORDER_CANCELLED" in set(result["rejected_orders"].reason)
    sales = result["fills"].query("side == 'SELL'")
    assert len(sales) == 1
    assert sales.iloc[0].quantity == 3437
    assert result["nav"].iloc[-1].holdings_value == 0


def test_bod_suspended_old_unit_bar_cannot_overwrite_split_adjusted_valuation():
    data = split_data(".36555", phase="BOD")
    day = data["calendar"][23]
    mask = data["bars"].instrument_id.eq("ETF_A") & data["bars"].date.eq(day)
    data["bars"].loc[mask, ["open", "close", "high", "low"]] = 10.
    data["bars"].loc[mask, ["volume", "amount"]] = 0.
    data["bars"].loc[mask, "suspended"] = True
    result = run_backtest(data, [decision(data)], 100000, cost_multiplier=0, slippage_multiplier=0)
    position = result["positions"].query("date == @day").iloc[0]
    assert position.quantity == 1097
    assert position.price == pytest.approx(10 / .36555)
    assert position.stale_days == 1
    assert position.market_value == pytest.approx(1097 * 10 / .36555)


def test_suspended_split_day_exit_reference_uses_adjusted_mark_not_old_unit_bar():
    data = split_data(".36555", phase="BOD")
    day = data["calendar"][23]
    mask = data["bars"].instrument_id.eq("ETF_A") & data["bars"].date.eq(day)
    data["bars"].loc[mask, ["open", "close", "high", "low"]] = 10.
    data["bars"].loc[mask, ["volume", "amount"]] = 0.
    data["bars"].loc[mask, "suspended"] = True
    result = run_backtest(data, [decision(data), decision(data, 23, {})], 100000,
                          cost_multiplier=0, slippage_multiplier=0)
    order = result["orders"].query("decision_date == @day").iloc[0]
    assert order.source_reference_price == 10
    assert order.reference_price == pytest.approx(10 / .36555)
    assert order.reference_basis == "CARRIED_ACTION_ADJUSTED_MARK"
    assert result["fills"].query("side == 'SELL'").iloc[0].quantity == 1097


def test_inconsistent_record_boundary_cannot_assign_wrong_day_ownership():
    data = split_data("1.14539", phase="EOD")
    data["actions"]["record_date"] = data["calendar"][22]
    with pytest.raises(ExecutionBlockedError, match="ownership boundary"):
        run_backtest(data, [decision(data)], 100000)
