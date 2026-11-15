"""Design and accounting invariants for the independent frozen review."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location("m4_frozen_review", Path(__file__).resolve().parents[1] / "scripts/m4_frozen_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_original_estimator_repeat_exposure_is_not_representation_invariant():
    rows = review.repeat_exposure_counterexample()["rows"]
    assert len({round(r["direct_sigma"],12) for r in rows}) == 1
    assert rows[2]["original_shrink_sigma"] < rows[1]["original_shrink_sigma"] < rows[0]["original_shrink_sigma"]
    for row in rows:
        assert row["original_shrink_sigma"] / row["direct_sigma"] == pytest.approx(row["analytic_shrunk_to_direct_ratio"])
    assert rows[2]["original_scale"] > rows[0]["original_scale"]


def test_independent_direct_and_covariance_risk_agree_without_changing_shrinkage():
    series = np.linspace(-.03,.04,60)
    returns = np.column_stack([series, series[::-1] * .5])
    w = [.25,.75]
    result = review.original_risk(returns,w)
    assert result["direct_sigma"] == pytest.approx(np.sqrt(np.array(w) @ np.cov(returns,rowvar=False) @ np.array(w)*252))
    assert result["original_shrink_sigma"] != pytest.approx(result["direct_sigma"])
    assert review.original_risk(returns[:44],w)["original_scale"] == 0


def test_frozen_selector_publication_and_half_open_effective_boundary():
    rows = [{"available_at":"2020-01-01T21:00:00+08:00","effective_from":"2020-01-03","effective_to":"2020-01-05","revision_id":"a"}]
    assert review.master_choice(rows,"2020-01-02T21:00:00+08:00")["revision_id"] == "a"
    assert review.master_choice(rows,"2020-01-02T21:00:00+08:00",True) is None
    assert review.master_choice(rows,"2020-01-03T21:00:00+08:00",True)["revision_id"] == "a"
    assert review.master_choice(rows,"2020-01-05T21:00:00+08:00",True) is None


def test_mark_to_market_attribution_includes_fees_and_does_not_double_count_payout():
    nav = [{"date":"2020-12-31","nav":99.},{"date":"2021-01-04","nav":104.},{"date":"2021-01-05","nav":104.}]
    positions = [{"date":d,"instrument_id":"ETF","market_value":v} for d,v in [("2020-12-31",50.),("2021-01-04",53.),("2021-01-05",53.)]]
    fills = [{"date":"2020-12-31","instrument_id":"ETF","side":"BUY","notional":50.,"fees":1.}]
    events = [{"date":"2021-01-04","instrument_id":"ETF","event":"DIVIDEND_RECEIVABLE","amount":2.},
              {"date":"2021-01-05","instrument_id":"ETF","event":"DIVIDEND_PAID","amount":2.}]
    daily, fees, error = review.daily_attribution(nav,positions,fills,events,100.)
    assert daily["2020-12-31"]["ETF"] == -1
    assert daily["2021-01-04"]["ETF"] == 5
    assert daily["2021-01-05"]["ETF"] == 0
    assert error == 0


def test_temporal_query_scope_cannot_be_overwritten_by_input_calendar_scope():
    run = {"directory":"toy","path":"base","period":"development",
           "config":{"initial_cash":100000,"variant":"E0","risk_scaling":False}}
    tables = {k:[] for k in ["positions","orders","order_events","fills","rejected_orders","decisions","share_events","nav"]}
    tables["positions"] = [{"date":"2020-01-02","instrument_id":"ETF"}]
    mismatch = {("2020-01-02","09:30:00","ETF"):{"scope":"ACCOUNT","instrument_id":"ETF","date":"2020-01-02"}}
    coverage, triggers = review.inspect_run(run,tables,{"calendar":["2020-01-02"],"actions":[]},{},mismatch)
    assert coverage["actual_execution_dependency_discrepancies"] == 1
    assert coverage["conclusion"] == "REVIEW_REQUIRED"
    assert triggers[0]["scope"] == "HELD_OPEN_AND_CLOSE"
