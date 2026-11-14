import copy

import numpy as np
import pandas as pd
import pytest

from quant_research.execution import ExecutionBlockedError, run_backtest


def fixture(names=("ETF_A", "ETF_B", "ETF_C"), days=40):
    calendar = pd.bdate_range("2020-01-01", periods=days).strftime("%Y-%m-%d").tolist()
    instruments = pd.DataFrame([dict(instrument_id=sid, asset_type="ETF", board="ETF",
        listed_on="2010-01-01", delisted_on=None, available_at="2010-01-01T00:00:00+08:00",
        account_verified=True, benchmark_id="INDEX", industry="BROAD", lot_size=100,
        tick_size=.001, t_plus=1, status="NORMAL", is_st=False) for sid in names])
    bars = pd.DataFrame([dict(date=day, instrument_id=sid, open=10., high=11., low=9.,
        close=10., volume=10000000., amount=100000000., upper_limit=11., lower_limit=9.,
        suspended=False, available_at=day + "T16:00:00+08:00", revision_id="1",
        total_return_index=100.) for day in calendar for sid in names])
    return dict(calendar=calendar, instruments=instruments, bars=bars, actions=pd.DataFrame())


def decision(data, index=20, weights=None, delay=1):
    day = data["calendar"][index]
    rows = data["bars"].loc[data["bars"].date == day].drop_duplicates("instrument_id", keep="last")
    return dict(decision_date=day, execution_date=data["calendar"][index + delay],
        weights={"ETF_A": .3} if weights is None else weights,
        reference_prices=dict(zip(rows.instrument_id, rows.close)),
        adv20={sid: 100000000. for sid in rows.instrument_id})


def test_ledger_nav_costs_lots_tplus_and_immutable_input():
    data = fixture()
    d = decision(data)
    original = copy.deepcopy(d)
    result = run_backtest(data, [d], 100000)
    assert d == original
    fill = result["fills"].iloc[0]
    assert fill.quantity % 100 == 0 and fill.price >= 10.003
    assert fill.commission == pytest.approx(round(fill.notional * .0003, 2))
    assert fill.stamp_duty == fill.transfer_fee == 0
    buy_position = result["positions"].query("date == @fill.date").iloc[0]
    assert buy_position.sellable_quantity == 0 and buy_position.locked_quantity == fill.quantity
    next_day = data["calendar"][22]
    assert result["positions"].query("date == @next_day").iloc[0].sellable_quantity == fill.quantity
    nav = result["nav"]
    assert np.allclose(nav.nav, nav.cash_total + nav.holdings_value + nav.receivables)
    assert nav.iloc[-1].nav == pytest.approx(100000 - fill.fees - fill.slippage_cost)
    assert nav.cash_available.min() >= 0
    assert (nav.cash_withdrawable <= nav.cash_total).all()


def test_open_gap_cannot_increase_intent_or_spend_beyond_reference_reservation():
    data = fixture()
    d = decision(data)
    execution = d["execution_date"]
    data["bars"].loc[(data["bars"].date == execution) & (data["bars"].instrument_id == "ETF_A"),
        ["open", "high", "low", "close", "upper_limit", "lower_limit"]] = [11., 12., 10., 11., 12., 9.]
    result = run_backtest(data, [d], 100000)
    order, fill = result["orders"].iloc[0], result["fills"].iloc[0]
    assert order.quantity == 3000 and order.reference_price == 10.
    assert fill.quantity < order.quantity
    reserve = result["order_events"].query("event == 'RESERVE'").iloc[0]
    assert fill.notional + fill.fees <= reserve.cash_reserved
    assert reserve.cash_total == pytest.approx(reserve.cash_available + reserve.cash_reserved)


@pytest.mark.parametrize("problem,reason", [("suspended", "SUSPENDED_OR_UNKNOWN_STATUS"),
    ("upper", "OPEN_AT_ADVERSE_LIMIT"), ("tick", "INVALID_PRICE_GRID"),
    ("missing", "MISSING_PRICE_OR_LIMIT_RULE")])
