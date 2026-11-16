"""M8 regressions: known intentions versus realized shared matching capacity."""
from decimal import Decimal

import pandas as pd
import pytest

from quant_research.execution import run_backtest
from test_execution import decision, fixture


def set_day(data, day, **values):
    mask = (data["bars"].date == day) & (data["bars"].instrument_id == "ETF_A")
    for key, value in values.items():
        data["bars"].loc[mask, key] = value


def test_original_over_market_counterexample_preserves_intent_but_cannot_fill_lot():
    normal = fixture(("ETF_A",))
    normal["bars"]["amount"] = 10000000.
    normal["bars"]["volume"] = 1000000.
    normal["bars"][["high", "low"]] = [10.01, 9.99]
    small = dict(normal, bars=normal["bars"].copy())
    intent = decision(normal)
    set_day(small, intent["execution_date"], volume=1000., amount=10000.)
    control = run_backtest(normal, [intent], 100000)
    actual = run_backtest(small, [intent], 100000)
    pd.testing.assert_frame_equal(actual["orders"], control["orders"])
    assert actual["orders"].iloc[0].quantity == 3000
    assert control["fills"].iloc[0].quantity == 3000
    assert control["fills"].iloc[0].notional == 30009
    assert actual["fills"].empty and actual["nav"].iloc[-1].cash == 100000
    assert actual["rejected_orders"].iloc[0].reason == "ACTUAL_DAY_AMOUNT_CAPACITY"
    assert actual["mode"] == "DAILY_SCREEN_ONLY"


@pytest.mark.parametrize("adv,volume,amount,expected,reason", [
    (250000., 10000000., 100000000., 200, "HISTORICAL_ADV_CAPACITY"),
    (100000000., 10000000., 1000000., 900, "ACTUAL_DAY_AMOUNT_CAPACITY"),
    (100000000., 100000., 100000000., 1000, "ACTUAL_DAY_VOLUME_CAPACITY"),
])
def test_each_capacity_dimension_can_independently_bind(adv, volume, amount, expected, reason):
    data = fixture(("ETF_A",))
    data["bars"]["amount"] = adv
    intent = decision(data)
    set_day(data, intent["execution_date"], volume=volume, amount=amount)
    result = run_backtest(data, [intent], 100000)
    assert result["fills"].quantity.tolist() == [expected]
    assert reason in set(result["rejected_orders"].reason)
    assert result["orders"].iloc[0].quantity == 3000


@pytest.mark.parametrize("field,invalid", [
    (field, invalid) for field in ("amount", "volume")
    for invalid in (None, float("nan"), float("inf"), 0., -1.)
])
def test_invalid_realized_liquidity_never_grants_capacity(field, invalid):
    data = fixture(("ETF_A",))
    intent = decision(data)
    set_day(data, intent["execution_date"], **{field: invalid})
    result = run_backtest(data, [intent], 100000)
    assert result["orders"].iloc[0].quantity == 3000
    assert result["fills"].empty
    assert "NO_MARKET_TRADING" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("field,value,expected", [
    ("volume", 150000., [1000, 500]),
    ("amount", 1500000., [1000, 400]),
])
def test_queued_buy_orders_cannot_reuse_day_capacity(field, value, expected):
    data = fixture(("ETF_A",))
    first = decision(data, 20, {"ETF_A": .1}, delay=3)
    second = decision(data, 21, {"ETF_A": .1}, delay=2)
    set_day(data, first["execution_date"], **{field: value})
    result = run_backtest(data, [first, second], 100000)
    assert result["orders"].quantity.tolist() == [1000, 1000]
    assert result["fills"].quantity.tolist() == expected
    events = result["order_events"].query("event == 'DAILY_CAPACITY'")
    assert events.actual_shares_consumed.tolist() == [expected[0], sum(expected)]


