"""M7 reviewer-owned synthetic oracle; no production inference helpers reused."""
import math
import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation import paired_inference


def observations(n=360):
    t = np.arange(n, dtype=float)
    index = pd.date_range("2019-01-01", periods=n, freq="B")
    base = pd.Series(0.001 * np.cos(t / 11), index=index)
    delta = 0.0001 + 0.002 * np.sin(t / 7) + 0.001 * np.cos(t / 17)
    return base + delta, base


def independent_standard_error(values, lag):
    centered = values - np.mean(values, axis=-1, keepdims=True)
    n = values.shape[-1]
    variance = np.sum(centered ** 2, axis=-1) / n
    for k in range(1, lag + 1):
        weight = (lag + 1 - k) / (lag + 1)
        variance += 2 * weight * np.sum(centered[..., :-k] * centered[..., k:], axis=-1) / n
    return np.sqrt(np.maximum(variance, 0) / n)


def oracle(candidate, baseline, block, draws=5000):
    d = np.asarray(candidate) - np.asarray(baseline)
    n = len(d)
    lag = int(4 * (n / 100) ** (2 / 9))
    se = independent_standard_error(d, lag)
    # Draw all offsets together, independent implementation of the frozen
    # circular, synchronized calendar resampling protocol.
    rng = np.random.default_rng(20261114)
    starts = rng.integers(0, n, (draws, math.ceil(n / block)))
    indexes = np.concatenate([(starts[:, j, None] + np.arange(block)) % n
                              for j in range(starts.shape[1])], axis=1)[:, :n]
    samples = (d - np.mean(d))[indexes]
    t = samples.mean(axis=1) / independent_standard_error(samples, lag)
    low, high = np.quantile(t, [.025, .975])
    return float(d.mean()), [float(d.mean() - high * se), float(d.mean() - low * se)], t, se


@pytest.mark.parametrize("block", [20, 60, 120])
def test_mean_and_descriptive_ci_independent_of_unknown_zero_positive_cost(block):
    candidate, baseline = observations()
    results = [paired_inference(candidate, baseline, annual_incremental_cost=cost,
                               primary_capital=100000, block_length=block,
                               repetitions=5000, seed=20261114)
               for cost in (None, 0, 1000)]
    expected_mean, expected_ci, t, se = oracle(candidate, baseline, block)
    assert all(r["mean_net_increment"] == results[0]["mean_net_increment"] for r in results)
    assert all(r["ci95"] == results[0]["ci95"] for r in results)
    assert results[0]["mean_net_increment"] == pytest.approx(expected_mean, abs=1e-17)
    assert results[0]["ci95"] == pytest.approx(expected_ci, abs=1e-15)
    unknown = results[0]
    assert unknown["status"] == "BLOCKED_HURDLE"
    for field in ("annual_incremental_cost", "daily_hurdle", "p_net", "p_hac"):
        assert field in unknown and unknown[field] is None
    for cost, result in zip((0, 1000), results[1:]):
        hurdle = cost / (100000 * 252)
        expected_p = (1 + np.sum(t >= (expected_mean - hurdle) / se)) / 5001
        assert result["daily_hurdle"] == hurdle
        assert result["p_net"] == expected_p
    assert results[2]["p_net"] >= results[1]["p_net"]


@pytest.mark.parametrize("case", ["short", "constant", "degenerate_bootstrap"])
@pytest.mark.parametrize("cost", [None, 0, 1000])
def test_inconclusive_description_is_separate_from_economic_gate(case, cost):
    candidate, baseline = observations(100 if case == "short" else 360)
    if case == "constant":
        candidate, baseline = baseline * 0 + .001, baseline * 0
    elif case == "degenerate_bootstrap":
        candidate, baseline = baseline * 0, baseline * 0
        candidate.iloc[0] = .1
    result = paired_inference(candidate, baseline, annual_incremental_cost=cost,
                              primary_capital=100000, repetitions=5000)
    assert result["ci95"] is None and result["p_net"] is None
    assert result.get("p_hac") is None
    descriptive = result.get("descriptive_status", result["status"])
    assert descriptive == {"short": "INCONCLUSIVE_SHORT_SAMPLE",
                           "constant": "INCONCLUSIVE_DEGENERATE",
                           "degenerate_bootstrap": "INCONCLUSIVE_DEGENERATE_BOOTSTRAP"}[case]
    if cost is None:
        assert result["status"] == "BLOCKED_HURDLE"


def test_pairing_preserves_missing_calendar_dates_and_finite_values():
    candidate, baseline = observations()
    with pytest.raises(ValueError):
        paired_inference(candidate.iloc[1:], baseline.iloc[:-1],
                         annual_incremental_cost=None, primary_capital=100000)
    candidate.iloc[20] = np.nan
    with pytest.raises(ValueError):
        paired_inference(candidate, baseline, annual_incremental_cost=None,
                         primary_capital=100000)