def test_unexecutable_buys_expire_without_retry(problem, reason):
    data = fixture()
    d = decision(data)
    mask = (data["bars"].date == d["execution_date"]) & (data["bars"].instrument_id == "ETF_A")
    if problem == "suspended":
        data["bars"].loc[mask, "suspended"] = True
    elif problem == "upper":
        data["bars"].loc[mask, "open"] = 11.
    elif problem == "tick":
        data["bars"].loc[mask, "open"] = 10.0001
    else:
        data["bars"].loc[mask, "upper_limit"] = np.nan
    result = run_backtest(data, [d], 100000)
    assert result["fills"].empty and len(result["orders"]) == 1
    assert reason in set(result["rejected_orders"].reason)
    assert result["nav"].iloc[-1].nav == 100000


def test_historical_capacity_partial_fills_does_not_use_current_volume():
    data = fixture()
    data["bars"].loc[data["bars"].instrument_id == "ETF_A", "amount"] = 250000.
    d = decision(data)
    # Supplied ADV tries to overstate liquidity; authoritative history caps it.
    result = run_backtest(data, [d], 100000)
    fill = result["fills"].iloc[0]
    assert fill.quantity == 200
    assert fill.commission == 5
    assert fill.quantity * fill.price <= 2500
    assert len(result["fills"]) == 1
    assert "HISTORICAL_ADV_CAPACITY" in set(result["rejected_orders"].reason)


def test_five_failed_sell_orders_keep_holdings_and_do_not_free_cash():
    data = fixture()
    buy, sell = decision(data), decision(data, 22, {})
    mask = (data["bars"].date >= sell["execution_date"]) & (data["bars"].instrument_id == "ETF_A")
    data["bars"].loc[mask, "suspended"] = True
    result = run_backtest(data, [buy, sell], 100000)
    assert len(result["orders"].query("side == 'SELL'")) == 5
    assert len(result["fills"]) == 1
    assert result["positions"].iloc[-1].quantity > 0
    assert "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS" in set(result["rejected_orders"].reason)


def test_sale_proceeds_usable_same_session_but_not_withdrawable():
    data = fixture()
    result = run_backtest(data, [decision(data), decision(data, 22, {"ETF_B": .3})], 100000)
    day = data["calendar"][23]
    fills = result["fills"].query("date == @day")
    assert list(fills.side) == ["SELL", "BUY"]
    nav = result["nav"].query("date == @day").iloc[0]
    assert nav.cash_total > nav.cash_withdrawable
    later = result["nav"].query("date > @day").iloc[0]
    assert later.cash_total == later.cash_withdrawable


def test_dividend_receivable_payment_split_and_delisting_conserve_rights():
    data = fixture()
    ex, paid, split, delist = [data["calendar"][i] for i in (23, 25, 27, 29)]
    data["actions"] = pd.DataFrame([
        dict(action_id="div", instrument_id="ETF_A", action_type="CASH_DIVIDEND", ex_date=ex,
             record_date=data["calendar"][22], pay_date=paid, cash_per_share=1., share_factor=1., recovery_per_share=0., available_at=ex + "T08:00:00+08:00"),
        dict(action_id="split", instrument_id="ETF_A", action_type="SPLIT", ex_date=split,
             share_factor=2., recovery_per_share=0., available_at=split + "T08:00:00+08:00"),
        dict(action_id="exit", instrument_id="ETF_A", action_type="DELISTING", ex_date=delist,
             share_factor=1., recovery_per_share=0., available_at=delist + "T08:00:00+08:00")])
    data["bars"].loc[(data["bars"].date >= ex) & (data["bars"].instrument_id == "ETF_A"), ["open", "close"]] = 9.
    data["bars"].loc[(data["bars"].date >= split) & (data["bars"].instrument_id == "ETF_A"), ["open", "close"]] = 4.5
    result = run_backtest(data, [decision(data)], 100000)
    nav = result["nav"].set_index("date")
    assert nav.loc[ex, "receivables"] > 0
    assert nav.loc[paid, "receivables"] == 0
    assert nav.loc[ex, "nav"] == pytest.approx(nav.loc[data["calendar"][22], "nav"])
    assert nav.loc[paid, "nav"] == pytest.approx(nav.loc[split, "nav"])
    positions = result["positions"].set_index("date")
    assert positions.loc[split, "quantity"] == 2 * positions.loc[ex, "quantity"]
    assert positions.loc[delist, "delisted_rights"] and positions.loc[delist, "market_value"] == 0
    assert positions.loc[delist, "quantity"] == positions.loc[split, "quantity"]


