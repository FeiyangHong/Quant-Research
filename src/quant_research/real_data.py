"""Audit observed provider records without promoting them to tradable PIT data.

This staging audit intentionally has no method that sets Dataset evidence gates.
Coverage inside an observed interval is not proof of an instrument's lifespan.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from .providers.baostock import Query, normalize_history, validate_response


def _verified_object(root, name, expected):
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Evidence path escapes collection directory") from exc
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Evidence SHA256 required")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Evidence hash mismatch: " + name)
    return json.loads(content)


def audit_collection(directory):
    """Verify file lineage, holdout separation, observations and calendar gaps."""
    root = Path(directory).resolve()
    content = (root / "collection.json").read_bytes()
    collection = json.loads(content)
    if collection.get("schema_version") != "baostock-collection-1.0":
        raise ValueError("Unknown collection schema")
    if collection.get("synthetic") is not False or collection.get("history_end_cap") != "2024-12-31":
        raise ValueError("Real collection with locked 2025+ holdout required")
    errors, verified, seen = [], [], set()
    planned = set()
    plan_content = (root / "request_plan.json").read_bytes()
    plan_sha256 = hashlib.sha256(plan_content).hexdigest()
    if collection.get("request_plan_sha256", plan_sha256) != plan_sha256:
        errors.append("Request plan hash mismatch")
    for parameters in json.loads(plan_content)["queries"]:
        query = Query(**parameters)
        query.validate()
        key = (query.kind, query.code, query.start, query.end, query.date)
        if key in planned:
            errors.append("Duplicate query in request plan")
        planned.add(key)
    for item in collection["query_results"]:
        try:
            query = Query(**{k: item[k] for k in ("kind", "code", "start", "end", "date")})
            query.validate()
            key = (query.kind, query.code, query.start, query.end, query.date)
            if key in seen:
                raise ValueError("Duplicate query in collection")
            seen.add(key)
            manifest = _verified_object(root, item["manifest_path"], item["manifest_sha256"])
            if manifest["query"] != query.__dict__:
                raise ValueError("Collection/query manifest identity mismatch")
            for field in ("status", "raw_path", "raw_sha256", "row_count"):
                if item[field] != manifest[field]:
                    raise ValueError("Manifest summary mismatch: " + field)
            # All attempts, including timeouts and failed responses, remain auditable.
            for attempt in manifest["attempts"]:
                _verified_object(root, attempt["raw_path"], attempt["raw_sha256"])
            payload = _verified_object(root, item["raw_path"], item["raw_sha256"])
            if payload["query"] != query.__dict__ or payload["status"] != item["status"]:
                raise ValueError("Raw response identity/status mismatch")
            if len(payload.get("rows", [])) != item["row_count"]:
                raise ValueError("Raw row count mismatch")
            if item["status"] != "SUCCESS":
                errors.append(f"{query.kind}/{query.code or query.date}: {item['status']}")
                continue
            validate_response(query, payload)
            normalized = None
            if query.kind in {"history", "universe"}:
                normalized = _verified_object(root, item["normalized_path"], item["normalized_sha256"])
                if normalized != normalize_history(payload):
                    raise ValueError("Normalized observations disagree with raw response")
            verified.append((query, payload, normalized))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            errors.append(str(exc))
    if seen != planned:
        errors.append("Collection queries do not match request plan: missing or unplanned query")
    sessions = set()
    calendar_rows = 0
    for query, payload, _ in verified:
        if query.kind == "calendar":
            records = [dict(zip(payload["fields"], row)) for row in payload["rows"]]
            calendar_rows += len(records)
            for row in records:
                if row.get("is_trading_day") not in {"0", "1"}:
                    errors.append("Unknown calendar trading flag")
                if row.get("is_trading_day") == "1":
                    sessions.add(row["calendar_date"])
    if not sessions:
        errors.append("No verified trading calendar")
    histories, snapshots, masters = [], [], []
    for query, payload, normalized in verified:
        if query.kind == "master":
            masters.append({"code": query.code, "row_count": len(payload["rows"]),
                            "pit_eligible": False, "reason": "Current metadata or empty; not historical lifespan proof"})
        if query.kind == "universe":
            records = normalized["records"]
            snapshots.append({"date": query.date, "row_count": len(records),
                "audit_cohort_present": sorted(r["instrument_id"] for r in records if r["instrument_id"] in {
                    "sh.510300", "sh.510330", "sh.510500", "sh.512100", "sz.159915", "sh.588000", "sh.512320"}),
                "completeness": "OBSERVED_ONLY_NOT_AUTHORITATIVE_LIFETIME_UNIVERSE"})
        if query.kind != "history":
            continue
        records = normalized["records"]
        days = {row["date"] for row in records}
        first, last = (min(days), max(days)) if days else (None, None)
        internal = sorted(d for d in sessions if first and first <= d <= last and d not in days)
        non_sessions = sorted(days - sessions)
        issue_counts = Counter(issue for row in records for issue in row["normalization_issues"])
        ohlc_errors = []
        for row in records:
            if all(row[k] is not None for k in ("open", "high", "low", "close")):
                op, hi, lo, cl = (Decimal(row[k]) for k in ("open", "high", "low", "close"))
                if not (lo <= op <= hi and lo <= cl <= hi):
                    ohlc_errors.append(row["date"])
        zero_tradable = [r["date"] for r in records if r["zero_turnover"] and r["suspended"] is False]
        histories.append({"code": query.code, "row_count": len(records), "observed_first": first,
            "observed_last": last, "internal_missing_sessions": internal, "non_session_rows": non_sessions,
            "normalization_issue_counts": dict(issue_counts), "ohlc_error_dates": ohlc_errors,
            "observed_state_counts": dict(Counter(r["observation_state"] for r in records)),
            "zero_turnover_marked_tradable_dates": zero_tradable,
            "development_rows": sum(d < "2022-01-01" for d in days),
            "validation_rows": sum("2022-01-01" <= d <= "2024-12-31" for d in days),
            "tail_policy": "No rows created before/after observations; lifecycle evidence required"})
        if internal or non_sessions or ohlc_errors:
            errors.append(f"{query.code}: calendar/OHLC observation errors")
    blockers = [
        {"field": "historical_universe_and_benchmark_mapping", "status": "INCOMPLETE_COVERAGE",
         "impact": "Seven selected instruments and sparse snapshots cannot define the full R1B candidate pool or quarterly representatives."},
        {"field": "listed_on/delisted_on/suspended", "status": "NEEDS_OFFICIAL_RECONCILIATION",
         "impact": "Current/empty master and trade flags do not prove historical lifespan, suspension or liquidation rights."},
        {"field": "cash_dividend/split/liquidation", "status": "NEEDS_COMPLETE_EVENT_LEDGER",
         "impact": "Selected notices prove individual events; absence of an event needs complete interval evidence before total-return construction."},
        {"field": "upper_limit/lower_limit/historical_rules", "status": "NOT_IN_PROVIDER_RESPONSE",
         "impact": "Do not derive all products' limits from a fixed percentage or execute on unverified historical rules."},
        {"field": "published_at/available_at/revision_id", "status": "NOT_IN_PROVIDER_RESPONSE",
         "impact": "Today's download is not historical first availability; original vintages or justified public-asof reconstruction required."},
        {"field": "CSI300_total_return_index_H00300", "status": "SEPARATE_SOURCE_REQUIRES_ADMISSION",
         "impact": "This BaoStock collection does not contain the benchmark; separately captured CSI observations still need PIT admission. A price index or ETF proxy cannot replace total return."},
        {"field": "dual_source_reconciliation/license/account_permissions/historical_fees", "status": "REVIEW_REQUIRED",
         "impact": "Read access and a single successful response cannot declare all Dataset evidence gates verified."},
    ]
    return {"schema_version": "real-staging-audit-1.0", "status": "BLOCKED_DATA",
        "collection_sha256": hashlib.sha256(content).hexdigest(), "synthetic": False,
        "request_plan_sha256": plan_sha256, "planned_queries": len(planned),
        "performance_evidence": False, "strategy_runs_permitted": False,
        "integrity_status": "PASS" if not errors else "FAIL", "errors": errors,
        "calendar_rows": calendar_rows, "trading_sessions": len(sessions),
        "queries_verified": len(verified), "queries_requested": len(collection["query_results"]),
        "histories": histories, "universe_snapshots": snapshots, "current_master_queries": masters,
        "blockers": blockers,
        "holdout": {"status": "LOCKED", "historical_requests_after_2024": 0,
                    "historical_observations_after_2024": 0,
                    "scope": "Hash/identity/response-validated queries only; rejected evidence is never admitted",
                    "current_metadata_used_as_historical_features": False},
        "interpretation": "Observed-data integrity audit only. Not an admitted Dataset or a historical strategy backtest."}
