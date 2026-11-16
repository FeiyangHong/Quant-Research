"""Boundary and economic-representation tests, without market replay."""
from copy import deepcopy
from types import SimpleNamespace
import math

import numpy as np
import pandas as pd
import pytest

from quant_research.provenance import digest
from quant_research.risk_budget import (CLAIM_TYPE, RISK_RULE, RISK_SCOPE, RiskBlockedError,
    estimate_basket_risk, generate_risk_targets, initialize_fixed_scale, validate_initializer)
from quant_research.strategy import TargetDecision, _cutoff


def fixture_dataset():
    calendar = pd.bdate_range("2019-10-01", periods=100).strftime("%Y-%m-%d").tolist()
    changes = np.array([0.018 if i % 3 == 0 else -0.006 for i in range(99)])
    levels = 100 * np.cumprod(np.r_[1, 1 + changes])
    rows = [dict(date=day, instrument_id=sid, total_return_index=float(levels[i]),
                 available_at=day + "T21:00:00+08:00",
                 total_return_available_at=day + "T21:00:00+08:00")
            for i, day in enumerate(calendar) for sid in ("a", "b", "c")]
    return SimpleNamespace(calendar=calendar, bars=pd.DataFrame(rows), benchmark=pd.DataFrame(rows),
                           manifest={"sample": "development", "funded_account_start": "2020-01-01"})


def risk(dataset, weights=None):
    return estimate_basket_risk(dataset, dataset.calendar[60], dataset.calendar[61], weights or {"a": 1.0})


def initializer():
    result = dict(experiment_id=RISK_SCOPE, claim_type=CLAIM_TYPE, anchor_date="2020-01-23",
                  release_date="2020-02-03", available_at=_cutoff("2020-02-03").isoformat(),
                  c=0.4, risk={"alpha": 0.4}, rule_hash=digest(RISK_RULE))
    result["initializer_hash"] = digest(result)
    return result