def test_permissions_etf_independent_of_underlying_stock_board():
    data = fixture(("MAIN", "CHINEXT", "STAR", "BSE", "STAR_ETF", "UNVERIFIED_ETF"))
    master = data["instruments"]
    for sid in ("MAIN", "CHINEXT", "STAR", "BSE"):
        master.loc[master.instrument_id == sid, ["asset_type", "board"]] = ["STOCK", sid]
    master.loc[master.instrument_id == "STAR_ETF", "board"] = "STAR"
    master.loc[master.instrument_id == "UNVERIFIED_ETF", "account_verified"] = False
    weights = {sid: .04 for sid in master.instrument_id}
    result = run_backtest(data, [decision(data, weights=weights)], 100000)
    assert set(result["fills"].instrument_id) == {"STAR_ETF"}
    rejected = result["rejected_orders"].set_index("instrument_id").reason.to_dict()
    assert rejected["STAR"] == rejected["BSE"] == "BOARD_PERMISSION_DENIED"
    assert rejected["MAIN"] == rejected["CHINEXT"] == "UNKNOWN_OR_AMBIGUOUS_STOCK_TAX_RULE"
    assert rejected["UNVERIFIED_ETF"] == "ETF_PERMISSION_UNVERIFIED"


def test_stock_dates_tax_and_industry_joint_with_locked_positions():
    data = fixture(tuple("ABCDEF"))
    data["instruments"]["asset_type"] = "STOCK"
    data["instruments"]["board"] = "MAIN"
    weights = {sid: .05 for sid in "ABCDEF"}
    rules = pd.DataFrame([dict(effective_from="2020-01-01", effective_to="2020-12-31",
        stamp_duty_sell=.001, transfer_fee_both=.00002, verified=True,
        source_url="https://example.test/synthetic-rule-not-legal-evidence")])
    buy, sell = decision(data, weights=weights), decision(data, 22, {})
    result = run_backtest(data, [buy, sell], 1000000, tax_rules=rules)
    industry = result["exposure"].query("scope == 'STOCK_INDUSTRY'")
    assert industry.weight.max() <= .20
    assert (result["fills"].query("side == 'BUY'").stamp_duty == 0).all()
    assert (result["fills"].query("side == 'SELL'").stamp_duty > 0).all()
    stressed = run_backtest(data, [buy, sell], 1000000, cost_multiplier=3, tax_rules=rules)
    common = result["fills"].merge(stressed["fills"], on=["date", "instrument_id", "side", "quantity", "price"], suffixes=("_a", "_b"))
    assert (common.stamp_duty_a == common.stamp_duty_b).all()
    assert (common.transfer_fee_a == common.transfer_fee_b).all()


