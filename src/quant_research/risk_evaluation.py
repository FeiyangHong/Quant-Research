"""M9 score units remain separate from net returns and monetary hurdles."""
import math

import numpy as np
import pandas as pd

from .evaluation import paired_inference

GAMMA = 5


def quadratic_utility(returns):
    values = returns.astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("Utility requires complete finite net returns")
    return values - 2.5 * values * values


def utility_inference(candidate, baseline, *, block_length=60, repetitions=5000, seed=20261114):
    """Reuse the numerical paired kernel, exporting only score-appropriate fields.

    Capital is an unused required kernel argument when fixed cost is None.
    No monetary hurdle, economic test or cost capacity is computed for utility.
    """
    raw = paired_inference(quadratic_utility(candidate), quadratic_utility(baseline),
                           annual_incremental_cost=None, primary_capital=1,
                           block_length=block_length, repetitions=repetitions, seed=seed)
    result = {key: raw[key] for key in ("n_dates", "block_length", "repetitions", "seed",
              "interval_type", "method", "descriptive_status")}
    result.update(mean_utility_difference=raw["mean_net_increment"], utility_ci=raw["ci95"],
                  gamma=GAMMA, unit="UTILITY_SCORE_PER_DAY",
                  annualized_score_multiplier=252, monetary_interpretation=False)
    for key in ("hac_lag", "hac_se", "caveat"):
        if key in raw:
            result[key] = raw[key]
    return result


def classify_utility(interval):
    ci = interval.get("utility_ci")
    if interval.get("descriptive_status") != "DESCRIPTIVE_INFERENCE" or ci is None:
        return "INCONCLUSIVE"
    if ci[0] > 0:
        return "DESCRIPTIVE_UTILITY_SUPPORT"
    if ci[1] <= 0:
        return "NOT_SUPPORTED_CURRENT_RISK_RULE"
    return "INCONCLUSIVE"


def account_risk_descriptions(returns):
    """Fixed lower-tail count and realized account risk, including cash dates."""
    values = returns.astype(float)
    if values.empty or not np.isfinite(values.to_numpy()).all():
        raise ValueError("Account risk descriptions need complete finite returns")
    count = math.ceil(.05 * len(values))
    rolling = values.rolling(60, min_periods=60).std(ddof=1) * np.sqrt(252)
    valid = rolling.dropna()
    return dict(mean_utility=float(quadratic_utility(values).mean()), cash_mean_utility=0.,
                tail_fraction=.05, tail_sample_count=count, total_sample_count=len(values),
                worst_five_percent_daily_mean=float(values.nsmallest(count).mean()),
                rolling60_count=len(valid),
                rolling60_above_10pct_count=int((valid > .10).sum()),
                rolling60_above_10pct_fraction=float((valid > .10).mean()) if len(valid) else None,
                rolling60_volatility_quantiles={str(q): float(valid.quantile(q)) for q in (0,.25,.5,.75,1)}
                    if len(valid) else {},
                rolling60_definition="60 complete net account returns, ddof1 sqrt252; no warmup NAV"), rolling
