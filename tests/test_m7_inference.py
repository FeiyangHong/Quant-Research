"""Unknown fixed fees do not censor the transaction-cost-net description."""
import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation import paired_inference


def test_unknown_hurdle_keeps_identical_descriptive_interval():
    rng = np.random.default_rng(917)
    dates = pd.bdate_range("2022-01-03", periods=360)
    baseline = pd.Series(rng.normal(0, .007, len(dates)), index=dates)
    candidate = baseline + rng.normal(.0002, .003, len(dates))
    results = [paired_inference(candidate, baseline, annual_incremental_cost=c,
                               primary_capital=100000, repetitions=499)
               for c in (None, 0, 1000)]
    assert all(r["ci95"] == results[0]["ci95"] for r in results)
    assert all(r["mean_net_increment"] == results[0]["mean_net_increment"] for r in results)
    assert results[0]["descriptive_status"] == "DESCRIPTIVE_INFERENCE"
    assert results[0]["economic_status"] == results[0]["status"] == "BLOCKED_HURDLE"
    assert all(results[0][k] is None for k in (
        "annual_incremental_cost", "daily_hurdle", "p_net", "p_hac"))
    assert results[1]["p_net"] <= results[2]["p_net"]


@pytest.mark.parametrize("n, expected", [(30, "INCONCLUSIVE_SHORT_SAMPLE"),
                                         (360, "INCONCLUSIVE_DEGENERATE")])
def test_unknown_hurdle_preserves_inconclusive_description(n, expected):
    zeros = pd.Series(np.zeros(n))
    result = paired_inference(zeros, zeros, annual_incremental_cost=None,
                              primary_capital=100000, repetitions=99)
    assert result["descriptive_status"] == expected
    assert result["ci95"] is None
    assert result["economic_status"] == "BLOCKED_HURDLE"


@pytest.mark.parametrize("cost", [-1, float("nan"), True])
def test_invalid_hurdle_still_rejected(cost):
    values = pd.Series(np.zeros(10))
    with pytest.raises(ValueError, match="Incremental cost"):
        paired_inference(values, values, annual_incremental_cost=cost,
                         primary_capital=100000)