def test_late_revision_never_changes_prior_execution_or_nav():
    data = fixture()
    d = decision(data)
    original = run_backtest(data, [d], 100000)
    late = data["bars"].loc[(data["bars"].date == d["execution_date"]) & (data["bars"].instrument_id == "ETF_A")].copy()
    late["available_at"] = "2030-01-01T00:00:00+08:00"
    late["open"] = 100.
    data["bars"] = pd.concat([data["bars"], late], ignore_index=True)
    revised = run_backtest(data, [d], 100000)
    pd.testing.assert_frame_equal(original["fills"], revised["fills"])
    pd.testing.assert_frame_equal(original["nav"], revised["nav"])


def test_same_day_execution_rejected_and_stock_dividend_not_faked():
    data = fixture()
    d = decision(data)
    d["execution_date"] = d["decision_date"]
    with pytest.raises(ExecutionBlockedError, match="Execution must follow"):
        run_backtest(data, [d], 100000)
    data["instruments"].loc[data["instruments"].instrument_id == "ETF_A", "asset_type"] = "STOCK"
    ex = data["calendar"][23]
    data["actions"] = pd.DataFrame([dict(action_id="div", instrument_id="ETF_A", action_type="CASH_DIVIDEND",
        ex_date=ex, pay_date=ex, cash_per_share=1., available_at=ex + "T08:00:00+08:00")])
    with pytest.raises(ExecutionBlockedError, match="Stock dividend"):
        run_backtest(data, [], 100000)


def test_validation_start_keeps_history_but_no_earlier_account_positions():
    data = fixture()
    earlier = decision(data, 20)
    boundary = decision(data, 25, {"ETF_B": .3})
    start = boundary["execution_date"]
    result = run_backtest(data, [earlier, boundary], 100000, start_date=start)
    assert result["nav"].iloc[0].date == start
    assert set(result["fills"].instrument_id) == {"ETF_B"}
    assert result["orders"].iloc[0].decision_date < start
    assert result["orders"].iloc[0].adv20 == 100000000.


def test_blocked_sale_and_pending_buys_cannot_create_leverage():
    data = fixture(tuple("ABCDE"))
    first = decision(data, weights={"A": .33, "B": .33, "C": .33})
    rotate = decision(data, 22, {"C": .33, "D": .33, "E": .33})
    mask = (data["bars"].date >= rotate["execution_date"]) & data["bars"].instrument_id.isin(["A", "B"])
    data["bars"].loc[mask, "suspended"] = True
    result = run_backtest(data, [first, rotate], 1000000)
    assert result["nav"].cash_total.min() >= 0
    assert result["exposure"].query("scope == 'GROSS'").weight.max() <= 1
    assert result["fills"].query("side == 'SELL' and instrument_id in ['A', 'B']").empty
    additions = result["fills"].query("instrument_id in ['D','E']")
    assert additions.notional.sum() < 20000


def test_partial_sell_retries_have_one_minimum_commission_per_actual_order():
    data = fixture()
    buy, sell = decision(data), decision(data, 22, {})
    # Use a lower declared historical budget for this fixed sell intent. Each
    # later child recalculates actual historical ADV, so keep history low too.
    sell["adv20"]["ETF_A"] = 250000.
    after = data["bars"].date >= data["calendar"][22]
    data["bars"].loc[after, "amount"] = 250000.
    result = run_backtest(data, [buy, sell], 100000)
    sales = result["fills"].query("side == 'SELL'")
    assert len(sales) >= 2
    assert sales.order_id.is_unique
    assert sales.iloc[0].commission == 5
    assert result["costs"].order_id.is_unique


def test_unsupported_fractional_split_and_delisting_recovery_block():
    for factor, recovery, kind, reason in [(1.0001, 0, "SPLIT", "Fractional"), (1, 1, "DELISTING", "Positive delisting")]:
        data = fixture()
        ex = data["calendar"][23]
        data["actions"] = pd.DataFrame([dict(action_id="action", instrument_id="ETF_A", action_type=kind,
            ex_date=ex, share_factor=factor, recovery_per_share=recovery, available_at=ex + "T08:00:00+08:00")])
        with pytest.raises(ExecutionBlockedError, match=reason):
            run_backtest(data, [decision(data)], 100000)


