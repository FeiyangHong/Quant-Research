from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd

from quant_research.dependencies import representative_dependencies, required_tr_start
from quant_research.strategy import _prepare, _representatives


def selection_market():
    days = pd.bdate_range("2014-01-01", "2017-01-10").strftime("%Y-%m-%d").tolist()
    master, rows = [], []
    for code, amount in (("A", 10.), ("B", 20.), ("C", 20.)):
        master.append(dict(instrument_id=code, asset_type="ETF", account_verified=True,
            listed_on=days[0], delisted_on=None, benchmark_id="SAME_INDEX", strategy_universe="R1B",
            available_at=days[0] + "T09:00:00+08:00"))
        rows.extend(dict(instrument_id=code, date=day, amount=amount, suspended=False,
            available_at=day + "T16:00:00+08:00", total_return_index=np.nan) for day in days)
    return SimpleNamespace(calendar=days, instruments=pd.DataFrame(master), bars=pd.DataFrame(rows))


def test_independent_selector_matches_strategy_without_return_inputs():
    dataset = selection_market()
    proof = representative_dependencies(dataset)
    for row in proof["schedule"]:
        index = dataset.calendar.index(row["quarter_start"])
        selected = _representatives(_prepare(dataset.instruments), _prepare(dataset.bars), dataset.calendar, index - 1)
        assert selected == row["representatives"]
    assert proof["required_full_history_instruments"] == ["B"]  # deterministic code tie
    changed = deepcopy(dataset)
    changed.bars["total_return_index"] = np.arange(len(changed.bars)) * 1e10
    assert representative_dependencies(changed) == proof


def test_pending_metadata_and_missing_turnover_cannot_win():
    dataset = selection_market()
    dataset.instruments.loc[dataset.instruments.instrument_id.eq("B"), "available_at"] = "2020-01-01T21:00:00+08:00"
    dataset.bars.loc[dataset.bars.instrument_id.eq("C"), "amount"] = np.nan
    assert representative_dependencies(dataset)["required_full_history_instruments"] == ["A"]


def test_required_warmup_covers_last_pre_account_signal():
    days = selection_market().calendar
    first = next(i for i, day in enumerate(days) if day >= "2016-01-01")
    start = required_tr_start(days)
    assert len(days[days.index(start):first]) == 200
