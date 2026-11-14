"""Artificial prices below test mechanics only; they are not market evidence."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_research.strategy import StrategyBlockedError, generate_targets


@pytest.fixture
def market():
    dates = pd.bdate_range("2019-01-01", periods=450).strftime("%Y-%m-%d").tolist()
    masters, bars = [], []
    for number, name in enumerate("ABCDE", 1):
        masters.append(dict(instrument_id=name, asset_type="ETF", board="ETF",
                            listed_on=dates[0], delisted_on=None, account_verified=True,
                            available_at=dates[0] + "T09:00:00+08:00", benchmark_id="INDEX_" + name,
                            strategy_universe="R1B"))
        for index, day in enumerate(dates):
            price = 100 * np.exp(number * .0001 * index)
            bars.append(dict(date=day, instrument_id=name, close=price, total_return_index=price,
                             amount=40_000_000., suspended=False,
                             available_at=day + "T16:00:00+08:00", revision_id="v1"))
    benchmark = pd.DataFrame(dict(date=dates, total_return_index=100 * np.exp(np.arange(450) * .0002),
                                  available_at=[day + "T16:00:00+08:00" for day in dates]))
    return SimpleNamespace(calendar=dates, instruments=pd.DataFrame(masters),
                           bars=pd.DataFrame(bars), benchmark=benchmark)


def active(market, **kwargs):
    return [decision for decision in generate_targets(market, **kwargs) if decision.weights]


def test_registered_momentum_top3_month_end_and_delay(market):
    decisions = active(market, variant="R0")
    assert decisions
    decision = decisions[-1]
    assert list(decision.weights) == ["E", "D", "C"]
    assert list(decision.weights.values()) == pytest.approx([1 / 3] * 3)
    assert decision.diagnostics["momentum"]["E"] == pytest.approx(.0005 * (126 - 21))
    assert decision.decision_at.hour == 21
    assert str(decision.decision_at.tzinfo) == "Asia/Shanghai"
    for item in decisions:
        position = market.calendar.index(item.decision_date)
        assert market.calendar[position + 1] == item.execution_date
        assert item.decision_date[:7] != item.execution_date[:7]
    delayed = active(market, variant="R0", execution_delay=2)
    assert [(x.decision_date, x.weights) for x in decisions] == [(x.decision_date, x.weights) for x in delayed]
    assert all(market.calendar[market.calendar.index(x.decision_date) + 2] == x.execution_date for x in delayed)


def test_date_only_benchmark_releases_unchanged_anchor_formula_next_session(market):
    expected = generate_targets(market, variant="R1")
    positions = {day: i for i, day in enumerate(market.calendar)}
    market.benchmark["available_at"] = [
        (market.calendar[i + 1] if i + 1 < len(market.calendar) else "2030-01-01") + "T21:00:00+08:00"
        for i in range(len(market.calendar))]
    actual = generate_targets(market, variant="R1", signal_release_delay=1)
    by_anchor = {row.decision_date: row for row in expected}
    for row in actual:
        anchor = row.diagnostics["signal_anchor_date"]
        assert row.weights == by_anchor[anchor].weights
        assert row.status == by_anchor[anchor].status
        assert row.decision_date == market.calendar[positions[anchor] + 1]
        assert row.execution_date == market.calendar[positions[anchor] + 2]
        assert row.decision_at.hour == 21


def test_release_day_returns_cannot_change_anchor_signal_but_prices_size_orders(market):
    before = active(market, variant="R1", signal_release_delay=1)[-1]
    day = before.decision_date
    # These observations arrive after the economic month-end. They are legal
    # order references, but cannot enter the momentum/trend/risk window.
    mask = market.bars.date.eq(day)
    market.bars.loc[mask & market.bars.instrument_id.eq("A"), "total_return_index"] = 1e20
    market.bars.loc[mask, "close"] *= 2
    market.benchmark.loc[market.benchmark.date.eq(day), "total_return_index"] = 1e20
    after = active(market, variant="R1", signal_release_delay=1)[-1]
    assert after.weights == before.weights
    assert after.diagnostics["momentum"] == before.diagnostics["momentum"]
    assert after.diagnostics["trend"] == before.diagnostics["trend"]
    assert after.reference_prices == {code: value * 2 for code, value in before.reference_prices.items()}


def test_momentum_skips_latest_21_sessions(market):
    before = active(market, variant="R0")[-1]
    position = market.calendar.index(before.decision_date)
    mask = market.bars.instrument_id.eq("A") & market.bars.date.isin(market.calendar[position - 20:position + 1])
    market.bars.loc[mask, "total_return_index"] *= 100
    after = active(market, variant="R0")[-1]
    assert after.weights == before.weights
    assert after.diagnostics["momentum"] == before.diagnostics["momentum"]


def test_trend_strict_sma_cash_is_explicit_decision(market):
    ordinary = active(market, variant="E0")[-1]
    assert ordinary.weights == {name: .2 for name in "ABCDE"}
    assert active(market, variant="E1")[-1].weights == ordinary.weights
    market.benchmark["total_return_index"] = 100.
    gated = generate_targets(market, variant="E1")[-1]
    assert gated.decision_date == ordinary.decision_date
    assert gated.weights == {}
    assert gated.status == "CASH_TREND_OFF"
    assert set(gated.reference_prices) == set("ABCDE")
    assert active(market, variant="E0")[-1].weights == ordinary.weights


def test_eligibility_252_sessions_and_median_liquidity(market):
    decisions = active(market)
    assert all(market.calendar.index(item.decision_date) >= 251 for item in decisions)
    day = decisions[-1].decision_date
    position = market.calendar.index(day)
    recent = market.calendar[position - 19:position + 1]
    mask = market.bars.instrument_id.eq("A") & market.bars.date.isin(recent)
    market.bars.loc[mask, "amount"] = 1_000_000.
    market.bars.loc[mask & market.bars.date.eq(day), "amount"] = 1_000_000_000.
    last = active(market)[-1]
    assert "A" not in last.weights  # Mean passes 20m, but the registered median fails.
    assert last.diagnostics["exclusions"]["A"] == "insufficient_20_session_liquidity"


def add_duplicate(market, listed_on=None):
    row = market.instruments.iloc[0].copy()
    row["instrument_id"] = "Z"
    row["listed_on"] = listed_on or row["listed_on"]
    market.instruments = pd.concat([market.instruments, row.to_frame().T], ignore_index=True)
    clone = market.bars.loc[market.bars.instrument_id.eq("A")].copy()
    clone["instrument_id"] = "Z"
    market.bars = pd.concat([market.bars, clone], ignore_index=True)


def test_quarter_representative_frozen_using_previous_quarter(market):
    add_duplicate(market)
    z = market.bars.instrument_id.eq("Z")
    market.bars.loc[z & market.bars.date.le("2020-03-31"), "amount"] = 60_000_000.
    market.bars.loc[z & market.bars.date.gt("2020-03-31"), "amount"] = 30_000_000.
    targets = {item.decision_date: item for item in active(market)}
    for day in ["2020-04-30", "2020-05-29", "2020-06-30"]:
        assert "Z" in targets[day].weights and "A" not in targets[day].weights
        assert targets[day].diagnostics["representative_at"] == "2020-03-31"
    assert "A" in targets["2020-07-31"].weights


def test_representative_ties_listing_date_then_identifier(market):
    add_duplicate(market, "2018-01-01")
    assert "Z" in active(market)[-1].weights
    market.instruments.loc[market.instruments.instrument_id.eq("Z"), "listed_on"] = market.calendar[0]
    assert "A" in active(market)[-1].weights
    assert "Z" not in active(market)[-1].weights


def test_ranking_ties_identifier_and_etf_permission_independent_of_underlying(market):
    market.bars["total_return_index"] = 100.
    market.instruments.loc[market.instruments.instrument_id.eq("A"), "board"] = "STAR"
    assert list(active(market, variant="R0")[-1].weights) == ["A", "B", "C"]
    market.instruments.loc[market.instruments.instrument_id.eq("A"), "asset_type"] = "STOCK"
    market.instruments.loc[market.instruments.instrument_id.eq("B"), "account_verified"] = False
    assert set(active(market)[-1].weights) == set("CDE")


def test_fewer_than_three_caps_equal_weight_and_blocks_top3(market):
    market.instruments.loc[market.instruments.instrument_id.isin(list("CDE")), "account_verified"] = False
    last = active(market)[-1]
    assert last.weights == {"A": .35, "B": .35}
    assert last.diagnostics["top3_comparable"] is False
    top3 = generate_targets(market, variant="R0")[-1]
    assert top3.weights == {}
    assert top3.status == "BLOCKED_INSUFFICIENT_ETFS"


def test_prefix_invariance_future_prices_metadata_and_late_revisions(market):
    cutoff = "2020-06-10"
    prefix = deepcopy(market)
    prefix.calendar = [date for date in prefix.calendar if date <= cutoff]
    prefix.bars = prefix.bars.loc[prefix.bars.date.le(cutoff)].copy()
    prefix.benchmark = prefix.benchmark.loc[prefix.benchmark.date.le(cutoff)].copy()
    before = generate_targets(prefix, variant="R1", risk_scaling=True)
    future = market.bars.date.gt(cutoff)
    market.bars.loc[future, ["close", "total_return_index", "amount"]] *= 123
    revision = market.bars.loc[market.bars.instrument_id.eq("E") & market.bars.date.lt(cutoff)].copy()
    revision["available_at"] = "2021-01-01T16:00:00+08:00"
    revision["revision_id"] = "late"
    revision[["total_return_index", "amount"]] *= 99
    market.bars = pd.concat([market.bars, revision], ignore_index=True)
    master_revision = market.instruments.iloc[[0]].copy()
    master_revision["available_at"] = "2021-01-01T16:00:00+08:00"
    master_revision["account_verified"] = False
    market.instruments = pd.concat([market.instruments, master_revision], ignore_index=True)
    after = [item for item in generate_targets(market, variant="R1", risk_scaling=True)
             if item.execution_date <= cutoff]
    assert before == after


def test_after_21_quote_excluded_and_missing_benchmark_blocks(market):
    day = active(market)[-1].decision_date
    mask = market.bars.date.eq(day) & market.bars.instrument_id.eq("A")
    market.bars.loc[mask, "available_at"] = day + "T22:00:00+08:00"
    last = active(market)[-1]
    assert "A" not in last.weights and "A" not in last.reference_prices
    market.benchmark.loc[market.benchmark.date.eq(day), "available_at"] = day + "T22:00:00+08:00"
    last = generate_targets(market, variant="E1")[-1]
    assert last.status == "BLOCKED_BENCHMARK_HISTORY"
    assert last.weights == {}


def test_covariance_half_diagonal_60_sessions_and_no_leverage(market):
    day = active(market)[-1].decision_date
    position = market.calendar.index(day)
    rng = np.random.default_rng(671)
    innovations = rng.normal(0, .045, (len(market.calendar) - 1, 5))
    innovations += rng.normal(0, .02, (len(market.calendar) - 1, 1))
    for number, name in enumerate("ABCDE"):
        market.bars.loc[market.bars.instrument_id.eq(name), "total_return_index"] = np.r_[100., 100 * np.cumprod(1 + innovations[:, number])]
    last = active(market, risk_scaling=True)[-1]
    covariance = np.cov(innovations[position - 60:position], rowvar=False, ddof=1)
    expected_sigma = np.sqrt(252 * np.full(5, .2) @ (.5 * covariance + .5 * np.diag(np.diag(covariance))) @ np.full(5, .2))
    assert last.diagnostics["complete_risk_sessions"] == 60
    assert last.diagnostics["annualized_sigma"] == pytest.approx(expected_sigma)
    assert sum(last.weights.values()) == pytest.approx(.1 / expected_sigma)
    market.bars["total_return_index"] = 100.
    assert sum(active(market, risk_scaling=True)[-1].weights.values()) == pytest.approx(1.)


@pytest.mark.parametrize("missing_days,expected_count,blocked", [(14, 45, False), (15, 44, True)])
def test_risk_requires_45_complete_synchronous_returns(market, missing_days, expected_count, blocked):
    day = active(market)[-1].decision_date
    position = market.calendar.index(day)
    missing = market.calendar[position - 40:position - 40 + missing_days]
    market.bars.loc[market.bars.instrument_id.eq("A") & market.bars.date.isin(missing), "total_return_index"] = np.nan
    last = generate_targets(market, risk_scaling=True)[-1]
    assert last.diagnostics["complete_risk_sessions"] == expected_count
    assert (last.status == "BLOCKED_RISK_HISTORY") is blocked
    assert bool(last.weights) is not blocked


def test_future_known_delisting_retains_history_and_no_intraquarter_substitute(market):
    add_duplicate(market)
    day = "2020-05-01"
    revised = market.instruments.loc[market.instruments.instrument_id.eq("A")].copy()
    revised["delisted_on"] = day
    revised["available_at"] = "2020-04-15T10:00:00+08:00"
    market.instruments = pd.concat([market.instruments, revised], ignore_index=True)
    targets = {item.decision_date: item for item in active(market)}
    assert "A" in targets["2020-03-31"].weights
    assert "A" not in targets["2020-05-29"].weights
    assert "Z" not in targets["2020-05-29"].weights
    assert "Z" in targets["2020-07-31"].weights


def test_missing_pit_industry_and_unsafe_timestamps_block(market):
    with pytest.raises(StrategyBlockedError, match="PIT industry"):
        generate_targets(market, universe="R1I")
    with pytest.raises(ValueError, match="execution_delay"):
        generate_targets(market, execution_delay=0)
    market.bars.loc[0, "available_at"] = "2019-01-01T16:00:00"
    with pytest.raises(StrategyBlockedError, match="timezone"):
        generate_targets(market)