def revise_instrument(data, sid, index, **updates):
    revision = data["instruments"].loc[data["instruments"].instrument_id == sid].iloc[[0]].copy()
    revision["available_at"] = data["calendar"][index] + "T20:00:00+08:00"
    for field, value in updates.items():
        revision[field] = value
    data["instruments"] = pd.concat([data["instruments"], revision], ignore_index=True)


@pytest.mark.parametrize("change,reason", [
    ({"account_verified": False}, "ETF_PERMISSION_UNVERIFIED"),
    ({"status": "SUSPENDED"}, "INSTRUMENT_STATUS_DENIED"),
    ({"delisted_on": "2020-02-25"}, "ANNOUNCED_DELISTING")])
def test_daily_qualification_exit_and_reentry_block_without_monthly_signal(change, reason):
    data = fixture()
    revise_instrument(data, "ETF_A", 23, **change)
    result = run_backtest(data, [decision(data), decision(data, 26)], 100000)
    sales = result["fills"].query("side == 'SELL'")
    assert len(sales) == 1
    assert sales.iloc[0].date == data["calendar"][24]
    risk_order = result["orders"].query("intent_type == 'RISK_EXIT'").iloc[0]
    assert risk_order.decision_date == data["calendar"][23]
    assert risk_order.risk_reason == reason
    assert result["fills"].query("side == 'BUY'").shape[0] == 1
    assert reason in set(result["rejected_orders"].reason)


def test_daily_exit_has_only_five_attempts_when_blocked_and_keeps_holding():
    data = fixture(days=60)
    revise_instrument(data, "ETF_A", 23, account_verified=False)
    mask = (data["bars"].date >= data["calendar"][24]) & (data["bars"].instrument_id == "ETF_A")
    data["bars"].loc[mask, "suspended"] = True
    result = run_backtest(data, [decision(data)], 100000)
    orders = result["orders"].query("intent_type == 'RISK_EXIT'")
    assert list(orders.attempt) == [1, 2, 3, 4, 5]
    assert len(result["order_events"].query("event == 'DAILY_RISK_EXIT'")) == 1
    assert result["positions"].iloc[-1].quantity > 0
    assert "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS" in set(result["rejected_orders"].reason)


def test_daily_exit_supersedes_delayed_partial_monthly_sale_and_sells_all():
    data = fixture()
    revise_instrument(data, "ETF_A", 23, account_verified=False)
    partial = decision(data, 22, {"ETF_A": .15}, delay=4)
    result = run_backtest(data, [decision(data), partial], 100000)
    sales = result["fills"].query("side == 'SELL'")
    buys = result["fills"].query("side == 'BUY'")
    assert len(sales) == 1 and sales.iloc[0].date == data["calendar"][24]
    assert sales.quantity.sum() == buys.quantity.sum()
    assert "SUPERSEDED_BY_DAILY_RISK_EXIT" in set(result["rejected_orders"].reason)


def test_daily_exit_adopts_existing_next_day_full_sell_without_duplicate():
    data = fixture()
    revise_instrument(data, "ETF_A", 23, account_verified=False)
    pending = decision(data, 22, {}, delay=2)
    result = run_backtest(data, [decision(data), pending], 100000)
    assert len(result["orders"].query("side == 'SELL'")) == 1
    assert len(result["fills"].query("side == 'SELL'")) == 1
    assert len(result["order_events"].query("event == 'DAILY_RISK_EXIT'")) == 1


