"""Document the full deterministic quarterly competition before returns exist."""
import numpy as np
import pandas as pd
from bisect import bisect_left


def required_tr_start(calendar, account_start="2016-01-01"):
    """Earliest common feature dependency for the first funded account day.

    The last prior session may generate the first target; 200 observations
    cover the longest registered feature. Earlier rows still enter turnover
    competition and listing-age calculations, but need no invented TR.
    """
    first = bisect_left(calendar, account_start)
    return calendar[max(0, first - 200)]


def representative_dependencies(dataset):
    """Independent amount-only reconstruction of the registered selector.

    No total-return, future survival, monthly age or data-availability ranking
    enters this calculation. Every selected identity requires full event data.
    """
    dates = list(dataset.calendar)
    master, bars = dataset.instruments.copy(), dataset.bars.copy()
    master["_known"] = pd.to_datetime(master.available_at, utc=True)
    bars["_known"] = pd.to_datetime(bars.available_at, utc=True)
    schedule, required = [], set()
    for index, day in enumerate(dates):
        current_quarter = pd.Timestamp(day).to_period("Q")
        if index and pd.Timestamp(dates[index - 1]).to_period("Q") == current_quarter:
            continue
        if index < 60:
            schedule.append({"quarter_start": day, "cutoff": dates[index - 1] if index else None,
                             "representatives": [], "reason": "INSUFFICIENT_60_SESSION_HISTORY"})
            continue
        previous = dates[index - 1]
        cutoff = pd.Timestamp(previous + "T21:00:00+08:00")
        m = master.loc[master._known <= cutoff].copy()
        for column, lower in (("effective_from", True), ("effective_to", False)):
            if column in m:
                values = m[column].fillna("").astype(str).str[:10]
                m = m.loc[values.eq("") | (values.le(previous) if lower else values.gt(previous))]
        m = m.sort_values("_known").drop_duplicates("instrument_id", keep="last")
        live = m.asset_type.eq("ETF") & m.account_verified.eq(True) & m.listed_on.le(previous)
        live &= m.delisted_on.isna() | m.delisted_on.eq("") | m.delisted_on.gt(previous)
        if "strategy_universe" in m:
            live &= m.strategy_universe.eq("R1B")
        else:
            live &= m.benchmark_id.isin(["CSI300", "CSI500", "CSI1000", "CHINEXT", "STAR", "BSE",
                                       "000300", "000905", "000852", "399006", "000688", "899050"])
        m = m.loc[live]
        h = bars.loc[(bars._known <= cutoff) & bars.date.le(previous)].sort_values("_known")
        h = h.drop_duplicates(["date", "instrument_id"], keep="last")
        window = h.loc[h.date.isin(dates[index - 60:index])].copy()
        amount = pd.to_numeric(window.amount, errors="coerce")
        window = window.loc[np.isfinite(amount) & amount.ge(0)]
        agg = window.groupby("instrument_id").amount.agg(["mean", "count"])
        normal = set(h.loc[h.date.eq(previous) & h.suspended.eq(False), "instrument_id"])
        m = m.merge(agg, left_on="instrument_id", right_index=True, how="left")
        m = m.loc[m["count"].eq(60) & m.instrument_id.isin(normal)
                  & m.benchmark_id.notna() & m.benchmark_id.ne("")]
        m = m.sort_values(["benchmark_id", "mean", "listed_on", "instrument_id"], ascending=[True, False, True, True])
        selected = m.drop_duplicates("benchmark_id").instrument_id.tolist()
        required.update(selected)
        schedule.append({"quarter_start": day, "cutoff": previous, "representatives": sorted(selected),
                         "candidate_count": len(m)})
    waivers = []
    for sid in sorted(required):
        # This proves a dependency is unreachable; it does not influence the
        # representative competition above. Never use return quality or future
        # survival to select a runner-up.
        listed = master.loc[master.instrument_id.eq(sid), "listed_on"].min()
        age = len(dates) - bisect_left(dates, listed)
        if age < 252:
            waivers.append({"instrument_id": sid, "reason": "NEVER_REACHES_252_LISTED_SESSIONS",
                            "listed_on": listed, "last_session": dates[-1], "listed_sessions": age,
                            "representative_selection_unchanged": True})
    waived = {row["instrument_id"] for row in waivers}
    return {"method": "REGISTERED_QUARTERLY_AMOUNT_ONLY", "depends_on_returns": False,
            "representative_union": sorted(required), "feature_dependency_waivers": waivers,
            "required_full_history_instruments": sorted(required - waived), "schedule": schedule}
