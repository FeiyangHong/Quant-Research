"""Independent synthetic counterexamples, not stock admission or performance.

Run from repository root with pytest; no author fixtures, network, final holdout,
source mutation, or real strategy runner are used.
"""
from copy import deepcopy
from decimal import Decimal

import pandas as pd
import pytest

from quant_research.equity_accounting import CashDividendTaxLedger, EquityAccountingBlocked, daily_limit_ratio
from quant_research.execution import ExecutionBlockedError, run_backtest


EVIDENCE = "https://example.invalid/independent-synthetic-evidence"


def ledger():
    return CashDividendTaxLedger("DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE")


def dividend(book, identifier, day, per_share="1"):
    book.record_dividend(identifier, "X", day, per_share,
        tax_category="ORDINARY_CASH_DIVIDEND", terms_verified=True, source_url=EVIDENCE)


def fixture():
    calendar = pd.bdate_range("2019-01-02", periods=30).strftime("%Y-%m-%d").tolist()
    master = dict(instrument_id="X", asset_type="STOCK", board="MAIN", listed_on="2000-01-01",
        delisted_on=None, account_verified=True, industry="C", lot_size=100, tick_size=.01,
        t_plus=1, status="NORMAL", is_st=False, available_at="2000-01-01T00:00:00+08:00")
    bars = [dict(date=day, instrument_id="X", open=20., high=21., low=19., close=20.,
        volume=10000000, amount=200000000, upper_limit=22., lower_limit=18., suspended=False,
        available_at=day + "T16:00:00+08:00") for day in calendar]
    return dict(calendar=calendar, instruments=pd.DataFrame([master]), bars=pd.DataFrame(bars),
                actions=pd.DataFrame(), manifest={"synthetic": True})


def decision(data, index=20, weight=.04):
    return dict(decision_date=data["calendar"][index], execution_date=data["calendar"][index + 1],
        weights={"X": weight} if weight else {}, reference_prices={"X": 20.}, adv20={"X": 200000000})


def fees():
    return [dict(effective_from="2016-01-01", effective_to="2024-12-31", stamp_duty_sell=.001,
        transfer_fee_both=.00002, verified=True, source_url=EVIDENCE,
        available_at="2015-01-01T00:00:00+08:00")]


def run(data, decisions=None, tax=None):
    return run_backtest(data, decisions or [decision(data)], 100000, tax_rules=fees() if tax is None else tax)


def test_fifo_two_distributions_and_intervening_repurchase():
    book = ledger()
    oldest = book.buy("X", 100, "2017-12-15")
    young = book.buy("X", 200, "2019-01-15")
    dividend(book, "D1", "2019-01-16")
    assert book.sell("X", 150, "2019-01-17")["lot_allocations"] == [(oldest, 100), (young, 50)]
    book.buy("X", 100, "2019-01-18")
    dividend(book, "D2", "2019-01-21", ".5")
    assert book.sell("X", 200, "2019-01-22")["amount"] == Decimal("50.00")
    assert book.tax_payable == Decimal("60.00")
    assert book.reserve("2019-01-23") == Decimal("65.00")
    assert sum(c["entitled_quantity"] for c in book.entitlements if c["action_id"] == "D1") == 300
    assert all(c["remaining"] == 0 for c in book.entitlements if c["action_id"] == "D1")
    book.settle_tax("T", "2019-01-23", "60", terms_verified=True, source_url=EVIDENCE,
                    mode="RULE_BASED_SIMULATION")
    assert book.reserve("2020-01-20") == 0
    assert book.tax_paid == 60 and book.events[-1]["actual_debit_date"] is None


@pytest.mark.parametrize("sale,expected", [("2019-02-15", "20"), ("2019-02-16", "10"),
                                          ("2020-01-15", "10"), ("2020-01-16", "0")])
def test_calendar_anniversary_after_excluding_disposal_day(sale, expected):
    book = ledger()
    book.buy("X", 100, "2019-01-15")
    dividend(book, "D", "2019-01-16")
    assert book.sell("X", 100, sale)["amount"] == Decimal(expected)


@pytest.mark.parametrize("purchase,record,sale", [("2019-01-31", "2019-02-01", "2019-03-01"),
    ("2020-02-29", "2020-03-02", "2021-03-02"), ("2020-08-31", "2020-09-01", "2020-09-02")])
def test_ambiguous_anniversary_fails_before_any_state_mutation(purchase, record, sale):
    book = ledger()
    book.buy("X", 100, purchase)
    dividend(book, "D", record)
    before = deepcopy(book.__dict__)
    with pytest.raises(EquityAccountingBlocked, match="anniversary"):
        book.sell("X", 100, sale)
    assert book.__dict__ == before