def test_stock_missing_status_rejected_and_st_or_permission_change_allows_defensive_sell():
    rules = pd.DataFrame([dict(effective_from="2020-01-01", effective_to="2020-12-31",
        stamp_duty_sell=.001, transfer_fee_both=.00002, verified=True,
        source_url="https://example.test/synthetic-rule-not-legal-evidence")])
    data = fixture()
    data["instruments"]["asset_type"], data["instruments"]["board"] = "STOCK", "MAIN"
    weights = {"ETF_A": .04}
    missing = copy.deepcopy(data)
    missing["instruments"] = missing["instruments"].drop(columns="status")
    rejected = run_backtest(missing, [decision(missing, weights=weights)], 100000, tax_rules=rules)
    assert rejected["fills"].empty
    assert "INSTRUMENT_STATUS_DENIED" in set(rejected["rejected_orders"].reason)
    for change in ({"status": "ST", "is_st": True}, {"account_verified": False}, {"board": "STAR"}):
        case = copy.deepcopy(data)
        revise_instrument(case, "ETF_A", 23, **change)
        result = run_backtest(case, [decision(case, weights=weights)], 100000, tax_rules=rules)
        assert result["fills"].query("side == 'SELL'").iloc[0].date == data["calendar"][24]
        assert result["fills"].query("side == 'SELL'").quantity.sum() == result["fills"].query("side == 'BUY'").quantity.sum()


def liquidation_events(data, record=23, retire=24, recognize=24, pay=28, delist=32,
                       per_share=.77524, mode="SCHEDULED", final=True):
    dates = data["calendar"]
    source = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-03-28/512320_20240328_QIII.pdf"
    return pd.DataFrame([
        dict(action_id="liquidation", instrument_id="ETF_A", action_type="LIQUIDATION",
             record_date=dates[record], ex_date=dates[retire], available_at=dates[retire] + "T08:00:00+08:00",
             terms_verified=True, source_url=source),
        dict(action_id="installment1", instrument_id="ETF_A", action_type="LIQUIDATION_PAYMENT",
             entitlement_action_id="liquidation", installment_id="distribution-1",
             ex_date=dates[recognize], recognition_date=dates[recognize], pay_date=dates[pay],
             cash_per_share=per_share, is_final=final, settlement_mode=mode,
             cash_settlement_verified=mode != "ASSUMED_SCHEDULED_CREDIT",
             available_at=dates[recognize] + "T08:00:00+08:00", terms_verified=True, source_url=source),
        dict(action_id="delisting", instrument_id="ETF_A", action_type="DELISTING", ex_date=dates[delist],
             recovery_per_share=0., available_at=dates[delist] + "T08:00:00+08:00")])


def test_liquidation_before_delisting_retires_units_and_pays_once_on_actual_pay_date():
    data = fixture()
    data["bars"].loc[:, ["open", "close"]] = .8
    data["bars"].loc[:, ["high", "upper_limit"]] = 1.
    data["bars"].loc[:, ["low", "lower_limit"]] = .5
    data["actions"] = liquidation_events(data)
    # Reverse source row order: runtime must retire units before same-day payment recognition.
    data["actions"] = data["actions"].iloc[::-1].reset_index(drop=True)
    result = run_backtest(data, [decision(data)], 100000)
    fill = result["fills"].iloc[0]
    amount = round(fill.quantity * .77524, 2)
    nav = result["nav"].set_index("date")
    before_cash = 100000 - fill.notional - fill.fees
    ex, pay, delist = [data["calendar"][i] for i in (24, 28, 32)]
    assert nav.loc[ex, "holdings_value"] == 0
    assert nav.loc[ex, "receivables"] == amount
    assert nav.loc[ex, "cash_total"] == pytest.approx(before_cash)
    assert nav.loc[data["calendar"][27], "cash_total"] == pytest.approx(before_cash)
    assert nav.loc[pay, "cash_total"] == pytest.approx(before_cash + amount)
    assert nav.loc[pay, "receivables"] == 0
    assert nav.loc[pay, "nav"] == pytest.approx(nav.loc[delist, "nav"])
    rights = result["rights"].set_index("date")
    assert rights.loc[ex, "status"] == "FINAL_RECEIVABLE"
    assert rights.loc[pay, "status"] == "PAID_FINAL"
    assert rights.loc[delist, "entitled_quantity"] == fill.quantity
    position = result["positions"].query("date == @delist").iloc[0]
    assert position.quantity == 0 and position.retired_quantity == fill.quantity
    assert len(result["cash_events"].query("event == 'LIQUIDATION_PAID'")) == 1
    assert not result["nav"].valuation_uncertainty.any()


