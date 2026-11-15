"""Invented observations exercise M7 mechanics, never investment evidence."""
import numpy as np
import pandas as pd
import pytest

from quant_research.cohort import (COHORT_SCOPE, FIXED_COHORT, cohort_dependencies,
                                   generate_cohort_targets)
from quant_research.cohort_runner import validate_cohort_config
from quant_research.data import Dataset, REQUIRED, SCHEMA_VERSION, audit_dataset
from quant_research.execution import run_backtest
from quant_research.strategy import StrategyBlockedError, generate_targets


@pytest.fixture
def cohort():
    calendar = pd.bdate_range("2014-01-02", "2016-07-29").strftime("%Y-%m-%d").tolist()
    masters, bars = [], []
    for number, sid in enumerate(FIXED_COHORT):
        masters.append(dict(instrument_id=sid, asset_type="ETF", board="ETF", listed_on=calendar[0],
                            delisted_on=None, available_at="2014-01-01T21:00:00+08:00",
                            account_verified=True, status="NORMAL", benchmark_id="INVENTED_" + str(number),
                            industry="FIXED_PRODUCT", lot_size=100, tick_size=.001, t_plus=1,
                            revision_id=sid + "_master", supersedes_id=None, strategy_universe=COHORT_SCOPE))
        for index, day in enumerate(calendar):
            bars.append(dict(date=day, instrument_id=sid, open=2., high=2.02, low=1.98, close=2.,
                             amount=40_000_000. if number < 4 else 10_000_000., volume=20_000_000,
                             upper_limit=2.2, lower_limit=1.8, suspended=False,
                             available_at=day + "T16:00:00+08:00", revision_id=sid + day, supersedes_id=None,
                             total_return_index=100 * np.exp(-.0001 * (number + 1) * index)))
    benchmark = pd.DataFrame([dict(date=day, total_return_index=100. + index,
                                  available_at=day + "T16:00:00+08:00", revision_id=day,
                                  supersedes_id=None) for index, day in enumerate(calendar)])
    manifest = dict(dataset_id="invented-m7-fixture", dataset_version="1", synthetic=True,
                    schema_version=SCHEMA_VERSION, timezone="Asia/Shanghai", research_scope=COHORT_SCOPE,
                    signal_release_delay=1, units=dict(volume="shares_or_fund_units", amount="CNY", price="CNY"))
    return Dataset(calendar, pd.DataFrame(masters), pd.DataFrame(bars),
                   pd.DataFrame(columns=REQUIRED["actions"]), benchmark, manifest)


def _live(cohort, variant="E0", **kwargs):
    return [d for d in generate_cohort_targets(cohort, variant, **kwargs) if d.status != "CASH_COHORT_NOT_YET_KNOWN"]


def test_first_legal_anchor_negative_momentum_and_execution_only_delay(cohort):
    targets = generate_cohort_targets(cohort, "R0")
    assert targets[0].diagnostics["signal_anchor_date"] == "2015-12-31"
    assert targets[0].weights == {} and targets[0].status == "CASH_COHORT_NOT_YET_KNOWN"
    first = targets[1]
    assert first.diagnostics["signal_anchor_date"] == "2016-01-29"
    assert first.decision_date == "2016-02-01" and first.execution_date == "2016-02-02"
    assert list(first.weights) == list(FIXED_COHORT[:3])
    assert all(v < 0 for v in first.diagnostics["momentum"].values())
    assert first.diagnostics["momentum"][FIXED_COHORT[0]] == pytest.approx(-.0105)
    delayed = generate_cohort_targets(cohort, "R0", execution_delay=2)
    assert [(d.decision_date, d.weights, d.reference_prices) for d in targets] == [
        (d.decision_date, d.weights, d.reference_prices) for d in delayed]
    assert delayed[1].execution_date == "2016-02-03"
    with pytest.raises(StrategyBlockedError):
        generate_targets(cohort, universe="R1I")


def test_release_day_values_do_not_recompute_signals(cohort):
    before = _live(cohort, "R1")[0]
    mask = cohort.bars.date.eq(before.decision_date)
    cohort.bars.loc[mask, "total_return_index"] = 1e30
    cohort.bars.loc[mask, "close"] = 3.
    cohort.benchmark.loc[cohort.benchmark.date.eq(before.decision_date), "total_return_index"] = 1e30
    after = _live(cohort, "R1")[0]
    assert after.weights == before.weights
    assert after.diagnostics["momentum"] == before.diagnostics["momentum"]
    assert after.diagnostics["trend"] == before.diagnostics["trend"]
    assert set(after.reference_prices.values()) == {3.}


@pytest.mark.parametrize("missing", ["amount", "status", "permission", "identity", "TR"])
def test_missing_never_becomes_cash(cohort, missing):
    sid = FIXED_COHORT[0]
    if missing == "amount":
        cohort.bars = cohort.bars.loc[~(cohort.bars.instrument_id.eq(sid) & cohort.bars.date.eq("2016-01-29"))]
    elif missing == "status":
        cohort.instruments.loc[cohort.instruments.instrument_id.eq(sid), "status"] = None
    elif missing == "permission":
        cohort.instruments["account_verified"] = cohort.instruments.account_verified.astype(object)
        cohort.instruments.loc[cohort.instruments.instrument_id.eq(sid), "account_verified"] = None
    elif missing == "identity":
        cohort.instruments = cohort.instruments.iloc[:-1]
    else:
        cohort.bars.loc[cohort.bars.instrument_id.eq(sid), "total_return_index"] = np.nan
    with pytest.raises(StrategyBlockedError, match="DATA_BLOCKED_COHORT"):
        generate_cohort_targets(cohort, "E0")


