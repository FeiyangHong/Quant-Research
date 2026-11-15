import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation import holm_four, paired_inference, mature_training_rows, nav_metrics


def test_holm_keeps_unready_families():
    adjusted = holm_four({"R1": .02})
    assert adjusted == {"R1": .08, "R2": 1, "R3": 1, "R4": 1}


def test_bootstrap_null_centering_and_reproducibility():
    rng = np.random.default_rng(4)
    e = rng.normal(0, .01, 500)
    x = pd.Series(e - e.mean())
    zero = x * 0
    args = dict(annual_incremental_cost=0, primary_capital=100000, repetitions=499)
    a = paired_inference(x, zero, **args)
    assert a == paired_inference(x, zero, **args)
    assert .25 < a["p_net"] < .75
    assert a["ci95"][0] < 0 < a["ci95"][1]
    positive = paired_inference(x + .01, zero, **args)
    assert positive["p_net"] <= .01


def test_unknown_hurdle_and_unmatched_dates_fail_closed():
    x = pd.Series([0.] * 200)
    assert paired_inference(x, x, annual_incremental_cost=None, primary_capital=10000)["status"] == "BLOCKED_HURDLE"
    with pytest.raises(ValueError):
        paired_inference(x, x.rename(index=lambda i: i + 1), annual_incremental_cost=0, primary_capital=10000)


def test_validation_tail_is_purged():
    rows = pd.DataFrame({"label_available_at": ["2024-12-30T21:00:00+08:00", "2025-01-10T21:00:00+08:00"]})
    assert len(mature_training_rows(rows, "2025-01-01T00:00:00+08:00")) == 1


def test_opening_cost_is_not_erased():
    result = nav_metrics(pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "nav": [995., 995.]}), 1000.)
    assert result["total_return"] == pytest.approx(-.005)
    assert result["max_drawdown"] == pytest.approx(-.005)