def test_individual_action_rounding_and_unpaid_liability_survive_aging():
    book = ledger()
    book.buy("X", 200, "2019-01-15")
    dividend(book, "A", "2019-01-16", ".00025")
    dividend(book, "B", "2019-01-17", ".00025")
    assert book.reserve("2019-01-18") == Decimal(".02")
    assert book.sell("X", 100, "2019-01-18")["amount"] == Decimal(".02")
    assert book.reserve("2019-01-19") == Decimal(".04")
    assert book.reserve("2020-01-16") == Decimal(".02")


@pytest.mark.parametrize("permission", [None, "true", 1, False])
def test_non_boolean_true_account_never_authorizes_new_risk(permission):
    data = fixture()
    data["instruments"]["account_verified"] = permission
    assert run(data)["fills"].empty


@pytest.mark.parametrize("is_st", [True, 1, "1"])
def test_st_flags_cannot_be_bypassed_by_type(is_st):
    data = fixture()
    data["instruments"]["is_st"] = is_st
    assert run(data)["fills"].empty, "Known/invalid ST flag must stop new risk, never silently become non-ST"


def test_permission_revoked_after_buy_sells_prior_day_holdings():
    data = fixture()
    update = data["instruments"].iloc[0].to_dict()
    update.update(account_verified=False, available_at=data["calendar"][22] + "T17:00:00+08:00")
    data["instruments"] = pd.concat([data["instruments"], pd.DataFrame([update])], ignore_index=True)
    result = run(data)
    assert list(result["fills"].side) == ["BUY", "SELL"]
    assert result["positions"].query("quantity > 0").date.max() == data["calendar"][22]


def test_invalid_st_flag_after_buy_triggers_risk_exit_without_deleting_holdings():
    data = fixture()
    update = data["instruments"].iloc[0].to_dict()
    update.update(is_st="1", available_at=data["calendar"][22] + "T17:00:00+08:00")
    data["instruments"] = pd.concat([data["instruments"], pd.DataFrame([update])], ignore_index=True)
    result = run(data)
    assert list(result["fills"].side) == ["BUY", "SELL"]
    assert result["positions"].query("quantity > 0").date.max() == data["calendar"][22]


@pytest.mark.parametrize("known,real", [(None, True), ("2019-02-01T10:00:00+08:00", False)])
def test_missing_real_or_future_tax_clock_blocks(known, real):
    data, schedule = fixture(), fees()
    data["manifest"]["synthetic"] = not real
    schedule[0]["available_at"] = known
    assert run(data, tax=schedule)["fills"].empty


def test_open_tax_rule_available_after_decision_applies_to_fill():
    data, schedule = fixture(), fees()
    schedule[0]["available_at"] = data["calendar"][21] + "T09:00:00+08:00"
    result = run(data)
    assert len(run(data, tax=schedule)["fills"]) == len(result["fills"]) == 1


@pytest.mark.parametrize("kind", ["CASH_DIVIDEND", "SPLIT", "RIGHTS_ISSUE", "ABSORPTION_MERGER"])
def test_unintegrated_equity_events_still_block(kind):
    data = fixture()
    day = data["calendar"][23]
    data["actions"] = pd.DataFrame([dict(action_id="X1", instrument_id="X", action_type=kind,
        ex_date=day, available_at=day + "T08:00:00+08:00", share_factor=2)])
    with pytest.raises(ExecutionBlockedError):
        run(data)


def test_master_delisting_alone_marks_zero_retains_rights_and_blocks_confirmation():
    data = fixture()
    update = data["instruments"].iloc[0].to_dict()
    update.update(delisted_on=data["calendar"][23], available_at=data["calendar"][23] + "T08:00:00+08:00")
    data["instruments"] = pd.concat([data["instruments"], pd.DataFrame([update])], ignore_index=True)
    result = run(data)
    end = result["positions"].iloc[-1]
    assert end.quantity == result["fills"].iloc[0].quantity and end.delisted_rights
    assert end.market_value == 0
    assert result["nav"].iloc[-1].valuation_uncertainty
    assert not result["accounting_timing_eligible"] and not result["confirmation_eligible"]


def test_one_day_stale_cannot_be_erased_by_later_fresh_mark():
    data = fixture()
    data["bars"] = data["bars"].loc[data["bars"].date != data["calendar"][23]]
    result = run(data)
    assert result["nav"].iloc[-1].valuation_status == "PRICED_LEDGER"
    assert not result["accounting_timing_eligible"]
    stale_row = result["nav"].loc[result["nav"].date == data["calendar"][23]].iloc[0]
    assert stale_row.valuation_status == "STALE_STOCK_MARK"
    assert result["positions"].stale_days.max() == 1


def test_chinext_legacy_delisting_and_unknown_status_are_not_normal_20_percent():
    args = dict(board="CHINEXT", day="2020-08-24", is_st=False, listed_on="2010-10-01",
                listing_session=2000, ipo_regime="APPROVAL")
    assert daily_limit_ratio(**args, delisting_started_on="2020-08-03") == Decimal(".10")
    args["is_st"] = None
    with pytest.raises(EquityAccountingBlocked):
        daily_limit_ratio(**args)
