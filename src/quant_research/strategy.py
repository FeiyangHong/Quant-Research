"""Pre-registered R1B monthly targets; all observations are queried as-of.

An empty ``weights`` is an explicit cash target, not absence of a decision.
The execution engine must union these targets with existing holdings, preserve
blocked sales, and use raw prices and real share counts in its account ledger.
"""
from dataclasses import dataclass, field
from bisect import bisect_left
from typing import Any, Dict, List

import numpy as np
import pandas as pd


class StrategyBlockedError(ValueError):
    """The requested research universe lacks its mandatory data contract."""


@dataclass
class TargetDecision:
    decision_date: str
    execution_date: str
    decision_at: pd.Timestamp
    weights: Dict[str, float]
    reference_prices: Dict[str, float]
    adv20: Dict[str, float]
    ranks: Dict[str, int] = field(default_factory=dict)
    status: str = "OK"
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "available_at" not in result:
        raise StrategyBlockedError("BLOCKED_DATA: missing available_at")
    stamps = [pd.Timestamp(value) for value in result["available_at"]]
    if any(pd.isna(value) or value.tzinfo is None for value in stamps):
        raise StrategyBlockedError("BLOCKED_DATA: available_at must have a timezone")
    result["_available"] = pd.to_datetime(stamps, utc=True)
    return result


def _snapshot(frame: pd.DataFrame, at: pd.Timestamp, keys: List[str],
              master: bool = False) -> pd.DataFrame:
    day = at.strftime("%Y-%m-%d")
    keep = frame["_available"] <= at
    if "date" in frame:
        keep &= frame["date"] <= day
    if master:
        for column, compare in (("effective_from", "le"), ("effective_to", "gt")):
            if column in frame:
                # Effective dates are interpreted in the exchange timezone.
                dates = frame[column].map(
                    lambda x: pd.Timestamp(x).strftime("%Y-%m-%d") if pd.notna(x) and x != "" else None)
                keep &= dates.isna() | (dates.le(day) if compare == "le" else dates.gt(day))
    result = frame.loc[keep].sort_values("_available", kind="stable")
    if result.duplicated(keys + ["_available"]).any():
        raise StrategyBlockedError("BLOCKED_DATA: ambiguous revisions at equal available_at")
    return result.drop_duplicates(keys, keep="last").copy()


def _cutoff(day: str) -> pd.Timestamp:
    return pd.Timestamp(day + " 21:00:00", tz="Asia/Shanghai")


def _active_etfs(master: pd.DataFrame, day: str) -> pd.DataFrame:
    keep = (master["asset_type"] == "ETF") & master["account_verified"].eq(True)
    keep &= master["listed_on"].le(day)
    if "delisted_on" in master:
        keep &= master["delisted_on"].isna() | master["delisted_on"].eq("") | master["delisted_on"].gt(day)
    if "strategy_universe" in master:
        keep &= master["strategy_universe"].eq("R1B")
    else:
        # A broad-market identity is required, not inferred from an ETF label.
        keep &= master["benchmark_id"].isin(
            ["CSI300", "CSI500", "CSI1000", "CHINEXT", "STAR", "BSE",
             "000300", "000905", "000852", "399006", "000688", "899050"])
    return master.loc[keep].copy()


def _matrix(bars: pd.DataFrame, column: str, dates: List[str]) -> pd.DataFrame:
    # Keep every historically observed column, including funds absent from the
    # requested window. Its sorted order is also used by downstream statistics.
    # Other dtypes retain pandas' original promotion/category-order rules.
    if (bars[column].dtype != np.dtype("float64")
            or isinstance(bars["instrument_id"].dtype, pd.CategoricalDtype)
            or bars["instrument_id"].hasnans):
        return bars.pivot(index="date", columns="instrument_id", values=column).reindex(dates)
    columns = pd.Index(bars["instrument_id"].unique(), name="instrument_id").sort_values()
    window = bars.loc[bars["date"].isin(dates), ["date", "instrument_id", column]]
    return window.pivot(index="date", columns="instrument_id", values=column).reindex(index=dates, columns=columns)


def _representatives(instruments: pd.DataFrame, bars: pd.DataFrame,
                     calendar: List[str], previous_index: int) -> List[str]:
    if previous_index < 59:
        return []
    previous = calendar[previous_index]
    at = _cutoff(previous)
    master = _active_etfs(_snapshot(instruments, at, ["instrument_id"], True), previous)
    history = _snapshot(bars, at, ["date", "instrument_id"])
    amounts = _matrix(history, "amount", calendar[previous_index - 59:previous_index + 1])
    mean = amounts.where(np.isfinite(amounts) & amounts.ge(0)).mean()
    count = amounts.where(np.isfinite(amounts) & amounts.ge(0)).count()
    master["_adv60"] = master["instrument_id"].map(mean)
    master["_count"] = master["instrument_id"].map(count)
    current = history.loc[history["date"].eq(previous)].set_index("instrument_id")
    normal = current.loc[current["suspended"].eq(False)].index
    master = master.loc[master["_count"].eq(60) & master["instrument_id"].isin(normal)
                        & master["benchmark_id"].notna() & master["benchmark_id"].ne("")]
    master = master.sort_values(["benchmark_id", "_adv60", "listed_on", "instrument_id"],
                                ascending=[True, False, True, True])
    return sorted(master.drop_duplicates("benchmark_id")["instrument_id"].tolist())


