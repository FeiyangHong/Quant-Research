"""Reviewer-owned synthetic scope, clock, competitor and ledger checks."""
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_research.liquid_cohort import generate_liquid_targets, liquid_dependencies
from quant_research.execution import run_backtest
from quant_research.strategy import StrategyBlockedError

SCOPE = "R1I_HISTORICAL_LIQUID_V1"
IDS = ["SYNTH_" + letter for letter in "ABCDEF"]


def fixture(eligible=4):
    # Synthetic older sessions; the Jan/Feb2020 clock explicitly models the
    # documented last January session and February reopening, no market returns.
    days = pd.bdate_range("2018-01-02", "2020-02-05").strftime("%Y-%m-%d").tolist()
    days = [d for d in days if d != "2020-01-01" and not "2020-01-24" <= d <= "2020-01-31"]
    masters, bars = [], []
    for j, sid in enumerate(IDS):
        masters.append(dict(instrument_id=sid, asset_type="ETF", board="ETF", listed_on=days[0],
            delisted_on=None, available_at="2018-01-01T21:00:00+08:00", account_verified=True,
            status="NORMAL", benchmark_id="INDEX_" + sid, strategy_universe=SCOPE,
            lot_size=100, tick_size=.001, t_plus=1, revision_id=sid, supersedes_id=None))
        for i, day in enumerate(days):
            bars.append(dict(instrument_id=sid, date=day, open=5., close=5., high=5.1, low=4.9,
                upper_limit=5.5, lower_limit=4.5, volume=10000000, amount=50000000 if j < eligible else 10000000,
                suspended=False, total_return_index=100 * np.exp(-(6-j) * .0001 * i),
                available_at=day + "T16:00:00+08:00"))
    return SimpleNamespace(calendar=days, instruments=pd.DataFrame(masters), bars=pd.DataFrame(bars),
        actions=pd.DataFrame(), benchmark=pd.DataFrame(dict(date=days,
            total_return_index=100 + np.arange(len(days)), available_at=[d+"T16:00:00+08:00" for d in days])),
        manifest=dict(research_scope=SCOPE, synthetic=True, cohort_selection=dict(status="FORMED",
            scope=SCOPE, sampling_frame_sha256="55b7b554d5e785b91a743960dec5f84f45bfdac13c70f191fd5f71c308e58b7a",
            formation_date="2019-12-31", cohort_available_at="2020-01-02T21:00:00+08:00", selected_instruments=IDS)))


def first(data, variant="R0", delay=1):
    return next(t for t in generate_liquid_targets(data, variant, delay)
                if t.diagnostics["signal_anchor_date"] == "2020-01-23")


def test_formation_and_first_month_clock_negative_momentum_and_delay():
    data = fixture()
    all_targets = generate_liquid_targets(data, "R0")
    assert all(t.weights == {} for t in all_targets if t.diagnostics["signal_anchor_date"] < "2020-01-23")
    t = first(data)
    assert t.decision_date == "2020-02-03" and t.execution_date == "2020-02-04"
    assert list(t.weights) == IDS[1:4]
    assert t.diagnostics["momentum"][IDS[0]] == pytest.approx(-6*.0001*105)
    assert all(v < 0 for v in t.diagnostics["momentum"].values())
    late = first(data, delay=2)
    assert late.execution_date == "2020-02-05" and late.weights == t.weights
    assert late.diagnostics["momentum"] == t.diagnostics["momentum"]
    changed = deepcopy(data)
    mask = changed.bars.date.eq("2020-02-03")
    changed.bars.loc[mask, "close"] = 7
    changed.bars.loc[mask, "total_return_index"] = 1e30
    assert first(changed).weights == t.weights
    assert first(changed).diagnostics["momentum"] == t.diagnostics["momentum"]
    assert set(first(changed).reference_prices.values()) == {7.}


