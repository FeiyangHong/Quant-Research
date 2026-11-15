"""Non-author M5 review; expected sets are economic hand oracles, not selector output."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from quant_research.data import Dataset, REQUIRED, audit_dataset, synthetic_dataset
from quant_research.dependencies import representative_dependencies
from quant_research.providers.universe import provisional_amount_representatives
from quant_research.strategy import _prepare, _representatives, _snapshot, generate_targets
from quant_research.temporal import master_record, representative_record


def independent_dataset():
    days = pd.bdate_range("2017-01-02", "2019-05-02").strftime("%Y-%m-%d").tolist()
    master = []
    bars = []
    for code, family, amount in [("A", "CSI300", 300000000), ("B", "CSI300", 180000000),
                                 ("C", "CSI500", 100000000), ("D", "CSI1000", 90000000)]:
        master.append(dict(instrument_id=code, asset_type="ETF", board="ETF", listed_on=days[0],
            delisted_on=None, available_at="2016-12-30T21:00:00+08:00", account_verified=True,
            benchmark_id=family, benchmark_source_available_at="2016-12-30T21:00:00+08:00",
            industry="BROAD_MARKET", lot_size=100, tick_size=.001, t_plus=1,
            strategy_universe="R1B", revision_id=code+"_first", supersedes_id=None,
            effective_from=days[0], effective_to=None))
        for day in days:
            bars.append(dict(instrument_id=code, date=day, open=4., high=4., low=4., close=4.,
                amount=float(amount), volume=amount/4, upper_limit=4.4, lower_limit=3.6, suspended=False,
                available_at=day+"T16:00:00+08:00", revision_id=code+day, supersedes_id=None,
                total_return_index=100., usage_scope="FULL_STRATEGY"))
    manifest = deepcopy(synthetic_dataset().manifest)
    manifest.update(dataset_id="INDEPENDENT_M5_COUNTEREXAMPLE_ONLY", coverage_start=days[0],
                    coverage_end=days[-1], tr_coverage_start=days[0])
    benchmark = pd.DataFrame([dict(date=d, total_return_index=100., available_at=d+"T16:00:00+08:00",
                                   revision_id="bench"+d, supersedes_id=None) for d in days])
    return Dataset(days, pd.DataFrame(master), pd.DataFrame(bars), pd.DataFrame(columns=REQUIRED["actions"]), benchmark, manifest)


def provider(data):
    initial = data.instruments.loc[data.instruments.revision_id.str.endswith("_first")]
    candidates = [dict(code=r.instrument_id, category=r.benchmark_id, documented_index_categories=[r.benchmark_id],
        documented_listing_dates=[r.listed_on], snapshot_dates=list(data.calendar)) for r in initial.itertuples()]
    histories = {code: [dict(date=r.date, amount=str(r.amount), suspended=r.suspended) for r in rows.itertuples()]
                 for code, rows in data.bars.groupby("instrument_id")}
    result = provisional_amount_representatives(list(data.calendar), candidates, histories, data.instruments.to_dict("records"))
    return next(r for r in result["schedule"] if r["quarter_start"] == "2019-04-01")["representatives"]


def compare_three(data, expected):
    schedule = representative_dependencies(data)
    assert next(r for r in schedule["schedule"] if r["quarter_start"] == "2019-04-01")["representatives"] == expected
    assert _representatives(_prepare(data.instruments), _prepare(data.bars), data.calendar,
                            data.calendar.index("2019-03-29")) == expected
    assert provider(data) == expected
    assert set(expected) <= set(schedule["required_full_history_instruments"])


@pytest.mark.parametrize("shuffle", [False, True])
def test_late_correction_of_old_state_does_not_resurrect_after_successor_expiry(shuffle):
    data = independent_dataset()
    original = data.instruments.iloc[0].to_dict()
    successor = dict(original, revision_id="A_term", supersedes_id="A_first", revision_kind="TRANSITION",
                     available_at="2017-12-28T21:00:00+08:00", effective_from="2018-01-01", effective_to="2019-01-01")
    old_fix = dict(original, revision_id="A_late_old_fix", supersedes_id="A_first", revision_kind="CORRECTION",
                   available_at="2019-03-28T21:00:00+08:00")
    data.instruments = pd.concat([data.instruments, pd.DataFrame([successor, old_fix])], ignore_index=True)
    if shuffle:
        data.instruments = data.instruments.sample(frac=1, random_state=188)
        data.bars = data.bars.sample(frac=1, random_state=991)
    # A ended Jan1. Updating its obsolete original state on Mar28 cannot reopen it.
    assert master_record([original, successor, old_fix], "2019-03-29T21:00:00+08:00") is None
    compare_three(data, ["B", "C", "D"])


def test_future_transition_does_not_advance_benchmark_gate_then_does_not_revive_old():
    data = independent_dataset()
    original = data.instruments.iloc[0].to_dict()
    successor = dict(original, revision_id="A_new", supersedes_id="A_first", revision_kind="TRANSITION",
        available_at="2019-02-27T21:00:00+08:00", effective_from="2019-03-01",
        benchmark_source_available_at="2019-04-02T21:00:00+08:00")
    versions = [successor, original]
    # Feb28 old economic state remains active even though its successor was announced.
    assert representative_record(versions, "2019-02-28T21:00:00+08:00")["revision_id"] == "A_first"
    # Mar1 successor exists economically, but its index evidence is still unavailable.
    assert master_record(versions, "2019-03-01T21:00:00+08:00")["revision_id"] == "A_new"
    assert representative_record(versions, "2019-03-01T21:00:00+08:00") is None
    assert representative_record(versions, "2019-04-02T21:00:00+08:00")["revision_id"] == "A_new"
    data.instruments = pd.concat([data.instruments, pd.DataFrame([successor])], ignore_index=True)
    compare_three(data, ["B", "C", "D"])
    snap = _snapshot(_prepare(data.instruments), pd.Timestamp("2019-03-29T21:00:00+08:00"), ["instrument_id"], master=True)
    assert sorted(snap.instrument_id) == ["B", "C", "D"]


def test_live_old_state_before_future_universe_revocation_is_not_revoked_early():
    data = independent_dataset()
    old = data.instruments.iloc[0].to_dict()
    future = dict(old, revision_id="A_future_out", supersedes_id="A_first", revision_kind="TRANSITION",
                  available_at="2019-03-28T21:00:00+08:00", effective_from="2019-04-02", strategy_universe="OUTSIDE")
    data.instruments = pd.concat([data.instruments, pd.DataFrame([future])], ignore_index=True)
    compare_three(data, ["A", "C", "D"])


def test_wrong_selection_only_B_blocks_audit_and_actual_monthly_target():
    data = independent_dataset()
    old = data.instruments.iloc[0].to_dict()
    expired = dict(old, revision_id="A_expired", supersedes_id="A_first", revision_kind="TRANSITION",
                  available_at="2018-02-28T21:00:00+08:00", effective_from="2018-03-01", effective_to="2019-01-01")
    data.instruments = pd.concat([data.instruments, pd.DataFrame([expired])], ignore_index=True)
    compare_three(data, ["B", "C", "D"])
    full = next(t for t in generate_targets(data, "R0") if t.decision_date == "2019-04-30")
    assert full.weights == {"B": 1/3, "C": 1/3, "D": 1/3}
    data.bars.loc[data.bars.instrument_id.eq("B"), "usage_scope"] = "REPRESENTATIVE_SELECTION_ONLY"
    data.bars.loc[data.bars.instrument_id.eq("B"), "total_return_index"] = np.nan
    data.manifest["representative_dependencies"] = representative_dependencies(data)
    compare_three(data, ["B", "C", "D"])
    audit = audit_dataset(data)
    assert not audit["errors"], audit
    assert any("selected representative lacks full TR/event coverage" in issue and "'B'" in issue for issue in audit["blockers"])
    blocked = next(t for t in generate_targets(data, "R0") if t.decision_date == "2019-04-30")
    assert blocked.status == "BLOCKED_MOMENTUM_DATA" and blocked.weights == {}