def test_n3_equal_targets_have_identical_main_accounts(cohort):
    cohort.bars.loc[cohort.bars.instrument_id.eq(FIXED_COHORT[3]), "amount"] = 10_000_000.
    # Reverse the factor ranking while preserving the three selected products.
    cohort.bars["total_return_index"] = 1 / cohort.bars.total_return_index
    equal, ranked = generate_cohort_targets(cohort, "E0"), generate_cohort_targets(cohort, "R0")
    assert [d.weights for d in equal] == [d.weights for d in ranked]
    assert [d.ranks for d in equal] == [d.ranks for d in ranked]
    a = run_backtest(cohort, equal, 100000, start_date="2016-01-01")
    b = run_backtest(cohort, ranked, 100000, start_date="2016-01-01")
    for table in ("orders", "fills", "nav", "positions"):
        pd.testing.assert_frame_equal(a[table], b[table])
    assert len(a["fills"]) > 0


def test_complete_n2_waives_unused_tr_and_produces_real_engine_cash(cohort):
    cohort.bars.loc[~cohort.bars.instrument_id.isin(FIXED_COHORT[:2]), "amount"] = 10_000_000.
    cohort.bars["total_return_index"] = np.nan
    cohort.bars["usage_scope"] = "COHORT_ELIGIBILITY_ONLY"
    proof = cohort_dependencies(cohort)
    assert proof["required_full_history_instruments"] == []
    assert proof["qualified_instruments"] == list(FIXED_COHORT[:2])
    assert proof["no_ranking_or_holding_dependency"] == list(FIXED_COHORT)
    cohort.manifest["cohort_dependencies"] = proof
    audit = audit_dataset(cohort)
    assert not audit["errors"] and not audit["blockers"]
    for variant in ("E0", "R0", "E1", "R1"):
        decisions = generate_cohort_targets(cohort, variant)
        assert all(d.weights == {} for d in decisions)
    result = run_backtest(cohort, decisions, 100000, start_date="2016-01-01")
    assert result["nav"].nav.eq(100000).all() and result["fills"].empty
    assert len(result["nav"]) == sum(d >= "2016-01-01" for d in cohort.calendar)
    # The same null fields must fail if an actual ranking opportunity appears.
    cohort.bars.loc[cohort.bars.instrument_id.eq(FIXED_COHORT[2]), "amount"] = 40_000_000.
    assert audit_dataset(cohort)["blockers"]
    with pytest.raises(StrategyBlockedError):
        generate_cohort_targets(cohort)


def test_economic_change_respects_publication_effectiveness_and_daily_exit(cohort):
    sid = FIXED_COHORT[0]
    row = cohort.instruments.loc[cohort.instruments.instrument_id.eq(sid)].iloc[0].to_dict()
    row.update(status="ECONOMIC_IDENTITY_CHANGED", effective_from="2016-02-10",
               available_at="2016-02-04T21:00:00+08:00", revision_id=sid + "_transition",
               supersedes_id=row["revision_id"], revision_kind="TRANSITION")
    cohort.instruments = pd.concat([cohort.instruments, pd.DataFrame([row])], ignore_index=True)
    targets = generate_cohort_targets(cohort)
    assert sid in targets[1].weights
    assert sid not in targets[2].weights
    result = run_backtest(cohort, targets, 100000, start_date="2016-01-01")
    exits = result["order_events"].loc[result["order_events"].event.eq("DAILY_RISK_EXIT")]
    assert exits.date.tolist() == ["2016-02-10"]
    sell = result["orders"].loc[result["orders"].intent_type.eq("RISK_EXIT")]
    assert sell.execution_date.tolist() == ["2016-02-11"]


def test_scope_does_not_waive_old_r1b_audit(cohort):
    cohort.bars["usage_scope"] = "COHORT_ELIGIBILITY_ONLY"
    cohort.manifest["research_scope"] = "R1B"
    assert any("unknown dependency usage scope" in e for e in audit_dataset(cohort)["errors"])


def test_false_permission_requires_explicit_known_denial(cohort):
    mask = cohort.instruments.instrument_id.eq(FIXED_COHORT[0])
    cohort.instruments.loc[mask, "account_verified"] = False
    with pytest.raises(StrategyBlockedError, match="unverified account permission"):
        cohort_dependencies(cohort)
    cohort.instruments.loc[mask, "account_permission_status"] = "DENIED"
    proof = cohort_dependencies(cohort)
    assert proof["schedule"][1]["exclusions"][FIXED_COHORT[0]] == "PERMISSION_DENIED"


def test_config_rejects_other_capital_scaling_paths_and_holdout():
    config = dict(protocol_version="phase2-mvp-0.1", live_enabled=False, universe=COHORT_SCOPE,
                  initial_cash=100000, primary_capital_confirmed=True, risk_scaling=False,
                  signal_release_delay=1, seed=20261114, claim_type="economic_increment",
                  sample="validation", variant="R0", cost_multiplier=1, slippage_multiplier=1,
                  execution_delay=1, annual_incremental_cost=None)
    validate_cohort_config(config)
    for key, value in (("universe", "R1I"), ("initial_cash", 10000), ("risk_scaling", True),
                       ("slippage_multiplier", 0), ("sample", "holdout"), ("annual_incremental_cost", 0),
                       ("annual_incremental_cost", 1000)):
        with pytest.raises(ValueError):
            validate_cohort_config(dict(config, **{key: value}))
    del config["annual_incremental_cost"]
    with pytest.raises(ValueError):
        validate_cohort_config(config)