@pytest.mark.parametrize("field", ["missing_competitor_TR", "late_competitor_TR", "missing_amount", "unknown_permission", "unknown_status"])
def test_missing_competitor_never_becomes_low_rank_or_cash(field):
    data = fixture()
    mask = data.bars.instrument_id.eq(IDS[0])
    if field == "missing_competitor_TR":
        data.bars.loc[mask, "total_return_index"] = np.nan
    elif field == "late_competitor_TR":
        data.bars["total_return_available_at"] = data.bars.available_at
        data.bars.loc[mask, "total_return_available_at"] = "2020-02-04T21:00:00+08:00"
    elif field == "missing_amount":
        data.bars.loc[mask & data.bars.date.eq("2020-01-22"), "amount"] = np.nan
    elif field == "unknown_permission":
        data.instruments.loc[0, "account_verified"] = False
    else:
        data.instruments.loc[0, "status"] = "UNKNOWN"
    # SYNTH_A loses the momentum ranking, but E0 and R0 must both block.
    for variant in ("E0", "R0"):
        with pytest.raises(StrategyBlockedError):
            generate_liquid_targets(data, variant)


def test_formation_sixty_sessions_does_not_allow_trading_before252():
    data = fixture(6)
    # At formation product F has exactly60 synthetic sessions, January has77.
    formation = data.calendar.index("2019-12-31")
    data.instruments.loc[5, "listed_on"] = data.calendar[formation-59]
    dependency = next(r for r in liquid_dependencies(data)["schedule"] if r["anchor_date"] == "2020-01-23")
    assert dependency["eligible_count"] == 5
    assert dependency["exclusions"][IDS[5]] == "LISTED_LESS_THAN_252_SESSIONS"
    assert IDS[5] not in first(data, "E0").weights


@pytest.mark.parametrize("mutation", ["old_seven", "early_clock", "five_products", "missing_status", "holdout"])
def test_new_scope_requires_frozen_new_selection_and_locked_calendar(mutation):
    data = fixture()
    if mutation == "old_seven":
        data.manifest["cohort_selection"]["selected_instruments"] = ["sz."+s for s in ("159936","159938","159939","159940","159944","159945","159946")]
    elif mutation == "early_clock":
        data.manifest["cohort_selection"]["cohort_available_at"] = "2019-12-31T21:00:00+08:00"
    elif mutation == "five_products":
        data.manifest["cohort_selection"]["selected_instruments"] = IDS[:5]
    elif mutation == "missing_status":
        data.manifest["cohort_selection"].pop("status")
    else:
        data.calendar += ["2025-01-02"]
    with pytest.raises(StrategyBlockedError):
        generate_liquid_targets(data)


@pytest.mark.parametrize("cost", [1,2,3])
def test_three_products_same_orders_and_decimal_account(cost):
    data = fixture(3)
    e = generate_liquid_targets(data, "E0")
    r = generate_liquid_targets(data, "R0")
    assert e[-1].weights == r[-1].weights == dict.fromkeys(IDS[:3], 1/3)
    assert e[-1].ranks == r[-1].ranks
    results = [run_backtest(data, targets, 100000, cost_multiplier=cost,
        slippage_multiplier=cost, start_date="2020-01-01") for targets in (e,r)]
    for name in ("orders", "fills", "positions", "nav"):
        pd.testing.assert_frame_equal(results[0][name], results[1][name])
    q = 6600
    price = (Decimal(5)*(1+Decimal(".0003")*cost)/Decimal(".001")).to_integral_value(rounding=ROUND_CEILING)*Decimal(".001")
    notional = (q*price).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    fee = (max(Decimal(5),notional*Decimal(".0003"))*cost).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    cash = Decimal(100000)-3*(notional+fee)
    assert list(results[0]["fills"].quantity) == [q,q,q]
    for row in results[0]["nav"].to_dict("records"):
        expect_cash = Decimal(100000) if row["date"] < "2020-02-04" else cash
        expect_holdings = Decimal(0) if row["date"] < "2020-02-04" else Decimal(3*q*5)
        assert row["cash_total"] == pytest.approx(float(expect_cash), abs=1e-7)
        assert row["nav"] == pytest.approx(float(expect_cash+expect_holdings), abs=1e-7)


def test_n2_cash_proof_preserves_unknown_and_strict_trend_equality():
    data = fixture(2)
    data.bars["total_return_index"] = np.nan
    assert liquid_dependencies(data)["required_full_history_instruments"] == []
    assert all(t.weights == {} for t in generate_liquid_targets(data))
    data = fixture()
    data.benchmark["total_return_index"] = 100.
    assert first(data, "E1").weights == first(data, "R1").weights == {}
