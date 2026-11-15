"""Paired, time-dependent inference. Never treat securities as independent days."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm


def holm_four(pvalues):
    """The four preregistered families always remain in the family."""
    if set(pvalues) - {"R1", "R2", "R3", "R4"}:
        raise ValueError("Only the four registered families are supported")
    values = {k: float(pvalues.get(k, 1.0)) for k in ("R1", "R2", "R3", "R4")}
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in values.values()):
        raise ValueError("Invalid p-value")
    ordered = sorted(values, key=values.get)
    running = 0.0
    result = {}
    for i, key in enumerate(ordered):
        running = max(running, min(1.0, (4 - i) * values[key]))
        result[key] = running
    return result


def _hac_se(x, lag):
    x = np.atleast_2d(x)
    n = x.shape[1]
    centered = x - x.mean(axis=1, keepdims=True)
    lrv = np.mean(centered * centered, axis=1)
    for k in range(1, min(lag + 1, n)):
        lrv += 2 * (1 - k / (lag + 1)) * np.sum(centered[:, k:] * centered[:, :-k], axis=1) / n
    return np.sqrt(np.maximum(lrv, 0) / n)


def paired_inference(candidate: pd.Series, baseline: pd.Series, *, annual_incremental_cost: Optional[float],
                     primary_capital: float, block_length=60, repetitions=5000, seed=20261114):
    """Circular moving-block bootstrap-t centered at H0 boundary, HAC studentized.

    Inputs are net daily returns on identical dates; costs paid in the NAV must
    not be included again in annual_incremental_cost. CI is marginal, not simultaneous.
    """
    if not candidate.index.equals(baseline.index) or candidate.index.has_duplicates:
        raise ValueError("Paired returns require identical unique dates")
    if not candidate.index.is_monotonic_increasing:
        raise ValueError("Returns must be in chronological order")
    if (isinstance(primary_capital, bool) or not isinstance(primary_capital, (int, float))
            or not math.isfinite(primary_capital) or primary_capital <= 0
            or type(block_length) is not int or block_length < 2
            or type(repetitions) is not int or repetitions < 99):
        raise ValueError("Invalid inference settings")
    d = candidate.to_numpy(dtype=float) - baseline.to_numpy(dtype=float)
    if not np.isfinite(d).all():
        raise ValueError("Missing/invalid returns cannot silently be dropped")
    result = {"n_dates": len(d), "block_length": block_length, "repetitions": repetitions,
              "seed": seed, "mean_net_increment": float(d.mean()) if len(d) else None,
              "interval_type": "marginal_95_percent", "method": "circular_block_bootstrap_t_HAC"}
    if annual_incremental_cost is not None and (
            isinstance(annual_incremental_cost, bool) or not isinstance(annual_incremental_cost, (int, float))
            or not math.isfinite(annual_incremental_cost) or annual_incremental_cost < 0):
        raise ValueError("Incremental cost must be finite and nonnegative")
    h = None if annual_incremental_cost is None else annual_incremental_cost / (primary_capital * 252)
    if h is not None and not math.isfinite(h):
        raise ValueError("Economic hurdle must be finite")
    result.update(annual_incremental_cost=annual_incremental_cost, daily_hurdle=h,
                  p_net=None, p_hac=None, ci95=None,
                  economic_status="BLOCKED_HURDLE" if h is None else "HURDLE_SPECIFIED")

    def finish(descriptive_status, **values):
        # Unknown fixed fees block economic confirmation, never the descriptive
        # interval of the supplied transaction-cost-net paired returns.
        return dict(result, status="BLOCKED_HURDLE" if h is None else descriptive_status,
                    descriptive_status=descriptive_status, **values)

    n = len(d)
    if n < max(120, 2 * block_length):
        return finish("INCONCLUSIVE_SHORT_SAMPLE")
    lag = max(1, int(4 * (n / 100) ** (2 / 9)))
    se = float(_hac_se(d, lag)[0])
    if se <= 1e-15:
        return finish("INCONCLUSIVE_DEGENERATE")
    centered = d - d.mean()  # null bootstrap: E[d*] = h, so E[d*-h] = 0
    rng = np.random.default_rng(seed)
    statistics = []
    for start in range(0, repetitions, 128):
        count = min(128, repetitions - start)
        starts = rng.integers(0, n, size=(count, math.ceil(n / block_length)))
        indices = ((starts[..., None] + np.arange(block_length)) % n).reshape(count, -1)[:, :n]
        sample = centered[indices]
        sample_se = _hac_se(sample, lag)
        if (sample_se <= 1e-15).any():
            return finish("INCONCLUSIVE_DEGENERATE_BOOTSTRAP")
        statistics.extend(sample.mean(axis=1) / sample_se)
    t = np.asarray(statistics)
    lower, upper = np.quantile(t, [0.025, 0.975])
    if h is not None:
        observed_t = (float(d.mean()) - h) / se
        result.update(p_net=float((1 + (t >= observed_t).sum()) / (repetitions + 1)),
                      p_hac=float(norm.sf(observed_t)))
    return finish("DESCRIPTIVE_INFERENCE", hac_lag=lag, hac_se=se,
                ci95=[float(d.mean() - upper * se), float(d.mean() - lower * se)],
                minimum_detectable_daily_effect_80pct=float((norm.ppf(.95) + norm.ppf(.8)) * se),
                caveat="Approximate under weak stationarity; short/nonstationary histories need caution.")


def nav_metrics(nav: pd.DataFrame, initial_cash: float):
    """Calendar-span CAGR; the first-day return includes opening trading costs."""
    if nav.empty:
        return {"status": "NOT_RUN"}
    equity = nav["nav"].astype(float)
    if (equity <= 0).any() or not np.isfinite(equity).all():
        raise ValueError("NAV must be finite and positive")
    previous = equity.shift(1).fillna(initial_cash)
    returns = equity / previous - 1
    peak = np.maximum.accumulate(np.r_[initial_cash, equity.to_numpy()])[1:]
    drawdown = equity.to_numpy() / peak - 1
    duration = longest = 0
    for value in drawdown:
        duration = duration + 1 if value < -1e-12 else 0
        longest = max(longest, duration)
    dates = pd.to_datetime(nav["date"])
    days = max(1, (dates.iloc[-1] - dates.iloc[0]).days + 1)
    vol = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else 0.0
    total = float(equity.iloc[-1] / initial_cash - 1)
    return {"total_return": total, "cagr": float((1 + total) ** (365.25 / days) - 1),
            "annual_volatility": vol, "sharpe_zero_cash": float(returns.mean() * 252 / vol) if vol else None,
            "max_drawdown": float(drawdown.min()), "max_drawdown_duration_sessions": longest,
            "worst_day": float(returns.min()), "n_sessions": len(nav),
            "warning": "Historical or synthetic simulation only; not realized account profit."}


def mature_training_rows(labels: pd.DataFrame, cutoff):
    """Purge labels crossing the fit cutoff, including validation-year tails."""
    boundary = pd.Timestamp(cutoff)
    if boundary.tzinfo is None:
        raise ValueError("Timezone-aware fit cutoff required")
    end = pd.to_datetime(labels["label_available_at"], utc=True)
    return labels.loc[end < boundary].copy()
