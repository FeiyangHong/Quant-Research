"""Versioned offline data with explicit point-in-time and evidence gates.

The generated fixture is invented; neither its calendar nor its returns are
market evidence. JSON snapshots are immutable and content checked on load.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCHEMA_VERSION = "r1-offline-1.1"
TIMEZONE = "Asia/Shanghai"
TABLES = ("instruments", "bars", "actions", "benchmark")
MODES = {"historical_public_asof", "historical_vendor_asof", "live_capture"}
REQUIRED = {
    "instruments": ["instrument_id", "asset_type", "board", "listed_on", "delisted_on",
                    "available_at", "account_verified", "benchmark_id", "industry", "lot_size",
                    "tick_size", "t_plus", "revision_id", "supersedes_id", "strategy_universe"],
    "bars": ["date", "instrument_id", "open", "high", "low", "close", "volume", "amount",
             "upper_limit", "lower_limit", "suspended", "available_at", "revision_id",
             "supersedes_id", "total_return_index"],
    "actions": ["action_id", "instrument_id", "action_type", "announcement_date", "ex_date",
                "record_date", "pay_date", "cash_per_share", "share_factor", "recovery_per_share",
                "available_at", "revision_id", "supersedes_id"],
    "benchmark": ["date", "total_return_index", "available_at", "revision_id", "supersedes_id"],
}
KEYS = {"instruments": ["instrument_id"], "bars": ["instrument_id", "date"],
        "actions": ["action_id"], "benchmark": ["date"]}
EVIDENCE_GATES = ("source", "license", "calendar", "historical_coverage", "point_in_time",
                  "lifecycle", "corporate_actions", "total_return", "historical_rules",
                  "historical_fees", "account_permissions", "dual_source_reconciliation")
PROVENANCE_COLUMNS = ["published_at", "publication_precision", "vendor_first_seen_at",
                      "ingested_at", "processed_at", "availability_mode", "source", "endpoint",
                      "source_record_id", "raw_object_hash", "license_profile_id", "quality_status"]


class DataValidationError(ValueError):
    """A data snapshot violates the schema or lacks mandatory evidence."""


@dataclass
class Dataset:
    calendar: list[str]
    instruments: pd.DataFrame
    bars: pd.DataFrame
    actions: pd.DataFrame
    benchmark: pd.DataFrame
    manifest: dict[str, Any]


def _aware(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise DataValidationError(f"Timezone-aware timestamp required: {value!r}")
    return stamp.tz_convert(TIMEZONE)


def decision_cutoff(day: str) -> pd.Timestamp:
    return pd.Timestamp(day, tz=TIMEZONE).normalize() + pd.Timedelta(hours=21)


def date_only_available_at(publication_date: str, calendar: Iterable[str], extra_delay: int = 0) -> str:
    """Date-only D becomes usable at 21:00 on first session strictly after D.

    extra_delay=1 is the prescribed additional-session stress. Execution must
    still occur on a session after this decision cutoff.
    """
    if not isinstance(extra_delay, int) or extra_delay < 0:
        raise ValueError("extra_delay must be a nonnegative integer")
    date.fromisoformat(publication_date)
    sessions = sorted(set(calendar))
    future = [day for day in sessions if day > publication_date]
    if len(future) <= extra_delay:
        raise DataValidationError("Calendar does not cover the availability delay")
    return decision_cutoff(future[extra_delay]).isoformat()


def asof_records(frame: pd.DataFrame, cutoff: Any, keys: list[str]) -> pd.DataFrame:
    """Select the latest visible revision, never a future revision.

    Equal availability timestamps for one economic key are ambiguous and are
    rejected instead of selecting by arbitrary row/revision order.
    """
    stamp = _aware(cutoff)
    if frame.empty:
        return frame.copy()
    if "available_at" not in frame or any(key not in frame for key in keys):
        raise DataValidationError("Missing point-in-time key or availability column")
    if not frame["available_at"].astype(str).str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
        raise DataValidationError("available_at must have an explicit timezone")
    visible = frame.copy()
    visible["_available"] = pd.to_datetime(visible["available_at"], utc=True, format="mixed", errors="raise")
    visible = visible.loc[visible["_available"] <= stamp.tz_convert("UTC")]
    if visible.duplicated(keys + ["_available"]).any():
        raise DataValidationError("Ambiguous revisions at equal available_at")
    return visible.sort_values("_available", kind="stable").drop_duplicates(keys, keep="last").drop(columns="_available")


def master_asof(dataset: Dataset, cutoff: Any) -> pd.DataFrame:
    """Historical knowledge of identities; does not silently remove dead assets."""
    return asof_records(dataset.instruments, cutoff, ["instrument_id"])


def bars_asof(dataset: Dataset, cutoff: Any) -> pd.DataFrame:
    stamp = _aware(cutoff)
    result = asof_records(dataset.bars, stamp, ["instrument_id", "date"])
    return result.loc[result["date"] <= stamp.date().isoformat()]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="records")


def _date_errors(series: pd.Series, nullable: bool = False) -> int:
    def valid(value: Any) -> bool:
        if pd.isna(value):
            return nullable
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return int((~series.map(valid)).sum())


def audit_dataset(dataset: Dataset) -> dict[str, Any]:
    """Schema errors and research evidence blockers are separate dimensions.

    Evidence gate entries require status=VERIFIED, reviewer, reviewed_at and
    evidence references; this records an audit attestation, not an automatic
    verification of external source documents or of legal permissions.
    """
    errors: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    manifest = dataset.manifest
    synthetic = manifest.get("synthetic") is True
    if manifest.get("schema_version") not in ("r1-offline-1.0", SCHEMA_VERSION):
        errors.append("manifest: unsupported schema_version")
    if not isinstance(manifest.get("synthetic"), bool):
        errors.append("manifest: explicit boolean synthetic is required")
    if not manifest.get("dataset_id") or not manifest.get("dataset_version"):
        errors.append("manifest: dataset_id and dataset_version required")
    if manifest.get("timezone") != TIMEZONE:
        errors.append("manifest: timezone must be Asia/Shanghai")
    if manifest.get("units") != {"volume": "shares_or_fund_units", "amount": "CNY", "price": "CNY"}:
        errors.append("manifest: explicit normalized units required")
    calendar = dataset.calendar
    if not calendar or calendar != sorted(set(calendar)) or _date_errors(pd.Series(calendar)):
        errors.append("calendar: sorted unique ISO dates required")
    valid_tables: dict[str, pd.DataFrame] = {}
    for name in TABLES:
        frame = getattr(dataset, name)
        missing = sorted(set(REQUIRED[name]) - set(frame.columns))
        if missing:
            errors.append(f"{name}: missing columns {missing}")
            continue
        valid_tables[name] = frame
        keys = KEYS[name]
        if frame[keys + ["revision_id", "available_at"]].isna().any().any():
            errors.append(f"{name}: null primary key, revision or availability")
        if frame.duplicated(keys + ["revision_id"]).any():
            errors.append(f"{name}: duplicate versioned primary key")
        if frame.duplicated(keys + ["available_at"]).any():
            errors.append(f"{name}: ambiguous equal-time revisions")
        try:
            if not frame["available_at"].astype(str).str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
                raise ValueError("naive timestamp")
            times = pd.to_datetime(frame["available_at"], utc=True, format="mixed", errors="raise")
            if times.isna().any():
                raise ValueError("missing timestamp")
        except (ValueError, TypeError):
            errors.append(f"{name}: invalid or timezone-naive available_at")
            times = None
        if times is not None and not frame.empty:
            revisions = {tuple(row[key] for key in keys) + (row["revision_id"],): (idx, row)
                         for idx, row in frame.iterrows()}
            for idx, row in frame.loc[frame["supersedes_id"].notna()].iterrows():
                prior = revisions.get(tuple(row[key] for key in keys) + (row["supersedes_id"],))
                if prior is None or times.loc[prior[0]] >= times.loc[idx]:
                    errors.append(f"{name}: invalid revision lineage for {row['revision_id']}")
            for _, group in frame.groupby(keys, dropna=False):
                if len(group) > 1 and group["supersedes_id"].isna().sum() != 1:
                    errors.append(f"{name}: revision chain needs one original per economic key")
                    break
        for column in ("date", "listed_on", "announcement_date", "ex_date", "record_date"):
            if column in frame and _date_errors(frame[column]):
                errors.append(f"{name}.{column}: invalid ISO date")
        for column in ("delisted_on", "pay_date"):
            if column in frame and _date_errors(frame[column], nullable=True):
                errors.append(f"{name}.{column}: invalid nullable ISO date")
        if "date" in frame:
            if not frame["date"].isin(calendar).all():
                errors.append(f"{name}: observed dates absent from calendar")
            if times is not None and not frame.empty:
                minimum = pd.to_datetime(frame["date"] + "T15:00:00+08:00", utc=True, errors="coerce")
                if (times < minimum).any():
                    errors.append(f"{name}: daily final observations available before session close")
        if not synthetic:
            missing_provenance = sorted(set(PROVENANCE_COLUMNS) - set(frame.columns))
            if missing_provenance:
                blockers.append(f"{name}: missing real-data provenance columns {missing_provenance}")
            elif not frame.empty:
                if not frame["quality_status"].eq("accepted").all():
                    blockers.append(f"{name}: non-accepted records present")
                if not frame["availability_mode"].isin(MODES).all():
                    blockers.append(f"{name}: unsupported availability mode")
                if not frame["publication_precision"].isin(["second", "minute", "date_only"]).all():
                    blockers.append(f"{name}: unknown publication precision")
                for _, row in frame.iterrows():
                    try:
                        available = _aware(row["available_at"])
                        ingested = _aware(row["ingested_at"])
                        processed = _aware(row["processed_at"])
                        if processed < ingested:
                            raise ValueError("processed before ingestion")
                        if row["publication_precision"] == "date_only":
                            minimum = _aware(date_only_available_at(str(row["published_at"])[:10], calendar))
                        else:
                            minimum = _aware(row["published_at"])
                        mode = row["availability_mode"]
                        if mode == "historical_vendor_asof":
                            minimum = max(minimum, _aware(row["vendor_first_seen_at"]))
                        elif mode == "live_capture":
                            minimum = max(minimum, ingested, processed)
                        if available < minimum:
                            raise ValueError("available before evidence lower bound")
                        for column in ["source", "endpoint", "source_record_id", "raw_object_hash", "license_profile_id"]:
                            if pd.isna(row[column]) or not str(row[column]).strip():
                                raise ValueError("empty provenance")
                        if not re.fullmatch(r"[a-f0-9]{64}", str(row["raw_object_hash"])):
                            raise ValueError("invalid raw object hash")
                    except (ValueError, TypeError):
                        blockers.append(f"{name}: invalid real-data provenance/availability lower bound")
                        break
    instruments = valid_tables.get("instruments")
    bars = valid_tables.get("bars")
    actions = valid_tables.get("actions")
    benchmark = valid_tables.get("benchmark")
    if instruments is not None:
        if instruments.empty:
            errors.append("instruments: empty master")
        if not instruments["asset_type"].isin(["ETF", "STOCK"]).all() or not instruments["board"].isin(["MAIN", "CHINEXT", "STAR", "BSE", "ETF"]).all():
            errors.append("instruments: unknown asset_type or board")
        if not instruments["account_verified"].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            errors.append("instruments: account_verified requires boolean")
        for column in ["lot_size", "tick_size", "t_plus"]:
            values = pd.to_numeric(instruments[column], errors="coerce")
            if not np.isfinite(values).all() or (values < 0).any() or (column != "t_plus" and (values == 0).any()):
                errors.append(f"instruments: invalid {column}")
        if ((instruments["delisted_on"].notna()) & (instruments["delisted_on"] < instruments["listed_on"])).any():
            errors.append("instruments: delisted before listing")
        identities = set(instruments["instrument_id"])
        for name, frame in (("bars", bars), ("actions", actions)):
            if frame is not None and not frame["instrument_id"].isin(identities).all():
                errors.append(f"{name}: unknown instrument identity")
    if bars is not None:
        if bars.empty:
            errors.append("bars: empty market observations")
        numeric = bars[["open", "high", "low", "close", "volume", "amount", "upper_limit", "lower_limit", "total_return_index"]].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(numeric.to_numpy()).all():
            errors.append("bars: nonfinite required numerical observation")
        if (numeric[["open", "high", "low", "close", "total_return_index"]] <= 0).any().any() or (numeric[["volume", "amount", "lower_limit"]] < 0).any().any():
            errors.append("bars: invalid price/quantity sign")
        if ((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)) | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))).any():
            errors.append("bars: inconsistent OHLC")
        if ((numeric["upper_limit"] < numeric["high"]) | (numeric["lower_limit"] > numeric["low"])).any():
            errors.append("bars: observed price outside supplied limits")
        if not bars["suspended"].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            errors.append("bars: suspended requires boolean")
        elif (bars["suspended"] & ((numeric["volume"] != 0) | (numeric["amount"] != 0))).any():
            errors.append("bars: suspended row has nonzero turnover")
    if benchmark is not None:
        value = pd.to_numeric(benchmark["total_return_index"], errors="coerce")
        if benchmark.empty or not np.isfinite(value).all() or (value <= 0).any():
            errors.append("benchmark: finite positive total return series required")
    if actions is not None:
        if not actions["action_type"].isin(["CASH_DIVIDEND", "SPLIT", "DELISTING", "LIQUIDATION", "LIQUIDATION_PAYMENT"]).all():
            errors.append("actions: unsupported event type")
        extended = actions["action_type"].isin(["LIQUIDATION", "LIQUIDATION_PAYMENT"])
        if extended.any() and manifest.get("schema_version") == "r1-offline-1.0":
            errors.append("actions: liquidation events require schema r1-offline-1.1")
        for column in ("cash_per_share", "share_factor"):
            value = pd.to_numeric(actions[column], errors="coerce")
            if not np.isfinite(value).all() or (value < 0).any() or (column == "share_factor" and (value == 0).any()):
                errors.append(f"actions: invalid {column}")
        recovery = pd.to_numeric(actions["recovery_per_share"], errors="coerce")
        if (recovery.dropna() < 0).any() or np.isinf(recovery.dropna()).any():
            errors.append("actions: invalid recovery_per_share")
        if ((actions["announcement_date"] > actions["ex_date"]) | (actions["record_date"] > actions["ex_date"])).any():
            errors.append("actions: invalid announcement/record/ex chronology")
        for _, action in actions.iterrows():
            kind = action["action_type"]
            if kind == "CASH_DIVIDEND" and not synthetic:
                cash_verified = action.get("cash_settlement_verified")
                if not isinstance(cash_verified, (bool, np.bool_)) or not cash_verified:
                    blockers.append("dividend: actual account cash settlement unverified")
            late = action.get("settlement_mode") == "LATE_RECOGNITION"
            assumed = action.get("settlement_mode") == "ASSUMED_SCHEDULED_CREDIT"
            if kind in ("LIQUIDATION", "LIQUIDATION_PAYMENT"):
                verified = action.get("terms_verified")
                if not isinstance(verified, (bool, np.bool_)) or not verified or not isinstance(action.get("source_url"), str) or not action["source_url"].strip():
                    errors.append("actions: liquidation requires verified terms and source URL")
            if pd.notna(action["pay_date"]) and action["pay_date"] < action["ex_date"]:
                if kind != "LIQUIDATION_PAYMENT" or not late:
                    errors.append("actions: payment before entitlement")
            if kind == "LIQUIDATION" and action["record_date"] >= action["ex_date"]:
                errors.append("actions: liquidation record date must precede recognition")
            if kind == "LIQUIDATION_PAYMENT":
                if action.get("recognition_date") != action["ex_date"]:
                    errors.append("actions: liquidation recognition_date must equal ex_date")
                if late and (pd.isna(action["pay_date"]) or action["pay_date"] >= action["ex_date"]):
                    errors.append("actions: late recognition requires earlier actual pay date")
                ref = action.get("entitlement_action_id")
                parents = actions.loc[(actions["action_id"] == ref) & actions["action_type"].eq("LIQUIDATION")]
                if parents.empty or not parents["instrument_id"].eq(action["instrument_id"]).all():
                    errors.append("actions: invalid liquidation entitlement reference")
                if not isinstance(action.get("is_final"), (bool, np.bool_)) or pd.isna(action["pay_date"]):
                    errors.append("actions: liquidation payment requires final flag and pay date")
                if not isinstance(action.get("installment_id"), str) or not action["installment_id"].strip():
                    errors.append("actions: liquidation payment requires installment_id")
                if action.get("settlement_mode", "SCHEDULED") not in ("SCHEDULED", "LATE_RECOGNITION", "ASSUMED_SCHEDULED_CREDIT"):
                    errors.append("actions: unknown liquidation settlement mode")
                cash_verified = action.get("cash_settlement_verified")
                if not assumed and (not isinstance(cash_verified, (bool, np.bool_)) or not cash_verified):
                    errors.append("actions: actual liquidation cash availability requires verification")
                if assumed:
                    warnings.append("liquidation: scheduled credit assumption is not verified account cash availability")
                    if not synthetic:
                        blockers.append("liquidation: actual account cash settlement unverified")
                if late:
                    warnings.append("liquidation: late observation is not the actual historical cash availability")
                    if not synthetic:
                        blockers.append("liquidation: unresolved historical payment information timing")
        payments = actions.loc[actions["action_type"].eq("LIQUIDATION_PAYMENT")]
        if not payments.empty and {"entitlement_action_id", "installment_id"}.issubset(payments.columns):
            if payments.duplicated(["entitlement_action_id", "installment_id", "revision_id"]).any():
                errors.append("actions: duplicate liquidation installment")
    coverage: dict[str, Any] = {"calendar_sessions": len(calendar), "tables": {name: len(getattr(dataset, name)) for name in TABLES}}
    if bars is not None:
        unique_bars = bars.drop_duplicates(["instrument_id", "date"])
        coverage["observations_by_month"] = unique_bars.groupby(unique_bars["date"].str[:7]).size().to_dict()
        coverage["observations_by_instrument"] = unique_bars.groupby("instrument_id").size().to_dict()
        coverage["suspended_observations"] = int(unique_bars["suspended"].eq(True).sum())
        coverage["missing_sessions_by_instrument"] = {}
        if instruments is not None and not any("invalid" in error or "timezone" in error for error in errors):
            latest = instruments.sort_values("available_at").drop_duplicates("instrument_id", keep="last")
            for _, row in latest.iterrows():
                expected = {day for day in calendar if day >= row["listed_on"] and (pd.isna(row["delisted_on"]) or day < row["delisted_on"])}
                observed = set(unique_bars.loc[unique_bars["instrument_id"] == row["instrument_id"], "date"])
                missing_count = len(expected - observed)
                coverage["missing_sessions_by_instrument"][row["instrument_id"]] = missing_count
                if missing_count:
                    blockers.append(f"coverage: {row['instrument_id']} missing {missing_count} listed sessions")
                if observed - expected:
                    errors.append(f"bars: {row['instrument_id']} observations outside listing interval")
            coverage["observations_by_board"] = unique_bars.merge(latest[["instrument_id", "board"]], on="instrument_id").groupby("board").size().to_dict()
    if benchmark is not None and set(calendar) - set(benchmark["date"]):
        blockers.append("coverage: benchmark has missing calendar sessions")
    if synthetic:
        warnings.append("SYNTHETIC_ONLY: invented prices, calendar, rules and permissions; never performance evidence")
    else:
        if manifest.get("availability_mode") not in MODES:
            blockers.append("manifest: valid real-data availability_mode required")
        for gate in EVIDENCE_GATES:
            item = manifest.get("evidence_gates", {}).get(gate, {})
            if not isinstance(item, dict) or item.get("status") != "VERIFIED" or not item.get("reviewer") or not item.get("reviewed_at") or not item.get("evidence"):
                blockers.append(f"evidence: {gate} unverified")
            else:
                try:
                    _aware(item["reviewed_at"])
                except (ValueError, TypeError):
                    blockers.append(f"evidence: {gate} invalid review timestamp")
        if manifest.get("calendar_kind") != "VERIFIED_EXCHANGE_CALENDAR":
            blockers.append("calendar: not verified exchange calendar")
        if not manifest.get("license_profile_id") or not manifest.get("source_snapshot_hashes"):
            blockers.append("manifest: license profile and original snapshot hashes required")
    return {"status": "BLOCKED_DATA" if errors or blockers else ("SYNTHETIC_ONLY" if synthetic else "PASSED"),
            "errors": list(dict.fromkeys(errors)), "blockers": list(dict.fromkeys(blockers)),
            "warnings": warnings, "performance_evidence": not synthetic and not errors and not blockers,
            "coverage": coverage, "schema_version": SCHEMA_VERSION}


def save_dataset(dataset: Dataset, path: str | Path) -> dict[str, Any]:
    """Persist a new immutable snapshot; identical repeats are idempotent."""
    audit = audit_dataset(dataset)
    if audit["errors"]:
        raise DataValidationError("; ".join(audit["errors"]))
    objects = {"calendar.json": dataset.calendar}
    objects.update({name + ".json": {"columns": list(getattr(dataset, name).columns), "records": _records(getattr(dataset, name))} for name in TABLES})
    payloads = {name: _canonical(value) for name, value in objects.items()}
    manifest = dict(dataset.manifest)
    manifest["file_sha256"] = {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}
    payloads["manifest.json"] = _canonical(manifest)
    destination = Path(path)
    if destination.exists() and any(destination.iterdir()):
        if all((destination / name).is_file() and (destination / name).read_bytes() == payload for name, payload in payloads.items()):
            return manifest
        raise FileExistsError("Snapshot already exists with different content; choose a new dataset version/path")
    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        with (destination / name).open("xb") as stream:
            stream.write(payload)
    return manifest


def load_dataset(path: str | Path, *, allow_unverified: bool = False) -> Dataset:
    """Verify snapshot hashes and schema; real unverified snapshots fail closed.

    allow_unverified is for auditing/quarantine only, never research admission.
    """
    source = Path(path)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    objects = {}
    for name in ["calendar.json"] + [table + ".json" for table in TABLES]:
        payload = (source / name).read_bytes()
        if manifest.get("file_sha256", {}).get(name) != hashlib.sha256(payload).hexdigest():
            raise DataValidationError(f"Hash mismatch or missing digest: {name}")
        objects[name] = json.loads(payload)
    frames = {name: pd.DataFrame(objects[name + ".json"]["records"], columns=objects[name + ".json"]["columns"]) for name in TABLES}
    dataset = Dataset(calendar=objects["calendar.json"], manifest=manifest, **frames)
    audit = audit_dataset(dataset)
    if audit["errors"] or (audit["blockers"] and not allow_unverified):
        raise DataValidationError("; ".join(audit["errors"] + audit["blockers"]))
    return dataset


def synthetic_dataset(seed: int = 20261114) -> Dataset:
    """Seven invented weekday years, six funds, dividend/split/delisting cases."""
    calendar = pd.bdate_range("2018-01-01", "2024-12-31").strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(seed)
    categories = ["300", "500", "1000", "CHINEXT", "STAR", "300_EXIT"]
    instruments, bars, actions = [], [], []
    dividend_day, dividend_pay = "2021-06-15", "2021-06-18"
    split_day, exit_day = "2022-06-15", "2022-10-17"
    market_returns = rng.normal(0.00015, 0.009, len(calendar))
    benchmark_levels = 1000 * np.cumprod(1 + market_returns)
    for number, category in enumerate(categories):
        identity = "SYN_ETF_" + category
        instrument = {"instrument_id": identity, "asset_type": "ETF", "board": "ETF", "listed_on": calendar[0],
                      "delisted_on": None, "available_at": "2017-12-29T21:00:00+08:00", "account_verified": True,
                      "benchmark_id": "CSI300" if category in ["300", "300_EXIT"] else ("CSI" + category if category in ["500", "1000"] else category),
                      "industry": "BROAD_MARKET", "lot_size": 100, "tick_size": 0.001, "t_plus": 1,
                      "revision_id": identity + "_master_v1", "supersedes_id": None, "strategy_universe": "R1B"}
        instruments.append(instrument)
        if category == "300_EXIT":
            instruments.append(dict(instrument, delisted_on=exit_day, available_at="2022-10-12T18:00:00+08:00",
                                    revision_id=identity + "_master_v2", supersedes_id=identity + "_master_v1"))
        asset_returns = 0.7 * market_returns + rng.normal(0.00005, 0.006 + number * 0.0003, len(calendar))
        prior_close, total_return = 2.0 + number * 0.5, 100.0
        for index, day in enumerate(calendar):
            if category == "300_EXIT" and day >= exit_day:
                break
            cash = 0.03 if category == "300" and day == dividend_day else 0.0
            factor = 2.0 if category == "500" and day == split_day else 1.0
            reference = (prior_close - cash) / factor
            close = round(reference * (1 + asset_returns[index]), 3)
            opening = round(reference * (1 + rng.normal(0, 0.002)), 3)
            high = round(max(opening, close) * 1.003, 3)
            low = round(min(opening, close) * 0.997, 3)
            volume = int(rng.integers(25_000_000, 60_000_000))
            # Exit product dominates its category before it disappears, so the
            # fixture exercises actual inherited holdings rather than unused rows.
            if category == "300_EXIT":
                volume *= 2
            total_return *= (close * factor + cash) / prior_close
            bars.append({"date": day, "instrument_id": identity, "open": opening, "high": high, "low": low,
                         "close": close, "volume": volume, "amount": round(volume * (opening + close) / 2, 2),
                         "upper_limit": round(reference * 1.1, 3), "lower_limit": round(reference * 0.9, 3),
                         "suspended": False, "available_at": day + "T16:00:00+08:00", "revision_id": identity + "_" + day + "_v1",
                         "supersedes_id": None, "total_return_index": total_return})
            prior_close = close
    for category, kind, exday, pay, cash, factor, recovery in [
        ("300", "CASH_DIVIDEND", dividend_day, dividend_pay, 0.03, 1.0, None),
        ("500", "SPLIT", split_day, split_day, 0.0, 2.0, None),
        ("300_EXIT", "DELISTING", exit_day, None, 0.0, 1.0, None),
    ]:
        event_index = calendar.index(exday)
        announcement, record = calendar[event_index - 3], calendar[event_index - 1]
        action_id = "SYN_" + kind
        actions.append({"action_id": action_id, "instrument_id": "SYN_ETF_" + category, "action_type": kind,
                        "announcement_date": announcement, "ex_date": exday, "record_date": record, "pay_date": pay,
                        "cash_per_share": cash, "share_factor": factor, "recovery_per_share": recovery,
                        "available_at": announcement + "T18:00:00+08:00", "revision_id": action_id + "_v1", "supersedes_id": None})
    benchmark = [{"date": day, "total_return_index": float(level), "available_at": day + "T16:00:00+08:00",
                  "revision_id": "SYN_CSI300_" + day + "_v1", "supersedes_id": None} for day, level in zip(calendar, benchmark_levels)]
    manifest = {"dataset_id": "synthetic-r1-fixture", "dataset_version": "1.0", "schema_version": SCHEMA_VERSION,
                "synthetic": True, "seed": seed, "timezone": TIMEZONE, "availability_mode": "SYNTHETIC_FIXTURE",
                "calendar_kind": "SYNTHETIC_WEEKDAY_CALENDAR", "source": "numpy.random.default_rng; invented data",
                "license_profile_id": "PROJECT_GENERATED_FIXTURE_ONLY", "units": {"volume": "shares_or_fund_units", "amount": "CNY", "price": "CNY"},
                "date_only_policy": "First session strictly after D at 21:00 Asia/Shanghai; execution next session",
                "performance_evidence": False, "historical_permissions_evidence": False,
                "warning": "NOT REAL MARKET DATA. Product identities, calendar, rules, permissions and returns are invented. Never performance evidence.",
                "coverage_start": calendar[0], "coverage_end": calendar[-1], "benchmark_definition": "Invented CSI300-like total return series"}
    return Dataset(calendar, pd.DataFrame(instruments), pd.DataFrame(bars), pd.DataFrame(actions, columns=REQUIRED["actions"]), pd.DataFrame(benchmark), manifest)
