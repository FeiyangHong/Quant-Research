"""Additional reviewer-authored M4 counterexamples; invented inputs only."""
from decimal import Decimal
from itertools import permutations

import pandas as pd
import pytest

from quant_research.engineering_replay import REPLAY_TAG, synthetic_fixture
from quant_research.execution import ExecutionBlockedError, run_backtest
from quant_research.temporal import master_record, TemporalStateError


def state(identity, start, known, **extra):
    return dict(instrument_id="A", revision_id=identity, effective_from=start,
                available_at=known, **extra)


def test_selection_is_order_invariant_with_old_correction_and_future_transition():
    rows = [state("a", "2020-01-01", "2019-12-01T00:00:00+08:00"),
            state("b", "2020-02-01", "2020-01-15T00:00:00+08:00", supersedes_id="a"),
            state("a2", "2020-01-01", "2020-01-20T00:00:00+08:00",
                  supersedes_id="a", effective_to="2020-01-25")]
    for ordered in permutations(rows):
        assert master_record(ordered, "2020-01-21T00:00:00+08:00")["revision_id"] == "a2"
        assert master_record(ordered, "2020-01-25T00:00:00+08:00") is None
        assert master_record(ordered, "2020-02-01T00:00:00+08:00")["revision_id"] == "b"


@pytest.mark.parametrize("kind", ["branch", "duplicate", "future_parent", "unpublished_parent"])
def test_visible_invalid_lineage_fails_closed(kind):
    rows = [state("a", "2020-01-01", "2019-12-01T00:00:00+08:00"),
            state("a2", "2020-01-01", "2020-01-20T00:00:00+08:00", supersedes_id="a")]
    if kind == "branch":
        rows.append(state("a3", "2020-01-01", "2020-01-21T00:00:00+08:00", supersedes_id="a"))
    elif kind == "duplicate":
        rows[1]["revision_id"] = "a"
    elif kind == "future_parent":
        rows[0]["available_at"] = "2020-01-22T00:00:00+08:00"
    else:
        rows[0]["available_at"] = "2020-03-01T00:00:00+08:00"
    with pytest.raises(TemporalStateError):
        master_record(rows, "2020-02-01T00:00:00+08:00")


@pytest.mark.parametrize("child_identity", [None, ""])
def test_correction_links_require_stable_child_identity(child_identity):
    rows = [state("a", "2020-01-01", "2019-12-01T00:00:00+08:00"),
            state(child_identity, "2020-01-01", "2020-01-20T00:00:00+08:00", supersedes_id="a")]
    with pytest.raises(TemporalStateError):
        master_record(rows, "2020-02-01T00:00:00+08:00")
    # Backward-compatible unversioned fixtures contain no lineage assertion.
    assert master_record([state(None, None, "2019-12-01T00:00:00+08:00")],
                         "2020-02-01T00:00:00+08:00") is not None


def test_unknown_explicit_revision_kind_cannot_silently_select_transition_semantics():
    rows = [state("a", "2020-01-01", "2019-12-01T00:00:00+08:00"),
            state("b", "2020-02-01", "2020-01-15T00:00:00+08:00",
                  supersedes_id="a", revision_kind="CORRECTON")]
    # Missing kind can use the established lifecycle inference. An explicit
    # unrecognized kind cannot safely assert which supersession clock to use.
    with pytest.raises(TemporalStateError):
        master_record(rows, "2020-01-20T00:00:00+08:00")


