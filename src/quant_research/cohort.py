"""The registered seven-product cohort; no industry representative competition.

Qualification uses raw amounts before any return dependency is inspected.
Unknown input raises rather than manufacturing a successful cash decision.
"""
from bisect import bisect_left

import numpy as np
import pandas as pd

from .strategy import StrategyBlockedError, TargetDecision, _cutoff, _prepare, _snapshot
from .temporal import master_record, TemporalStateError


COHORT_SCOPE = "R1I_FIXED_COHORT_V1"
FIXED_COHORT = ("sz.159936", "sz.159938", "sz.159939", "sz.159940",
                "sz.159944", "sz.159945", "sz.159946")
COHORT_AVAILABLE_AT = "2016-01-05T21:00:00+08:00"


def _blocked(day, sid, field):
    raise StrategyBlockedError(f"DATA_BLOCKED_COHORT: {day} {sid} {field}")


def _check_scope(dataset):
    if dataset.manifest.get("research_scope") != COHORT_SCOPE:
        raise StrategyBlockedError("DATA_BLOCKED_COHORT: explicit research_scope required")
    if set(dataset.instruments.instrument_id) != set(FIXED_COHORT):
        raise StrategyBlockedError("DATA_BLOCKED_COHORT: all and only seven registered identities required")
    if not dataset.instruments.strategy_universe.eq(COHORT_SCOPE).all():
        raise StrategyBlockedError("DATA_BLOCKED_COHORT: master scope mismatch")
    if not dataset.bars.instrument_id.isin(FIXED_COHORT).all():
        raise StrategyBlockedError("DATA_BLOCKED_COHORT: foreign bar identity")
    calendar = list(dataset.calendar)
    if not calendar or calendar != sorted(set(calendar)) or any(d >= "2025-01-01" for d in calendar):
        raise StrategyBlockedError("DATA_BLOCKED_COHORT: sorted pre-2025 calendar required")
    return calendar


