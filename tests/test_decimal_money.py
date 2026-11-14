"""Observed boundary counterexamples; not approximate equality to the bug."""
from decimal import Decimal

import pytest

from quant_research.execution import _charges, _product_money, _tick, run_backtest
from test_execution import fixture, decision


@pytest.mark.parametrize("multiplier,expected", [(1, 6.20), (2, 12.39), (3, 18.59)])
def test_commission_exact_half_cent_before_rounding(multiplier, expected):
    assert _charges(20650., True, (0., 0.), multiplier) == (expected, 0., 0.)


def test_odd_lot_notional_and_slippage_half_cent():
    assert _product_money(373, 2.695) == 1005.24
    assert _product_money(33775, abs(Decimal("2.579") - Decimal("2.58"))) == 33.78
    assert _product_money(373, .005) == 1.87  # dividend/entitlement uses the same primitive


def test_statutory_charges_do_not_multiply_with_commission_stress():
    assert _charges(20650., False, (.0003, .0001), 3) == (18.59, 6.20, 2.07)


def test_cash_and_fee_ledger_replay_half_cent_regression():
    data = fixture(names=("ETF_A",), days=25)
    data["bars"].loc[:, ["open", "close"]] = 2.95
    data["bars"].loc[:, ["high", "upper_limit"]] = 3.2
    data["bars"].loc[:, ["low", "lower_limit"]] = 2.7
    result = run_backtest(data, [decision(data, weights={"ETF_A": .2065})], 100000,
        cost_multiplier=3, slippage_multiplier=0)
    fill = result["fills"].iloc[0]
    assert fill.quantity == 7000 and fill.notional == 20650 and fill.commission == 18.59
    assert result["nav"].iloc[-1].nav == pytest.approx(99981.41, abs=1e-8)
    assert result["cash_events"].query("event == 'BUY'").iloc[0].amount == -20668.59


def test_exact_tick_at_registered_slippage_boundary():
    assert _tick(Decimal("10") * (1 + Decimal("0.0003")), .001, True) == 10.003
    assert _tick(Decimal("10") * (1 - Decimal("0.0003")), .001, False) == 9.997