def test_economic_exposure_split_is_invariant_and_uses_ddof_one():
    dataset = fixture_dataset()
    single = risk(dataset)
    split = risk(dataset, {"a": 0.5, "b": 0.5})
    three = risk(dataset, {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
    assert single["sigma"] == split["sigma"]
    assert three["sigma"] == pytest.approx(single["sigma"], rel=1e-14)
    assert single["complete_count"] == 60
    assert single["window_return_dates"] == dataset.calendar[1:61]
    # Closed-form variance for 20 positive and40 negative observations.
    avg = (20 * 0.018 + 40 * -0.006) / 60
    expected = math.sqrt((20 * (0.018 - avg) ** 2 + 40 * (-0.006 - avg) ** 2) / 59 * 252)
    assert single["sigma"] == pytest.approx(expected, rel=1e-12)
    assert single["alpha"] == pytest.approx(0.10 / expected)


def test_zero_risk_is_one_but_unknown_risk_is_not_zero():
    dataset = fixture_dataset()
    dataset.bars.total_return_index = 100.0
    assert risk(dataset)["zero_variance"] is True
    assert risk(dataset)["alpha"] == 1.0
    for invalid in (float("nan"), float("inf"), 0.0, -1.0):
        dataset.bars.total_return_index = invalid
        with pytest.raises(RiskBlockedError) as caught:
            risk(dataset)
        assert caught.value.diagnostics["complete_count"] == 0
        assert caught.value.diagnostics["alpha"] is None


def test_complete_dates_intersect_all_members_and_minimum_is45():
    dataset = fixture_dataset()
    dataset.bars = dataset.bars.loc[~(dataset.bars.instrument_id.eq("b")
        & dataset.bars.date.isin(dataset.calendar[:15]))].copy()
    assert risk(dataset, {"a": .5, "b": .5})["complete_count"] == 45
    dataset.bars = dataset.bars.loc[~(dataset.bars.instrument_id.eq("b")
        & dataset.bars.date.eq(dataset.calendar[15]))].copy()
    with pytest.raises(RiskBlockedError) as caught:
        risk(dataset, {"a": .5, "b": .5})
    assert caught.value.diagnostics["complete_count"] == 44
    assert len(caught.value.diagnostics["missing"]) == 16


@pytest.mark.parametrize("endpoint", [0, 60])
@pytest.mark.parametrize("clock", ["available_at", "total_return_available_at"])
def test_both_return_endpoints_and_both_clocks_are_as_of_release(endpoint, clock):
    dataset = fixture_dataset()
    mask = dataset.bars.instrument_id.eq("a") & dataset.bars.date.eq(dataset.calendar[endpoint])
    dataset.bars.loc[mask, clock] = dataset.calendar[62] + "T21:00:00+08:00"
    result = risk(dataset)
    assert result["complete_count"] == 59
    assert result["missing"]
    with pytest.raises(RiskBlockedError, match="D\\+1"):
        estimate_basket_risk(dataset, dataset.calendar[60], dataset.calendar[62], {"a": 1})


def test_future_rows_and_post_anchor_price_cannot_change_risk_prefix():
    dataset = fixture_dataset()
    original = risk(dataset)
    dataset.bars.loc[dataset.bars.date.gt(dataset.calendar[60]), "total_return_index"] *= 10
    dataset.bars.loc[dataset.bars.date.lt(dataset.calendar[0]), "total_return_index"] = np.nan
    assert risk(dataset) == original
    revision = dataset.bars.iloc[0].copy()
    revision["total_return_index"] *= 5
    revision["available_at"] = dataset.calendar[62] + "T21:00:00+08:00"
    dataset.bars = pd.concat([dataset.bars, revision.to_frame().T], ignore_index=True)
    assert risk(dataset) == original


def test_initializer_hash_and_legal_time_are_enforced():
    fixed = initializer()
    validate_initializer(fixed)
    fixed["c"] = .5
    with pytest.raises(RiskBlockedError, match="hash"):
        validate_initializer(fixed)
    fixed = initializer()
    fixed["release_date"] = "2020-01-24"
    fixed["initializer_hash"] = digest({k: v for k, v in fixed.items() if k != "initializer_hash"})
    with pytest.raises(RiskBlockedError, match="anchor"):
        validate_initializer(fixed)


def test_ce_uses_same_c_across_periods_and_delay_and_survives_diagnostic_missing(monkeypatch):
    dataset, fixed = fixture_dataset(), initializer()
    first = TargetDecision("2020-02-03", "2020-02-04", _cutoff("2020-02-03"),
        {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}, {}, {}, diagnostics={"signal_anchor_date": "2020-01-23"})
    monkeypatch.setattr("quant_research.risk_budget.generate_liquid_targets", lambda *a, **k: [first])
    monkeypatch.setattr("quant_research.risk_budget.estimate_basket_risk", lambda *a: {"alpha": .8, "sigma": .125})
    for sample in ("development", "validation"):
        dataset.manifest["sample"] = sample
        for delay in (1, 2):
            target = generate_risk_targets(dataset, "CE", fixed, delay)[0]
            assert sum(target.weights.values()) == pytest.approx(.4)
            assert target.diagnostics["alpha_applied"] == .4
            assert target.diagnostics["risk"]["alpha"] == .8
    def missing(*args):
        raise RiskBlockedError("insufficient", {"complete_count": 44})
    monkeypatch.setattr("quant_research.risk_budget.estimate_basket_risk", missing)
    ce = generate_risk_targets(dataset, "CE", fixed)[0]
    assert sum(ce.weights.values()) == pytest.approx(.4)
    assert ce.diagnostics["risk"]["status"] == "BLOCKED_DIAGNOSTIC"
    for arm in ("VE", "VR"):
        with pytest.raises(RiskBlockedError):
            generate_risk_targets(dataset, arm, fixed)


def test_vr_calculates_its_own_basket_and_empty_target_keeps_cash(monkeypatch):
    dataset, fixed = fixture_dataset(), initializer()
    baskets = {"E0": {"a": .25, "b": .25, "c": .25, "d": .25}, "R0": {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}}
    def targets(data, variant, delay):
        return [TargetDecision("2020-02-03", "2020-02-04", _cutoff("2020-02-03"), baskets[variant],
                               {}, {}, diagnostics={"signal_anchor_date": "2020-01-23"})]
    monkeypatch.setattr("quant_research.risk_budget.generate_liquid_targets", targets)
    monkeypatch.setattr("quant_research.risk_budget.estimate_basket_risk", lambda d, a, r, w:
                        {"alpha": len(w) / 10, "sigma": 1 / len(w)})
    assert sum(generate_risk_targets(dataset, "VE", fixed)[0].weights.values()) == pytest.approx(.4)
    assert sum(generate_risk_targets(dataset, "VR", fixed)[0].weights.values()) == pytest.approx(.3)
    baskets["E0"] = {}
    empty = generate_risk_targets(dataset, "VE", fixed)[0]
    assert empty.weights == {} and empty.diagnostics["risk"] is None


def test_initializer_uses_first_nonempty_signal_and_not_execution_or_validation(monkeypatch):
    dataset = fixture_dataset()
    empty = TargetDecision("2020-01-02", "2020-01-03", _cutoff("2020-01-02"), {}, {}, {},
                           diagnostics={"signal_anchor_date": "2019-12-31"})
    first = TargetDecision("2020-02-03", "2020-02-04", _cutoff("2020-02-03"), {"a": 1}, {}, {},
                           diagnostics={"signal_anchor_date": "2020-01-23"})
    monkeypatch.setattr("quant_research.risk_budget.generate_liquid_targets", lambda *a, **k: [empty, first])
    seen = []
    def estimate(data, anchor, release, weights):
        seen.append((anchor, release, weights))
        return {"alpha": .3}
    monkeypatch.setattr("quant_research.risk_budget.estimate_basket_risk", estimate)
    monkeypatch.setattr("quant_research.risk_budget.dataset_hash", lambda d: "dataset_identity")
    assert initialize_fixed_scale(dataset)["c"] == .3
    assert seen == [("2020-01-23", "2020-02-03", {"a": 1})]
    dataset.manifest["sample"] = "validation"
    with pytest.raises(RiskBlockedError, match="development"):
        initialize_fixed_scale(dataset)
