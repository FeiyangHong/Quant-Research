"""M9's single registered scalar basket risk estimator and three target arms.

The basket is the current *unscaled* M8 target, with synchronized historical
returns. No covariance shrinkage, NAV feedback, or parameter search is used.
"""
from dataclasses import replace
from copy import copy
import math

import numpy as np
import pandas as pd

from .liquid_cohort import generate_liquid_targets
from .provenance import digest
from .runner import dataset_hash
from .strategy import StrategyBlockedError, _cutoff, _prepare, _snapshot

RISK_SCOPE = "M9_ETF_RISK_BUDGET_V1"
CLAIM_TYPE = "RISK_ALLOCATION_EXPLORATION"
RISK_RULE = dict(window=60, min_complete=45, ddof=1, annualization=252,
                 vol_target=0.10, estimator="UNSCALED_CURRENT_BASKET_SAMPLE_STD",
                 shrinkage=False, gamma=5)


class RiskBlockedError(StrategyBlockedError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def estimate_basket_risk(dataset, anchor_date, release_date, unscaled_weights):
    """Use 60 return dates ending D, with both endpoints legal at D+1 21:00.

    An incomplete date is excluded for every member together, never filled.
    No raw TR levels or daily product returns are included in public diagnostics;
    their complete legal input records are bound by ``input_sha256``.
    """
    weights = {sid: float(value) for sid, value in sorted(unscaled_weights.items()) if value != 0}
    if not weights or any(not math.isfinite(w) or w <= 0 for w in weights.values()):
        raise RiskBlockedError("RISK_BLOCKED: nonempty positive finite basket required", {})
    if sum(weights.values()) > 1 + 1e-12:
        raise RiskBlockedError("RISK_BLOCKED: unlevered basket required", {})
    calendar = list(dataset.calendar)
    if calendar != sorted(set(calendar)) or anchor_date not in calendar:
        raise RiskBlockedError("RISK_BLOCKED: invalid anchor/calendar", {})
    end = calendar.index(anchor_date)
    if end + 1 >= len(calendar) or release_date != calendar[end + 1]:
        raise RiskBlockedError("RISK_BLOCKED: release must be D+1 actual trading day", {})
    dates = calendar[max(1, end - 59):end + 1]
    at = _cutoff(release_date)
    needed_dates = {calendar[calendar.index(day) - 1] for day in dates} | set(dates)
    original = dataset.bars.loc[dataset.bars.date.isin(needed_dates)
                                & dataset.bars.instrument_id.isin(weights)].copy()
    known = _snapshot(_prepare(original), at, ["date", "instrument_id"])
    lookup = {(row.date, row.instrument_id): row for row in known.itertuples()}
    complete, missing, inputs, basket_returns = [], [], [], []
    for day in dates:
        previous = calendar[calendar.index(day) - 1]
        reasons, member_returns, endpoints = [], [], []
        for sid, weight in weights.items():
            values = []
            for label, endpoint in (("start", previous), ("end", day)):
                row = lookup.get((endpoint, sid))
                if row is None:
                    reasons.append(f"{sid}:{label}:MISSING_OR_UNAVAILABLE_ROW")
                    continue
                clock = getattr(row, "total_return_available_at", None)
                try:
                    stamp = pd.Timestamp(clock)
                    legal_clock = not pd.isna(stamp) and stamp.tzinfo is not None and stamp <= at
                except (TypeError, ValueError):
                    legal_clock = False
                if not legal_clock:
                    reasons.append(f"{sid}:{label}:UNAVAILABLE_TR")
                    continue
                try:
                    value = float(row.total_return_index)
                except (TypeError, ValueError):
                    value = float("nan")
                if not math.isfinite(value) or value <= 0:
                    reasons.append(f"{sid}:{label}:INVALID_TR")
                    continue
                values.append(value)
                endpoints.append(dict(date=endpoint, instrument_id=sid, tr=value,
                                      available_at=pd.Timestamp(row.available_at).isoformat(),
                                      total_return_available_at=stamp.isoformat()))
            if len(values) == 2:
                value = values[1] / values[0] - 1
                if not math.isfinite(value):
                    reasons.append(f"{sid}:NONFINITE_RETURN")
                else:
                    member_returns.append(weight * value)
        if reasons:
            missing.append(dict(date=day, reasons=reasons))
        else:
            complete.append(day)
            basket_returns.append(math.fsum(member_returns))
            inputs.append(dict(date=day, endpoints=endpoints))
    result = dict(anchor_date=anchor_date, release_date=release_date, available_at=at.isoformat(),
                  window_return_dates=dates, window_start_date=dates[0] if dates else None,
                  window_end_date=dates[-1] if dates else None, complete_dates=complete,
                  complete_count=len(complete), missing=missing, unscaled_weights=weights,
                  sigma=None, alpha=None, zero_variance=False,
                  input_sha256=digest(dict(weights=weights, inputs=inputs, missing=missing)),
                  rule_hash=digest(RISK_RULE))
    if len(complete) < RISK_RULE["min_complete"]:
        raise RiskBlockedError("RISK_BLOCKED: fewer than45 complete synchronized returns", result)
    sigma = float(np.std(basket_returns, ddof=1) * np.sqrt(252))
    if not math.isfinite(sigma) or sigma < 0:
        raise RiskBlockedError("RISK_BLOCKED: unknown or nonfinite estimated volatility", result)
    result.update(sigma=sigma, alpha=1.0 if sigma == 0 else min(1.0, 0.10 / sigma),
                  zero_variance=sigma == 0)
    return result


def initialize_fixed_scale(development):
    """First nonempty legal development E0 signal; never first fill or path."""
    if development.manifest.get("sample") != "development":
        raise RiskBlockedError("RISK_BLOCKED: fixed c must initialize from development", {})
    # Generate only the first registered anchor's legal prefix. Constructing
    # later targets would make initialization depend on later input failures.
    expected_anchor = "2020-01-23"
    if expected_anchor not in development.calendar:
        raise RiskBlockedError("RISK_BLOCKED: first legal development anchor unavailable", {})
    anchor_index = development.calendar.index(expected_anchor)
    prefix = copy(development)
    prefix.calendar = development.calendar[:anchor_index + 3]
    prefix_end = prefix.calendar[-1]
    prefix.bars = development.bars.loc[development.bars.date.le(prefix_end)].copy()
    prefix.benchmark = development.benchmark.loc[development.benchmark.date.le(prefix_end)].copy()
    targets = generate_liquid_targets(prefix, "E0", execution_delay=1)
    first = next((d for d in targets if d.execution_date >= "2020-01-01" and d.weights), None)
    if first is None or first.diagnostics["signal_anchor_date"] != "2020-01-23":
        raise RiskBlockedError("RISK_BLOCKED: first legal development anchor differs from2020-01-23", {})
    anchor = first.diagnostics["signal_anchor_date"]
    risk = estimate_basket_risk(development, anchor, first.decision_date, first.weights)
    result = dict(experiment_id=RISK_SCOPE, claim_type=CLAIM_TYPE, anchor_date=anchor,
                  release_date=first.decision_date, available_at=first.decision_at.isoformat(),
                  c=risk["alpha"], unscaled_weights=first.weights, risk=risk,
                  development_data_hash=dataset_hash(development), rule_hash=digest(RISK_RULE),
                  initialized_from="FIRST_NONEMPTY_LEGAL_DEVELOPMENT_E0_SIGNAL",
                  common_to_all_periods_and_execution_paths=True, performance_evidence=False)
    result["initializer_hash"] = digest(result)
    return result


def validate_initializer(initializer):
    content = {k: v for k, v in initializer.items() if k != "initializer_hash"}
    if initializer.get("initializer_hash") != digest(content):
        raise RiskBlockedError("RISK_BLOCKED: initializer content hash mismatch", {})
    if (initializer.get("experiment_id") != RISK_SCOPE or initializer.get("anchor_date") != "2020-01-23"
            or initializer.get("release_date") != "2020-02-03"
            or initializer.get("available_at") != _cutoff("2020-02-03").isoformat()
            or initializer.get("rule_hash") != digest(RISK_RULE)
            or type(initializer.get("c")) not in (int, float)
            or not math.isfinite(initializer["c"]) or not 0 < initializer["c"] <= 1
            or initializer["c"] != initializer.get("risk", {}).get("alpha")):
        raise RiskBlockedError("RISK_BLOCKED: initializer rule/anchor/value mismatch", {})


def generate_risk_targets(dataset, variant, initializer, execution_delay=1):
    if variant not in ("VE", "CE", "VR"):
        raise ValueError("Only VE, CE, VR are registered")
    validate_initializer(initializer)
    base_variant = "R0" if variant == "VR" else "E0"
    start = dataset.manifest.get("funded_account_start", "2020-01-01")
    decisions = []
    for base in generate_liquid_targets(dataset, base_variant, execution_delay):
        if base.execution_date < start:
            continue
        diagnostics = dict(base.diagnostics, universe=RISK_SCOPE, variant=variant,
                           base_variant=base_variant, risk_scaling=True,
                           unscaled_weights=dict(base.weights), fixed_c=initializer["c"],
                           initializer_hash=initializer["initializer_hash"], risk=None,
                           alpha_applied=None, scaling_policy="FIXED_C" if variant == "CE" else "DYNAMIC")
        weights = {}
        if base.weights:
            try:
                risk = estimate_basket_risk(dataset, base.diagnostics["signal_anchor_date"],
                                           base.decision_date, base.weights)
            except RiskBlockedError as error:
                if variant != "CE":
                    raise
                # CE needs only the frozen legal initializer and today's E0.
                # Missing contemporary diagnostic risk does not turn it to cash.
                risk = dict(error.diagnostics, status="BLOCKED_DIAGNOSTIC", reason=str(error))
            alpha = initializer["c"] if variant == "CE" else risk["alpha"]
            weights = {sid: weight * alpha for sid, weight in base.weights.items()}
            diagnostics.update(risk=risk, alpha_applied=alpha)
        diagnostics["target_gross_weight"] = sum(weights.values())
        decisions.append(replace(base, weights=weights, diagnostics=diagnostics))
    return decisions