def cohort_dependencies(dataset):
    """Recompute monthly raw-data qualification without reading TR or returns.

    Only complete N>=3 months create ranking/order dependencies. N<3 is
    common cash for all four rules. A product never reaching such a month
    remains present and can have amount-only bars without invented TR.
    """
    calendar = _check_scope(dataset)
    bars = _prepare(dataset.bars[["date", "instrument_id", "amount", "suspended", "available_at"]])
    master = {sid: group.to_dict("records") for sid, group in dataset.instruments.groupby("instrument_id")}
    schedule, required, qualified = [], set(), set()
    for index, day in enumerate(calendar):
        if index + 2 >= len(calendar) or day[:7] == calendar[index + 1][:7]:
            continue
        release, execution = calendar[index + 1], calendar[index + 2]
        if execution < "2016-01-01":
            continue
        entry = dict(anchor_date=day, release_date=release, execution_date=execution)
        if _cutoff(day) < pd.Timestamp(COHORT_AVAILABLE_AT):
            schedule.append(dict(entry, status="CASH_COHORT_NOT_YET_KNOWN", eligible=[],
                                 eligible_count=None, exclusions={}, qualification={}))
            continue
        history = _snapshot(bars, _cutoff(release), ["date", "instrument_id"])
        history = history.loc[history.date.le(day)]
        eligible, exclusions, qualification = [], {}, {}
        for sid in FIXED_COHORT:
            try:
                meta = master_record(master[sid], _cutoff(day))
            except TemporalStateError as exc:
                _blocked(day, sid, str(exc))
            if meta is None:
                _blocked(day, sid, "missing as-of identity/state")
            if meta.get("asset_type") != "ETF" or meta.get("board") != "ETF":
                _blocked(day, sid, "unverified ETF identity")
            if not isinstance(meta.get("account_verified"), (bool, np.bool_)):
                _blocked(day, sid, "unknown account permission")
            if not meta["account_verified"] and meta.get("account_permission_status") != "DENIED":
                _blocked(day, sid, "unverified account permission is not a known denial")
            status = meta.get("status")
            if status not in ("NORMAL", "ACTIVE", "SUSPENDED", "ECONOMIC_IDENTITY_CHANGED", "RETIRED"):
                _blocked(day, sid, "unknown instrument status")
            listed = meta.get("listed_on")
            if not isinstance(listed, str):
                _blocked(day, sid, "unknown listed_on")
            if listed < calendar[0]:
                _blocked(day, sid, "calendar does not cover listing age")
            age = max(0, index - bisect_left(calendar, listed) + 1)
            evidence = dict(listed_sessions=age, status=status, account_verified=bool(meta["account_verified"]))
            reason = None
            retired = meta.get("delisted_on")
            if listed > day:
                reason = "NOT_YET_LISTED"
            elif pd.notna(retired) and retired and retired <= day:
                reason = "DELISTED"
            elif pd.notna(retired) and retired:
                reason = "ANNOUNCED_DELISTING"
            elif status not in ("NORMAL", "ACTIVE"):
                reason = status
            elif not meta["account_verified"]:
                reason = "PERMISSION_DENIED"
            elif age < 252:
                reason = "LISTED_LESS_THAN_252_SESSIONS"
            else:
                window = history.loc[history.instrument_id.eq(sid)].set_index("date").reindex(calendar[index - 19:index + 1])
                amount = pd.to_numeric(window.amount, errors="coerce")
                if len(window) != 20 or not (np.isfinite(amount) & amount.ge(0)).all():
                    _blocked(day, sid, "incomplete 20-session amount")
                if not window.suspended.map(lambda v: isinstance(v, (bool, np.bool_))).all():
                    _blocked(day, sid, "unknown suspension state")
                if (window.suspended & amount.ne(0)).any():
                    _blocked(day, sid, "suspended state conflicts with turnover")
                evidence["median_amount20"] = float(amount.median())
                if bool(window.suspended.iloc[-1]):
                    reason = "SUSPENDED"
                elif amount.median() < 20_000_000:
                    reason = "MEDIAN_AMOUNT_BELOW_20000000"
            qualification[sid] = evidence
            if reason:
                exclusions[sid] = reason
            else:
                eligible.append(sid)
        qualified.update(eligible)
        if len(eligible) >= 3:
            required.update(eligible)
        schedule.append(dict(entry, status="QUALIFIED_INPUTS", eligible=eligible,
                             eligible_count=len(eligible), exclusions=exclusions, qualification=qualification))
    return dict(method="REGISTERED_FIXED_COHORT_MONTHLY_AMOUNT_ONLY", research_scope=COHORT_SCOPE,
                depends_on_returns=False, cohort=list(FIXED_COHORT),
                cohort_available_at=COHORT_AVAILABLE_AT, schedule=schedule,
                required_full_history_instruments=sorted(required),
                qualified_instruments=sorted(qualified),
                never_eligible_instruments=sorted(set(FIXED_COHORT) - qualified),
                no_ranking_or_holding_dependency=sorted(set(FIXED_COHORT) - required))


