"""Independent adversarial checks from the pre-return admission review."""
from types import SimpleNamespace

import pandas as pd

from quant_research.data import bars_asof
from quant_research.dependencies import representative_dependencies
from quant_research.providers.real_builder import reconstruct_total_return
from quant_research.strategy import _prepare, _representatives


def test_late_share_terms_do_not_change_public_turnover_competition():
    """The amount winner cannot be replaced because its TR terms arrive later."""
    days = pd.bdate_range("2014-01-01", "2014-07-02").strftime("%Y-%m-%d").tolist()
    master, rows = [], []
    for code, amount in (("A", 10.0), ("B", 20.0)):
        master.append(dict(instrument_id=code, asset_type="ETF", account_verified=True,
                           listed_on=days[0], delisted_on=None, benchmark_id="SAME_INDEX",
                           strategy_universe="R1B", available_at=days[0] + "T09:00:00+08:00"))
        for day in days:
            clock = day + "T21:00:00+08:00"
            rows.append(dict(instrument_id=code, date=day, amount=amount, suspended=False,
                             close=10.0 if day <= "2014-03-31" or code == "A" else 5.0,
                             volume=100.0, available_at=clock, market_available_at=clock))
    raw = pd.DataFrame(rows)
    event = pd.DataFrame([dict(instrument_id="B", ex_date="2014-03-31", action_type="SPLIT",
                               effective_phase="EOD", share_factor=2.0,
                               available_at="2014-04-02T21:00:00+08:00")])
    reconstructed, issues = reconstruct_total_return(raw.loc[raw.instrument_id.eq("B")], event, start=days[0])
    assert not issues
    assert reconstructed.loc[reconstructed.date.eq("2014-03-31"), "total_return_available_at"].iloc[0] == "2014-04-02T21:00:00+08:00"
    dataset = SimpleNamespace(calendar=days, instruments=pd.DataFrame(master),
                              bars=pd.concat([raw.loc[raw.instrument_id.eq("A")], reconstructed], ignore_index=True))
    schedule = representative_dependencies(dataset)["schedule"]
    assert next(row for row in schedule if row["quarter_start"] == "2014-04-01")["representatives"] == ["B"]
    previous_index = days.index("2014-03-31")
    assert _representatives(_prepare(dataset.instruments), _prepare(dataset.bars), days, previous_index) == ["B"]
    # Public price/turnover stay visible, while the later-derived TR does not.
    early = bars_asof(dataset, "2014-03-31T21:00:00+08:00")
    early_b = early.loc[early.instrument_id.eq("B") & early.date.eq("2014-03-31")].iloc[0]
    assert early_b.amount == 20.0 and early_b.close == 10.0
    assert pd.isna(early_b.total_return_index)
    later = bars_asof(dataset, "2014-04-02T21:00:00+08:00")
    assert pd.notna(later.loc[later.instrument_id.eq("B") & later.date.eq("2014-03-31"), "total_return_index"].iloc[0])


def test_unreachable_age_waiver_keeps_winner_and_expires_at_252_sessions():
    """Missing TR never selects the runner-up; reaching entry age restores need."""
    days = pd.bdate_range("2014-01-01", periods=252).strftime("%Y-%m-%d").tolist()
    master = pd.DataFrame([dict(instrument_id=code, asset_type="ETF", account_verified=True,
                               listed_on=days[0], delisted_on=None, benchmark_id="SAME_INDEX",
                               strategy_universe="R1B", available_at=days[0] + "T09:00:00+08:00")
                           for code in ("A", "B")])
    bars = pd.DataFrame([dict(instrument_id=code, date=day, amount=amount, suspended=False,
                              available_at=day + "T21:00:00+08:00", total_return_index=None)
                         for code, amount in (("A", 10.0), ("B", 20.0)) for day in days])
    short = SimpleNamespace(calendar=days[:247], instruments=master, bars=bars.loc[bars.date.le(days[246])])
    waived = representative_dependencies(short)
    assert waived["representative_union"] == ["B"]
    assert waived["required_full_history_instruments"] == []
    assert waived["feature_dependency_waivers"][0]["listed_sessions"] == 247
    full = representative_dependencies(SimpleNamespace(calendar=days, instruments=master, bars=bars))
    assert full["representative_union"] == ["B"]
    assert full["feature_dependency_waivers"] == []
    assert full["required_full_history_instruments"] == ["B"]
