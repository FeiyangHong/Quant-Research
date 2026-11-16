import numpy as np
import pandas as pd
import pytest

from quant_research.risk_evaluation import (
    quadratic_utility, utility_inference, classify_utility, account_risk_descriptions,
)


def test_score_difference_is_not_utility_of_return_difference():
    a, b = pd.Series([.1, -.1]), pd.Series([-.1, .1])
    assert np.allclose(quadratic_utility(a) - quadratic_utility(b), [.2, -.2])
    assert not np.allclose(quadratic_utility(a - b), [.2, -.2])


def test_score_inference_cannot_expose_monetary_fields_and_retains_cash_dates():
    index = pd.date_range("2020-01-01", periods=300)
    x = pd.Series(np.random.default_rng(2).normal(0, .01, 300), index=index)
    x.iloc[:30] = 0
    result = utility_inference(x, x * .6, repetitions=101)
    assert result["n_dates"] == 300 and result["utility_ci"] is not None
    assert not set(result) & {"mean_net_increment", "primary_capital", "daily_hurdle", "p_net", "cost_capacity"}
    assert result["unit"] == "UTILITY_SCORE_PER_DAY"


def test_degenerate_score_is_inconclusive_not_zero_fee_confirmation():
    zero = pd.Series(np.zeros(300))
    result = utility_inference(zero, zero, repetitions=101)
    assert result["utility_ci"] is None
    assert classify_utility(result) == "INCONCLUSIVE"


@pytest.mark.parametrize("ci,expected", [
    ([0, .1], "INCONCLUSIVE"), ([-.1, 0], "NOT_SUPPORTED_CURRENT_RISK_RULE"),
    ([.001, .1], "DESCRIPTIVE_UTILITY_SUPPORT"),
])
def test_frozen_classification_boundaries(ci, expected):
    assert classify_utility(dict(descriptive_status="DESCRIPTIVE_INFERENCE", utility_ci=ci)) == expected


def test_fixed_tail_count_and_realized_risk_use_full_account_calendar():
    x = pd.Series([-.2] + [0.] * 60)
    result, rolling = account_risk_descriptions(x)
    assert result["tail_sample_count"] == 4
    assert result["worst_five_percent_daily_mean"] == pytest.approx(-.05)
    assert result["rolling60_count"] == 2
    assert rolling.iloc[:59].isna().all() and rolling.iloc[-1] == 0
    with pytest.raises(ValueError):
        quadratic_utility(pd.Series([0, float("nan")]))