@pytest.mark.parametrize("buy_at,sell_at,expected_entitled", [(20, 21, False), (24, None, False), (20, 24, True)])
def test_liquidation_uses_record_date_not_current_or_postrecord_ownership(buy_at, sell_at, expected_entitled):
    data = fixture()
    data["actions"] = liquidation_events(data, record=23, retire=27, recognize=27)
    decisions = [decision(data, buy_at)]
    if sell_at is not None:
        decisions.append(decision(data, sell_at, {}))
    result = run_backtest(data, decisions, 100000)
    bought = result["fills"].query("side == 'BUY'").quantity.sum()
    payment = result["cash_events"].query("event == 'LIQUIDATION_PAID'").amount.sum()
    assert payment == (round(bought * .77524, 2) if expected_entitled else 0.)


def test_liquidation_payment_after_delisting_keeps_receivable_and_no_double_payment():
    data = fixture()
    data["actions"] = liquidation_events(data, pay=31, delist=26)
    result = run_backtest(data, [decision(data)], 100000)
    nav = result["nav"].set_index("date")
    assert nav.loc[data["calendar"][26], "receivables"] > 0
    assert nav.loc[data["calendar"][26], "nav"] == pytest.approx(nav.iloc[-1].nav)
    assert len(result["cash_events"].query("event == 'LIQUIDATION_PAID'")) == 1


def test_unknown_liquidation_recovery_remains_unpriced_until_announcement_prefix_stable():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=30, pay=32)
    decisions = [decision(data)]
    result = run_backtest(data, decisions, 100000)
    cutoff = data["calendar"][29]
    prefix = copy.deepcopy(data)
    prefix["calendar"] = prefix["calendar"][:30]
    earlier = run_backtest(prefix, decisions, 100000)
    pd.testing.assert_frame_equal(earlier["nav"], result["nav"].query("date <= @cutoff").reset_index(drop=True))
    before = result["nav"].query("date == @cutoff").iloc[0]
    assert before.receivables == 0 and before.valuation_uncertainty
    assert before.valuation_status == "CONSERVATIVE_UNPRICED_RIGHTS"
    recognized = result["nav"].iloc[30]
    assert recognized.receivables > 0
    assert recognized.cash_total == before.cash_total


def test_late_liquidation_observation_never_backfills_cash_and_is_flagged():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=32, pay=28, mode="LATE_RECOGNITION")
    result = run_backtest(data, [decision(data)], 100000)
    nav = result["nav"]
    assert nav.iloc[28].cash_total == nav.iloc[31].cash_total
    assert nav.iloc[32].cash_total > nav.iloc[31].cash_total
    assert nav.iloc[32].valuation_status == "OBSERVATION_TIME_REPLAY"
    assert nav.iloc[-1].valuation_uncertainty
    assert result["confirmation_eligible"] is False
    paid = result["cash_events"].query("event == 'LIQUIDATION_PAID'").iloc[0]
    assert paid.date == data["calendar"][32] and paid.actual_pay_date == data["calendar"][28]
    data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT", "settlement_mode"] = "SCHEDULED"
    with pytest.raises(ExecutionBlockedError, match="explicit late recognition"):
        run_backtest(data, [decision(data)], 100000)