def test_all_orders_share_smallest_known_historical_budget():
    data = fixture(("ETF_A",))
    first = decision(data, 20, {"ETF_A": .1}, delay=3)
    first["adv20"]["ETF_A"] = 1500000.
    second = decision(data, 21, {"ETF_A": .1}, delay=2)
    result = run_backtest(data, [first, second], 100000)
    assert result["fills"].quantity.tolist() == [1000, 400]
    events = result["order_events"].query("event == 'DAILY_CAPACITY'")
    assert events.historical_limit.tolist() == [15000., 15000.]
    assert events.iloc[-1].historical_consumed == 14004.2


@pytest.mark.parametrize("dimension", ["volume", "amount", "historical"])
def test_buys_and_sells_consume_absolute_shared_daily_capacity(dimension):
    data = fixture(("ETF_A",))
    initial = decision(data)
    addition = decision(data, 22, {"ETF_A": .34}, delay=3)
    sale = decision(data, 23, {}, delay=2)
    if dimension == "historical":
        addition["adv20"]["ETF_A"] = 3200000.
    else:
        set_day(data, sale["execution_date"], **{dimension: 320000. if dimension == "volume" else 3200000.})
    result = run_backtest(data, [initial, addition, sale], 100000,
                          cost_multiplier=0, slippage_multiplier=0)
    day = sale["execution_date"]
    fills = result["fills"].query("date == @day")
    assert fills.side.tolist() == ["SELL", "BUY"]
    assert fills.quantity.tolist() == [3000, 200]
    assert fills.notional.sum() == 32000.
    events = result["order_events"].query("event == 'DAILY_CAPACITY' and date == @day")
    assert events.iloc[-1].actual_shares_consumed == 3200


def test_capacity_resets_next_day_and_five_partial_sells_retain_inventory():
    data = fixture(("ETF_A",))
    initial, sale = decision(data), decision(data, 22, {})
    data["bars"].loc[data["bars"].date >= sale["execution_date"], "volume"] = 50000.
    result = run_backtest(data, [initial, sale], 100000)
    sells = result["fills"].query("side == 'SELL'")
    assert sells.quantity.tolist() == [500] * 5
    assert sells.commission.tolist() == [5.] * 5
    assert sells.date.is_unique and sells.order_id.is_unique
    assert result["positions"].iloc[-1].quantity == 500
    assert "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS" in set(result["rejected_orders"].reason)


def test_conservative_historical_consumption_uses_higher_reference_on_gap_down():
    data = fixture(("ETF_A",))
    intent = decision(data)
    intent["adv20"]["ETF_A"] = 2000000.
    set_day(data, intent["execution_date"], open=9.5, close=9.5)
    result = run_backtest(data, [intent], 100000)
    assert result["fills"].quantity.tolist() == [2000]
    assert result["fills"].iloc[0].price == 9.503
    event = result["order_events"].query("event == 'DAILY_CAPACITY'").iloc[0]
    assert event.historical_consumed == 20000.


def test_decimal_amount_boundary_does_not_round_up_odd_lot_past_budget():
    data = fixture(("ETF_A",))
    buy = decision(data, 20, {"ETF_A": .03})
    split_day = data["calendar"][22]
    data["actions"] = pd.DataFrame([dict(action_id="synthetic_split", instrument_id="ETF_A",
        action_type="SPLIT", ex_date=split_day, share_factor=1.01, recovery_per_share=0.,
        available_at=split_day + "T08:00:00+08:00")])
    sale = decision(data, 23, {})
    # 303 * 9.999 = 3029.697, but cash notional rounds to 3029.70.
    set_day(data, sale["execution_date"], amount=302969.7)
    result = run_backtest(data, [buy, sale], 100000, slippage_multiplier=Decimal("0.1"))
    day = sale["execution_date"]
    fills = result["fills"].query("date == @day and side == 'SELL'")
    assert fills.quantity.tolist() == [300]
    assert Decimal(str(fills.notional.sum())) <= Decimal("3029.697")