def _risk_multiplier(tr: pd.DataFrame, weights: Dict[str, float]):
    # pct_change(fill_method=None) must precede dropping incomplete dates, so
    # missing sessions cannot become artificial multi-session daily returns.
    returns = tr[list(weights)].pct_change(fill_method=None).iloc[-60:]
    complete = returns.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    if len(complete) < 45:
        return 0.0, None, len(complete)
    covariance = complete.cov(ddof=1).to_numpy()
    shrunk = .5 * covariance + .5 * np.diag(np.diag(covariance))
    vector = np.array(list(weights.values()))
    variance = float(vector @ shrunk @ vector) * 252.0
    sigma = float(np.sqrt(max(0.0, variance)))
    return (min(1.0, .10 / sigma) if sigma > 0 else 1.0), sigma, len(complete)


def generate_targets(dataset, variant: str = "E0", risk_scaling: bool = False,
                     execution_delay: int = 1, universe: str = "R1B", signal_release_delay: int = 0) -> List[TargetDecision]:
    """Return monthly targets, including cash decisions and diagnostic reasons.

    Only a supplied exchange calendar determines month/quarter boundaries. At
    least one later session is needed to establish month-end and schedule a
    target. A truncated dataset therefore never guesses its last day is month-end.
    R1I is intentionally blocked until a separate PIT industry mapping is wired.
    """
    if universe != "R1B":
        raise StrategyBlockedError("BLOCKED_DATA: R1I requires verified PIT industry mapping")
    if variant not in {"E0", "R0", "E1", "R1"}:
        raise ValueError("variant must be E0, R0, E1 or R1")
    if isinstance(execution_delay, bool) or not isinstance(execution_delay, int) or execution_delay < 1:
        raise ValueError("execution_delay must be an integer >= 1 trading session")
    if type(signal_release_delay) is not int or signal_release_delay not in (0, 1):
        raise ValueError("signal_release_delay must be zero or one session")
    calendar = list(dataset.calendar)
    if calendar != sorted(set(calendar)):
        raise ValueError("calendar must contain unique, ascending ISO dates")
    instruments = _prepare(dataset.instruments)
    # Provenance/execution fields do not enter any strategy formula. Avoid
    # copying their wide payload for every point-in-time monthly snapshot.
    bar_columns = ["date", "instrument_id", "close", "amount", "suspended",
                   "available_at", "total_return_index"]
    if "total_return_available_at" in dataset.bars:
        bar_columns.append("total_return_available_at")
    bars = _prepare(dataset.bars[bar_columns])
    if "total_return_available_at" in bars:
        # Invalid clocks in not-yet-visible rows must not break an earlier
        # prefix. Preserve the original error only if that row becomes visible.
        bars["_tr_available"] = pd.to_datetime(bars.total_return_available_at, utc=True, format="mixed", errors="coerce")
    benchmark = _prepare(dataset.benchmark)
    decisions = []
    quarter = None
    representatives = []
    representative_at = None
    for index, day in enumerate(calendar):
        timestamp = pd.Timestamp(day)
        this_quarter = (timestamp.year, timestamp.quarter)
        if this_quarter != quarter:
            representatives = _representatives(instruments, bars, calendar, index - 1)
            representative_at = calendar[index - 1] if index else None
            quarter = this_quarter
        if index + signal_release_delay + execution_delay >= len(calendar) or day[:7] == calendar[index + 1][:7]:
            continue
        anchor_at = _cutoff(day)
        decision_day = calendar[index + signal_release_delay]
        at = _cutoff(decision_day)
        history = _snapshot(bars, at, ["date", "instrument_id"])
        # Delayed publication changes when the target is released, not its
        # economic observation window or historical candidate qualification.
        history = history.loc[history.date.le(day)]
        if "_tr_available" in history:
            tr_known = history["_tr_available"]
            unresolved = tr_known.isna() & history.total_return_available_at.notna()
            if unresolved.any():
                pd.to_datetime(history.loc[unresolved, "total_return_available_at"], utc=True, format="mixed", errors="raise")
            history.loc[tr_known.isna() | tr_known.gt(at), "total_return_index"] = np.nan
        master = _active_etfs(_snapshot(instruments, anchor_at, ["instrument_id"], True), day)
        current = history.loc[history["date"].eq(day)].set_index("instrument_id")
        amounts = _matrix(history, "amount", calendar[max(0, index - 19):index + 1])
        amounts = amounts.where(np.isfinite(amounts) & amounts.ge(0))
        counts, medians, averages = amounts.count(), amounts.median(), amounts.mean()
        references = {str(name): float(value) for name, value in current["close"].items()
                      if pd.notna(value) and np.isfinite(value) and value > 0}
        adv = {str(name): float(value) for name, value in averages.items()
               if counts[name] == 20 and pd.notna(value) and np.isfinite(value) and value > 0}
        eligible, exclusions = [], {}
        available_master = master.set_index("instrument_id")
        for name in representatives:
            reason = None
            if name not in available_master.index:
                reason = "inactive_or_unverified"
            elif index - bisect_left(calendar, available_master.loc[name, "listed_on"]) + 1 < 252:
                reason = "listed_less_than_252_sessions"
            elif name not in current.index or not current.loc[name, "suspended"] == False:
                reason = "no_current_normal_quote"
            elif name not in references:
                reason = "invalid_reference_price"
            elif name not in counts or counts[name] != 20 or medians[name] < 20_000_000:
                reason = "insufficient_20_session_liquidity"
            if reason:
                exclusions[name] = reason
            else:
                eligible.append(name)
        diagnostics = {"universe": universe, "variant": variant,
                       "signal_anchor_date": day, "signal_anchor_at": anchor_at.isoformat(),
                       "signal_release_delay": signal_release_delay, "order_reference_date": decision_day,
                       "representative_at": representative_at,
                       "representatives": list(representatives), "eligible": eligible,
                       "exclusions": exclusions, "top3_comparable": len(eligible) >= 3,
                       "risk_scaling": risk_scaling}
        weights, ranks = {}, {}
        status = "OK"
        if not eligible:
            status = "BLOCKED_INSUFFICIENT_ETFS"
        elif variant in {"R0", "R1"} and len(eligible) < 3:
            status = "BLOCKED_INSUFFICIENT_ETFS"
        else:
            selected = eligible
            if variant in {"R0", "R1"}:
                tr = _matrix(history, "total_return_index", calendar[:index + 1])
                momentum = {}
                if index >= 126:
                    for name in eligible:
                        recent, old = tr.loc[calendar[index - 21], name], tr.loc[calendar[index - 126], name]
                        if np.isfinite(recent) and np.isfinite(old) and recent > 0 and old > 0:
                            momentum[name] = float(np.log(recent / old))
                diagnostics["momentum"] = momentum
                if len(momentum) != len(eligible):
                    status = "BLOCKED_MOMENTUM_DATA"
                    selected = []
                else:
                    ordered = sorted(momentum, key=lambda name: (-momentum[name], name))
                    ranks = {name: rank for rank, name in enumerate(ordered, 1)}
                    selected = ordered[:3]
            else:
                ranks = {name: rank for rank, name in enumerate(eligible, 1)}
            if selected:
                weights = {name: min(.35, 1.0 / len(selected)) for name in selected}
        if weights and variant in {"E1", "R1"}:
            market = _snapshot(benchmark, at, ["date"])
            market = market.loc[market.date.le(day)].set_index("date")
            trend_window = market["total_return_index"].reindex(calendar[max(0, index - 199):index + 1])
            if len(trend_window) != 200 or not (np.isfinite(trend_window) & trend_window.gt(0)).all():
                status, weights = "BLOCKED_BENCHMARK_HISTORY", {}
                diagnostics["trend"] = None
            else:
                trend = bool(trend_window.iloc[-1] > trend_window.mean())
                diagnostics["trend"] = trend
                if not trend:
                    status, weights = "CASH_TREND_OFF", {}
        if weights and risk_scaling:
            tr = _matrix(history, "total_return_index", calendar[max(0, index - 60):index + 1])
            tr = tr.where(np.isfinite(tr) & tr.gt(0))
            multiplier, sigma, complete = _risk_multiplier(tr, weights)
            diagnostics.update(risk_multiplier=multiplier, annualized_sigma=sigma,
                               complete_risk_sessions=complete)
            if complete < 45:
                status, weights = "BLOCKED_RISK_HISTORY", {}
            else:
                weights = {name: weight * multiplier for name, weight in weights.items()}
        diagnostics["target_gross_weight"] = sum(weights.values())
        if signal_release_delay:
            # These inputs size orders and cap participation only. They must
            # never re-rank funds or revise the anchor-date eligibility pool.
            order_history = _snapshot(bars, at, ["date", "instrument_id"])
            order_current = order_history.loc[order_history.date.eq(decision_day)].set_index("instrument_id")
            references = {str(name): float(value) for name, value in order_current.close.items()
                          if pd.notna(value) and np.isfinite(value) and value > 0}
            order_amounts = _matrix(order_history, "amount", calendar[max(0, index + signal_release_delay - 19):index + signal_release_delay + 1])
            order_amounts = order_amounts.where(np.isfinite(order_amounts) & order_amounts.ge(0))
            order_count, order_mean = order_amounts.count(), order_amounts.mean()
            adv = {str(name): float(value) for name, value in order_mean.items()
                   if order_count[name] == 20 and pd.notna(value) and np.isfinite(value) and value > 0}
        decisions.append(TargetDecision(decision_day, calendar[index + signal_release_delay + execution_delay], at,
                                        weights, references, adv, ranks, status, diagnostics))
    return decisions