def test_distinct_liquidation_installments_and_duplicate_or_after_final_rejected():
    data = fixture()
    data["actions"] = liquidation_events(data, recognize=25, pay=27, per_share=.5, final=False)
    second = data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT"].copy()
    second.loc[:, ["action_id", "installment_id", "cash_per_share", "is_final"]] = ["installment2", "distribution-2", .27524, True]
    second["ex_date"] = second["recognition_date"] = data["calendar"][28]
    second["pay_date"] = data["calendar"][30]
    second["available_at"] = data["calendar"][28] + "T08:00:00+08:00"
    data["actions"] = pd.concat([data["actions"], second], ignore_index=True)
    result = run_backtest(data, [decision(data)], 100000)
    assert len(result["cash_events"].query("event == 'LIQUIDATION_PAID'")) == 2
    assert result["rights"].iloc[-1].status == "PAID_FINAL"
    duplicate = copy.deepcopy(data)
    duplicate["actions"].loc[duplicate["actions"].action_id == "installment2", "installment_id"] = "distribution-1"
    with pytest.raises(ExecutionBlockedError, match="Duplicate installment"):
        run_backtest(duplicate, [decision(duplicate)], 100000)
    after_final = copy.deepcopy(data)
    after_final["actions"].loc[after_final["actions"].action_id == "installment1", "is_final"] = True
    with pytest.raises(ExecutionBlockedError, match="after final"):
        run_backtest(after_final, [decision(after_final)], 100000)


def test_liquidation_cancels_pending_orders_and_disallows_reentry_before_exchange_delist():
    data = fixture()
    data["actions"] = liquidation_events(data)
    result = run_backtest(data, [decision(data), decision(data, 23, {}), decision(data, 25)], 100000)
    assert len(result["fills"]) == 1
    reasons = set(result["rejected_orders"].reason)
    assert "ECONOMIC_LIQUIDATION_ORDER_CANCELLED" in reasons
    assert "ECONOMICALLY_RETIRED_INSTRUMENT" in reasons


def test_late_changed_liquidation_terms_block_instead_of_rewriting_history():
    data = fixture()
    data["actions"] = liquidation_events(data)
    revised = data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT"].copy()
    revised["available_at"] = data["calendar"][30] + "T08:00:00+08:00"
    revised["cash_per_share"] = .9
    data["actions"] = pd.concat([data["actions"], revised], ignore_index=True)
    with pytest.raises(ExecutionBlockedError, match="Post-effective corporate-action revision"):
        run_backtest(data, [decision(data)], 100000)
    prefix = copy.deepcopy(data)
    prefix["calendar"] = prefix["calendar"][:29]
    base = copy.deepcopy(prefix)
    base["actions"] = base["actions"].iloc[:-1]
    pd.testing.assert_frame_equal(run_backtest(prefix, [decision(prefix)], 100000)["nav"],
                                  run_backtest(base, [decision(base)], 100000)["nav"])


def test_assumed_distribution_credit_never_claims_verified_account_arrival():
    data = fixture()
    data["actions"] = liquidation_events(data, mode="ASSUMED_SCHEDULED_CREDIT")
    result = run_backtest(data, [decision(data)], 100000)
    cash_events = result["cash_events"].query("event in ['LIQUIDATION_RECEIVABLE', 'LIQUIDATION_PAID']")
    assert cash_events.actual_pay_date.isna().all()
    assert set(cash_events.scheduled_pay_date) == {data["calendar"][28]}
    assert result["nav"].iloc[27].cash_total < result["nav"].iloc[28].cash_total
    assert result["nav"].iloc[-1].valuation_status == "ASSUMED_SCHEDULED_CREDIT"
    assert result["nav"].iloc[-1].assumed_settlement
    assert result["rights"].iloc[-1].valuation_uncertainty
    assert result["accounting_timing_eligible"] is False
    assert result["confirmation_eligible"] is False
    data["actions"].loc[data["actions"].action_type == "LIQUIDATION_PAYMENT", "settlement_mode"] = "SCHEDULED"
    with pytest.raises(ExecutionBlockedError, match="verified account settlement"):
        run_backtest(data, [decision(data)], 100000)