def test_partial_fifo_sale_before_dividend_cash_new_buy_gets_no_old_claim():
    data, orders = synthetic_fixture()
    sid, days = data["instruments"].iloc[0].instrument_id, data["calendar"]
    data["actions"] = data["actions"].iloc[:1].copy()
    data["tax_settlements"] = []
    instructions = orders[:2]
    for index, target in [(25, 100), (28, 300), (40, 0)]:
        instructions.append(dict(decision_date=days[index], execution_date=days[index + 1],
            weights={sid: .04} if target else {}, reference_prices={sid: 10.},
            adv20={sid: 1e8}, fixed_quantities={sid: target}))
    result = run_backtest(data, instructions, 100000, slippage_multiplier=0, engineering_replay=True)
    assert list(zip(result["fills"].side, result["fills"].quantity)) == [
        ("BUY", 200), ("BUY", 200), ("SELL", 300), ("BUY", 200), ("SELL", 300)]
    nav = result["nav"].set_index("date")
    assert nav.loc[days[26], "receivables"] == 100
    assert nav.loc[days[26], "dividend_tax_payable"] == 15
    assert nav.loc[days[26], "cash_reserved"] == 20
    assert nav.loc[days[27], "receivables"] == 0
    assert nav.loc[days[29], "cash_reserved"] == 20
    assert nav.loc[days[41], "dividend_tax_payable"] == 20
    assert nav.loc[days[41], "cash_reserved"] == 20
    final_claims = result["dividend_entitlements"].query("date == @days[-1]")
    assert final_claims.entitled_quantity.sum() == 400
    assert final_claims.remaining.sum() == 0
    assert set(final_claims.lot_id) == {"L00000001", "L00000002"}
    assert result["tax_lots"].query("date == @days[-1]").remaining.sum() == 0
    # Three CNY2000 buys: 3*(2000+5+.02); two CNY3000 sells:
    # The Aug 8 sale precedes the duty change: 3000-5-3-.03;
    # the Aug 29 sale follows it: 3000-5-1.50-.03.
    # Gross dividend is 100; no tax debit is assumed.
    expected_cash = Decimal("100000") - 3*Decimal("2005.02") + Decimal("2991.97") + Decimal("2993.47") + 100
    assert abs(Decimal(str(nav.iloc[-1].cash_total)) - expected_cash) < Decimal(".0000001")
    assert abs(Decimal(str(nav.iloc[-1].nav)) - (expected_cash - 20)) < Decimal(".0000001")
    assert not result["cash_events"].event.eq("DIVIDEND_TAX_DEBIT").any()


def test_fixed_share_targets_do_not_depend_on_weight_membership():
    data, instructions = synthetic_fixture()
    data["actions"] = pd.DataFrame()
    data["tax_settlements"] = []
    # Fixed engineering instructions are explicit shares, not strategy signals.
    for instruction in instructions:
        instruction["weights"] = {}
    result = run_backtest(data, instructions, 100000, slippage_multiplier=0, engineering_replay=True)
    assert list(zip(result["fills"].side, result["fills"].quantity)) == [
        ("BUY", 200), ("BUY", 200), ("SELL", 400)]


def test_fixed_quantity_contract_is_rejected_outside_engineering_even_without_weight_keys():
    data, instructions = synthetic_fixture()
    data["actions"] = pd.DataFrame()
    data["tax_settlements"] = []
    for instruction in instructions:
        instruction["weights"] = {}
    with pytest.raises(ExecutionBlockedError, match="engineering"):
        run_backtest(data, instructions, 100000)


@pytest.mark.parametrize("unknown", ["tick", "settlement", "limit"])
def test_current_unknown_exit_rule_cannot_fill_and_shares_remain(unknown):
    data, instructions = synthetic_fixture()
    data["actions"] = pd.DataFrame()
    data["tax_settlements"] = []
    days = data["calendar"]
    if unknown == "limit":
        data["bars"].loc[data["bars"].date >= days[41], "limit_terms_verified"] = False
    else:
        successor = data["instruments"].iloc[0].to_dict()
        successor.update(available_at=days[39]+"T20:00:00+08:00", effective_from=days[41])
        successor["tick_size" if unknown == "tick" else "t_plus"] = None
        data["instruments"] = pd.concat([data["instruments"], pd.DataFrame([successor])], ignore_index=True)
    result = run_backtest(data, instructions, 100000, slippage_multiplier=0, engineering_replay=True)
    assert result["fills"].side.tolist() == ["BUY", "BUY"]
    assert result["positions"].iloc[-1].quantity == 400
    assert "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS" in set(result["rejected_orders"].reason)


@pytest.mark.parametrize("changed_field,changed_value", [("cash_per_share", .5), ("record_date", "2023-08-03")])
def test_post_effective_dividend_revisions_require_adjustment_ledger(changed_field, changed_value):
    data, instructions = synthetic_fixture()
    changed = data["actions"].iloc[0].to_dict()
    changed.update(available_at=data["calendar"][28]+"T20:00:00+08:00")
    changed[changed_field] = changed_value
    data["actions"] = pd.concat([data["actions"], pd.DataFrame([changed])], ignore_index=True)
    with pytest.raises(ExecutionBlockedError, match="adjustment ledger"):
        run_backtest(data, instructions, 100000, engineering_replay=True)
