"""Shared publication/effective clocks for instrument state.

Intervals are [effective_from, effective_to), in Asia/Shanghai dates. Missing
bounds are unbounded. A later state does not resurrect its predecessor when
it expires. Publications amend knowledge; they never advance effective time.
"""
from datetime import date
import pandas as pd


class TemporalStateError(ValueError):
    pass


def _bound(value):
    if value is None or pd.isna(value) or value == "":
        return None
    if not isinstance(value, str):
        raise TemporalStateError("Effective bounds require ISO dates")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise TemporalStateError("Effective bounds require ISO dates") from None
    return value


def _revision_kind(value):
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    if not isinstance(value, str) or value not in ("CORRECTION", "TRANSITION"):
        raise TemporalStateError("Unknown explicit master revision_kind")
    return value


def master_record(rows, cutoff):
    stamp = pd.Timestamp(cutoff)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise TemporalStateError("Timezone-aware cutoff required")
    day = stamp.tz_convert("Asia/Shanghai").date().isoformat()
    known = []
    for row in rows:
        available = pd.Timestamp(row.get("_available", row.get("available_at")))
        if pd.isna(available) or available.tzinfo is None:
            raise TemporalStateError("Timezone-aware available_at required")
        if available > stamp:
            continue
        _revision_kind(row.get("revision_kind"))
        start, end = _bound(row.get("effective_from")), _bound(row.get("effective_to"))
        if start is not None and end is not None and end <= start:
            raise TemporalStateError("Empty or reversed effective interval")
        known.append((row, available, start, end))
    # supersedes_id links both historical corrections and lifecycle states.
    # Effective starts distinguish transitions; revision_kind=CORRECTION
    # explicitly identifies a correction that moves its start forward.
    identities = {}
    for item in known:
        revision = item[0].get("revision_id")
        if isinstance(revision, str) and revision:
            if revision in identities:
                raise TemporalStateError("Duplicate master revision identity")
            identities[revision] = item
    superseded, successors = set(), set()
    seen_states = set()
    for row, available, start, end in known:
        if (start, available) in seen_states:
            raise TemporalStateError("Ambiguous master revisions at equal available_at")
        seen_states.add((start, available))
        previous = row.get("supersedes_id")
        if previous is not None and pd.notna(previous) and previous != "":
            revision = row.get("revision_id")
            if (not isinstance(previous, str) or not previous.strip()
                    or not isinstance(revision, str) or not revision.strip()):
                raise TemporalStateError("Master lineage requires stable parent and child revision identities")
            if previous not in identities or identities[previous][1] >= available:
                raise TemporalStateError("Invalid or branching master correction chain")
            previous_start = identities[previous][2] or "0001-01-01"
            # Existing master files link future lifecycle transitions via
            # supersedes_id too. A later start replaces its predecessor only
            # when effective. Explicit corrections can move a start forward.
            kind = _revision_kind(row.get("revision_kind"))
            transition = (start or "0001-01-01") > previous_start and kind != "CORRECTION"
            if kind == "TRANSITION" and not transition:
                raise TemporalStateError("Explicit master transition requires a later effective start")
            branch = (previous, start if transition else "CORRECTION")
            if branch in successors:
                raise TemporalStateError("Invalid or branching master correction chain")
            if not transition or start <= day:
                superseded.add(previous)
            successors.add(branch)
    candidates = [item for item in known if item[0].get("revision_id") not in superseded
                  and (item[2] is None or item[2] <= day)]
    if not candidates:
        return None
    # Effective state order first; publication order resolves amendments of
    # that state. End filtering AFTER selection prevents expired-state fallback.
    candidates.sort(key=lambda item: (item[2] or "0001-01-01", item[1]))
    chosen = candidates[-1]
    if sum((item[2], item[1]) == (chosen[2], chosen[1]) for item in candidates) != 1:
        raise TemporalStateError("Ambiguous master revisions at equal available_at")
    return chosen[0] if chosen[3] is None or day < chosen[3] else None


def master_snapshot(frame, cutoff):
    if frame.empty:
        return frame.copy()
    if not {"instrument_id", "available_at"}.issubset(frame.columns):
        raise TemporalStateError("Missing master identity or available_at")
    selected = []
    for _, group in frame.groupby("instrument_id", sort=False):
        row = master_record(group.to_dict("records"), cutoff)
        if row is not None:
            selected.append(row)
    return pd.DataFrame(selected, columns=frame.columns)


def representative_record(rows, cutoff):
    """Select economic state first, then require its benchmark evidence.

    A pending index source never resurrects an older state. Account execution
    uses master_record directly because benchmark knowledge is a research gate.
    """
    row = master_record(rows, cutoff)
    if row is None:
        return None
    source = row.get("benchmark_source_available_at")
    if source is None or pd.isna(source) or source == "":
        source = row.get("available_at")
    stamp = pd.Timestamp(source)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise TemporalStateError("Timezone-aware benchmark source availability required")
    return row if stamp <= pd.Timestamp(cutoff) else None


def representative_snapshot(frame, cutoff):
    if frame.empty:
        return frame.copy()
    if not {"instrument_id", "available_at"}.issubset(frame.columns):
        raise TemporalStateError("Missing master identity or available_at")
    rows = [representative_record(group.to_dict("records"), cutoff)
            for _, group in frame.groupby("instrument_id", sort=False)]
    return pd.DataFrame([row for row in rows if row is not None], columns=frame.columns)