def generate_cohort_targets(dataset, variant="E0", execution_delay=1):
    """Generate fixed D/D+1/D+2 monthly targets for the main account engine."""
    if variant not in ("E0", "R0", "E1", "R1"):
        raise ValueError("Unregistered cohort variant")
    if type(execution_delay) is not int or execution_delay not in (1, 2):
        raise ValueError("Only base and one additional execution session are registered")
    dependencies = cohort_dependencies(dataset)
    calendar, decisions = list(dataset.calendar), []
    positions = {day: i for i, day in enumerate(calendar)}
    columns = ["date", "instrument_id", "close", "amount", "available_at", "total_return_index"]
    if "total_return_available_at" in dataset.bars:
        columns.append("total_return_available_at")
    bars, benchmark = _prepare(dataset.bars[columns]), _prepare(dataset.benchmark)
    for entry in dependencies["schedule"]:
        day, release = entry["anchor_date"], entry["release_date"]
        index, release_index = positions[day], positions[release]
        if release_index + execution_delay >= len(calendar):
            continue
        execution, at = calendar[release_index + execution_delay], _cutoff(release)
        known = _snapshot(bars, at, ["date", "instrument_id"])
        current = known.loc[known.date.eq(release)].set_index("instrument_id")
        refs = {sid: float(v) for sid, v in current.close.items() if pd.notna(v) and np.isfinite(v) and v > 0}
        order_window = known.loc[known.date.isin(calendar[release_index - 19:release_index + 1])]
        adv = {}
        for sid, rows in order_window.groupby("instrument_id"):
            amounts = pd.to_numeric(rows.amount, errors="coerce")
            if len(amounts) == 20 and (np.isfinite(amounts) & amounts.ge(0)).all() and amounts.mean() > 0:
                adv[sid] = float(amounts.mean())
        diagnostics = dict(entry, universe=COHORT_SCOPE, variant=variant, signal_anchor_date=day,
                           signal_anchor_at=_cutoff(day).isoformat(), signal_release_delay=1,
                           order_reference_date=release, risk_scaling=False, momentum={}, trend=None)
        eligible, weights, status = entry["eligible"], {}, entry["status"]
        if status != "CASH_COHORT_NOT_YET_KNOWN":
            # Shared signal inputs are verified across all four controls before
            # producing any one control, so one missing competitor cannot be
            # silently excluded from ranking or converted to a cash signal.
            history = known.loc[known.date.le(day)].copy()
            if "total_return_available_at" in history:
                clocks = pd.to_datetime(history.total_return_available_at, utc=True, format="mixed", errors="coerce")
                history.loc[clocks.isna() | clocks.gt(at), "total_return_index"] = np.nan
            tr = history.pivot(index="date", columns="instrument_id", values="total_return_index")
            momentum = {}
            for sid in (eligible if len(eligible) >= 3 else []):
                for feature_day in (calendar[index - 126], calendar[index - 21]):
                    if feature_day not in tr.index or sid not in tr or not np.isfinite(tr.at[feature_day, sid]) or tr.at[feature_day, sid] <= 0:
                        _blocked(day, sid, "missing as-of momentum TR " + feature_day)
                momentum[sid] = float(np.log(tr.at[calendar[index - 21], sid] / tr.at[calendar[index - 126], sid]))
                if sid not in refs or sid not in adv:
                    _blocked(release, sid, "missing release-day order price/ADV20")
            market = _snapshot(benchmark, at, ["date"]).set_index("date")
            trend_window = market.total_return_index.reindex(calendar[max(0, index - 199):index + 1])
            if len(trend_window) != 200 or not (np.isfinite(trend_window) & trend_window.gt(0)).all():
                _blocked(day, "HS300_TR", "missing 200-session benchmark window")
            trend = bool(trend_window.iloc[-1] > trend_window.mean())
            ordered = sorted(momentum, key=lambda sid: (-momentum[sid], sid))
            diagnostics.update(momentum=momentum, trend=trend, momentum_order=ordered,
                               ranking_freedom=len(eligible) >= 4)
            status = "CASH_INSUFFICIENT_PRODUCTS" if len(eligible) < 3 else "OK"
            if len(eligible) >= 3:
                chosen = ordered[:3] if variant in ("R0", "R1") else eligible
                weights = {sid: min(.35, 1 / len(chosen)) for sid in sorted(chosen)}
                if variant in ("E1", "R1") and not trend:
                    status, weights = "CASH_TREND_OFF", {}
        diagnostics["target_gross_weight"] = sum(weights.values())
        # These are execution priorities, not factor ranks. Equal vectors have
        # identical order priorities even when momentum ordering differs.
        ranks = {sid: rank for rank, sid in enumerate(sorted(weights), 1)}
        decisions.append(TargetDecision(release, execution, at, weights, refs, adv, ranks, status, diagnostics))
    return decisions


def cohort_opportunities(dataset):
    """Pre-account diagnostics: no simulated or forward portfolio returns."""
    targets = {variant: generate_cohort_targets(dataset, variant) for variant in ("E0", "R0", "E1", "R1")}
    start = dataset.manifest.get("funded_account_start", "2016-01-01")
    rows = []
    for index, target in enumerate(targets["E0"]):
        if target.execution_date < start:
            continue
        rows.append(dict(anchor_date=target.diagnostics["signal_anchor_date"],
                         execution_date=target.execution_date,
                         status=target.status,
                         eligible_count=target.diagnostics["eligible_count"],
                         eligible=target.diagnostics["eligible"], trend=target.diagnostics["trend"],
                         targets={v: ds[index].weights for v, ds in targets.items()},
                         ranking_targets_differ=target.weights != targets["R0"][index].weights))
    return dict(research_scope=COHORT_SCOPE, performance_evidence=False, schedule=rows,
                funded_account_start=start, scheduled_count=len(rows),
                legal_anchor_count=sum(row["eligible_count"] is not None for row in rows),
                preactivation_cash_count=sum(row["eligible_count"] is None for row in rows),
                n_ge4=sum(row["eligible_count"] is not None and row["eligible_count"] >= 4 for row in rows),
                trend_on=sum(row["trend"] is True for row in rows),
                ranking_targets_differ=sum(row["ranking_targets_differ"] for row in rows))
