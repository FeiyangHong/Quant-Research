"""Evidence-preserving real-data staging. This module cannot admit a backtest.

Unknown publication times, rules and permissions remain missing or blocked.
Only an explicit reviewed policy can supply a reconstruction or account model.
"""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..data import Dataset, EVIDENCE_GATES, REQUIRED, SCHEMA_VERSION, TABLES, audit_dataset, date_only_available_at
from ..dependencies import representative_dependencies


class BuildBlockedError(ValueError):
    pass


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verified_file(root, relative, expected):
    root, path = Path(root).resolve(), (Path(root) / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise BuildBlockedError("Snapshot path missing or outside collection: " + str(relative))
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise BuildBlockedError("Source SHA256 mismatch: " + str(relative))
    return json.loads(payload)


def _frame(records, required):
    frame = pd.DataFrame(records)
    for name in required:
        if name not in frame:
            frame[name] = pd.Series([None] * len(frame), dtype=object)
    return frame


def _number(value):
    if value is None or value == "":
        return None
    result = float(value)
    if not np.isfinite(result):
        raise BuildBlockedError("Nonfinite source numeric observation")
    return result


def _aware(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise BuildBlockedError("Explicit timezone required: " + str(value))
    return stamp


def _max_time(*values):
    present = [value for value in values if value is not None and pd.notna(value)]
    return max(present, key=_aware) if present else None


def _availability(day, policy, calendar=None):
    if not policy:
        return {"available_at": None, "published_at": None, "publication_precision": "unknown",
                "availability_mode": "historical_public_asof", "availability_reconstruction": None}
    if policy.get("mode") != "historical_public_asof" or not policy.get("reconstruction_basis") or not policy.get("source_url"):
        raise BuildBlockedError("Daily reconstruction needs public-asof policy, rationale and evidence")
    clock = policy.get("available_clock")
    if not isinstance(clock, str):
        raise BuildBlockedError("Explicit daily availability clock required")
    available = day + "T" + clock + "+08:00"
    if policy.get("publication_precision") == "date_only":
        if calendar is None:
            raise BuildBlockedError("Date-only series needs the verified availability calendar")
        available = date_only_available_at(day, calendar)
    if _aware(available) < _aware(day + "T15:00:00+08:00"):
        raise BuildBlockedError("Daily final market observation cannot precede close")
    template = policy.get("published_at_template")
    return {"available_at": available, "published_at": template.format(date=day) if template else None,
            "market_event_at": day + "T15:00:00+08:00" if policy.get("publication_precision") == "reconstructed_market_close" else None,
            "market_event_time_basis": "SCHEDULED_SESSION_END_NOT_OBSERVED_LAST_TRADE" if policy.get("publication_precision") == "reconstructed_market_close" else None,
            "publication_precision": policy.get("publication_precision", "unknown"),
            "availability_mode": "historical_public_asof",
            "availability_reconstruction": policy["reconstruction_basis"],
            "availability_evidence_url": policy["source_url"]}


def historical_limits(record, benchmark_id, rules):
    """Return documented historical price limits; never infer 10% from prices."""
    matched = [r for r in rules if r["effective_from"] <= record["date"] <= r["effective_to"]
               and (r.get("instrument_id") == record["instrument_id"] or
                    (not r.get("instrument_id") and r.get("benchmark_id") == benchmark_id))]
    if not matched:
        return {"upper_limit": None, "lower_limit": None, "rule_id": None}
    if len(matched) != 1:
        raise BuildBlockedError("Overlapping historical rules: " + record["instrument_id"] + "/" + record["date"])
    rule = matched[0]
    if not rule.get("source_url") or not rule.get("rule_id") or _aware(rule["available_at"]) > _aware(record["date"] + "T09:30:00+08:00"):
        raise BuildBlockedError("Historical rule lacks contemporaneous evidence")
    reference, tick = Decimal(str(record["preclose"])), Decimal(str(rule["tick_size"]))
    ratio = Decimal(str(rule["limit_ratio"]))
    if reference <= 0 or tick <= 0 or not 0 < ratio < 1:
        raise BuildBlockedError("Invalid documented price-limit inputs")
    # Provider preclose is retained as the stated ex-rights reference. It is
    # never replaced with yesterday's close across a corporate action.
    return {"upper_limit": float(((reference * (1 + ratio) / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * tick),
            "lower_limit": float(((reference * (1 - ratio) / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * tick),
            "rule_id": rule["rule_id"], "rule_source_url": rule["source_url"], "limit_reference_price": float(reference)}


def reconstruct_total_return(frame, actions, start="2015-01-01"):
    """Proportional fund TR; account share rounding belongs only in execution.

    BOD suspension rows may retain old-unit prices. EOD closes are pre-change.
    Later-known terms delay availability; they never become early features.
    Returns a copy, with source OHLC unmodified, and explicit reconstruction issues.
    """
    result = frame.sort_values("date").copy()
    result["total_return_index"] = np.nan
    result["total_return_available_at"] = None
    result["valuation_close"] = np.nan
    result["total_return_method"] = "RAW_PRICE_CA_PROPORTIONAL_EX_DATE_REINVESTMENT"
    events, issues = {}, []
    for action in actions.to_dict("records"):
        events.setdefault(action["ex_date"], []).append(action)
    previous_mark, level, dependency_at = None, 100., None
    broken = False
    for index, row in result.iterrows():
        day = row["date"]
        if day < start:
            continue
        old_mark, units, cash = previous_mark, Decimal(1), Decimal(0)
        mark = previous_mark
        today = [a for a in events.get(day, []) if a.get("action_status", "CONFIRMED") != "CANCELLED"]
        today.sort(key=lambda a: (a.get("effective_phase", "BOD") == "EOD", a["action_type"] != "SPLIT"))
        for phase in ("BOD", "EOD"):
            if phase == "EOD" and not row["suspended"] and row["volume"] > 0:
                mark = Decimal(str(row["close"]))
            for action in today:
                if action.get("effective_phase", "BOD") != phase:
                    continue
                if not action.get("available_at"):
                    issues.append({"instrument_id": row["instrument_id"], "date": day, "reason": "ACTION_AVAILABILITY_UNKNOWN"})
                    broken = True
                    continue
                dependency_at = _max_time(dependency_at, action["available_at"])
                kind = action["action_type"]
                if kind == "SPLIT":
                    factor = Decimal(str(action["share_factor"]))
                    if factor <= 0:
                        raise BuildBlockedError("Nonpositive share conversion ratio")
                    units *= factor
                    if mark is not None:
                        mark /= factor
                elif kind == "CASH_DIVIDEND":
                    dividend = Decimal(str(action["cash_per_share"]))
                    cash += units * dividend
                    if mark is not None:
                        mark -= dividend
                else:
                    issues.append({"instrument_id": row["instrument_id"], "date": day, "reason": "UNSUPPORTED_TR_EVENT:" + kind})
                    broken = True
        if previous_mark is None:
            mark = Decimal(str(row["close"]))
            if today:
                issues.append({"instrument_id": row["instrument_id"], "date": day, "reason": "TR_START_COINCIDES_WITH_ACTION_WITHOUT_PRIOR_MARK"})
                broken = True
        if mark is None or mark <= 0:
            broken = True
            issues.append({"instrument_id": row["instrument_id"], "date": day, "reason": "NO_POSITIVE_VALUATION"})
        if old_mark is not None and not broken:
            level *= float((units * mark + cash) / old_mark)
        previous_mark = mark
        if broken:
            continue
        result.at[index, "total_return_index"] = level
        result.at[index, "valuation_close"] = float(mark)
        availability = _max_time(row.get("market_available_at", row.get("available_at")), dependency_at)
        if row.get("market_available_at", row.get("available_at")) is None:
            availability = None
        result.at[index, "total_return_available_at"] = availability
        # Price/turnover facts keep their own clock. A later share-ratio
        # disclosure may delay TR, but must never change the ADV competition.
    return result, issues


def _coverage_complete(manifest, sid, years):
    coverage = manifest.get("coverage", manifest.get("corporate_action_coverage", []))
    if isinstance(coverage, dict):
        coverage = coverage.get("records", [])
    good = {int(r["year"]) for r in coverage if r.get("instrument_id") == sid and
            ((r.get("status") in ("COMPLETE", "VERIFIED_COMPLETE") and r.get("source_url")) or
             (not r.get("unresolved") and r.get("report_hashes") and
              r.get("dividend_status") in ("EXPLICIT_ZERO_RECONCILED", "RECONCILED_POSITIVE") and
              r.get("split_status") in ("EXPLICIT_NONE", "EXECUTED_CHANGE_DOCUMENTED")))}
    return sorted(set(years) - good)


def normalize_actions(manifest, policy, ingested_at):
    """Map canonical documentary facts; missing settlement remains a blocker."""
    rows = []
    overrides = policy.get("action_overrides", {})
    documents = {doc.get("pdf_sha256", doc.get("source_sha256")): doc for doc in manifest.get("documents", [])}
    for event in manifest.get("canonical_actions", []):
        kind = event.get("action_type", event.get("type"))
        kind = "CASH_DIVIDEND" if kind == "DIVIDEND" else kind
        phase = event.get("effective_phase", "BOD")
        phase_map = {"END_OF_DAY": "EOD", "SUSPENDED_SESSION": "BOD", "PRE_LISTING": "BOD", "BOD": "BOD", "EOD": "EOD"}
        if phase not in phase_map:
            raise BuildBlockedError("Unresolved canonical share phase: " + str(phase))
        source_hash = event.get("source_sha256", event.get("raw_object_hash"))
        document = documents.get(source_hash, {})
        ratio = event.get("split_ratio", event.get("share_factor"))
        ratio = 1 if ratio is None and kind != "SPLIT" else ratio
        row = dict(event, action_type=kind, share_factor=_number(ratio),
            cash_per_share=_number(event.get("cash_per_share", 0)), recovery_per_share=event.get("recovery_per_share"),
            pay_date=event.get("pay_date", event.get("scheduled_pay_date")), effective_phase=phase_map[phase],
            rounding_policy=event.get("fractional_share_rounding", event.get("rounding_policy", "EXACT")),
            action_status="CANCELLED" if event.get("status") == "CANCELLED" else "CONFIRMED",
            action_usage_scope="PRE_LISTING_METADATA_ONLY" if phase == "PRE_LISTING" else "ACCOUNTING_EVENT",
            available_at=event.get("ratio_available_at", event.get("available_at")),
            revision_id=event.get("revision_id", source_hash), supersedes_id=event.get("supersedes_id"),
            terms_verified=event.get("parse_status") in ("HUMAN_RECONCILED_HASH_BOUND", "PARSED_LABELED_TABLE"),
            publication_precision="date_only", published_at=document.get("publication_date", event.get("ratio_publication_date", event.get("announcement_date"))),
            vendor_first_seen_at=None, ingested_at=ingested_at, processed_at=ingested_at,
            availability_mode="historical_public_asof", source="Official issuer announcement",
            endpoint=event.get("source_url"), source_record_id=event["action_id"], raw_object_hash=source_hash,
            license_profile_id=policy.get("license_profile_id"), quality_status="provisional")
        if kind == "SPLIT":
            # Shenzhen may register new units at D's close while calling D+1
            # the ex-date. Preserve both source facts; the ledger trigger is D.
            row["source_ex_date"] = event["ex_date"]
            row["ex_date"] = event.get("effective_date", event["ex_date"])
        row.update(overrides.get(event["action_id"], {}))
        rows.append(row)
    # Canceled plans remain evidence without creating a second economic event.
    known = {row["action_id"] for row in rows}
    for event in manifest.get("cancelled_actions", []):
        if event["action_id"] not in known:
            clone = dict(event, status="CANCELLED")
            rows.extend(normalize_actions({"canonical_actions": [clone]}, policy, ingested_at))
    return rows


def build_dataset(collection_root, benchmark_root, event_manifest, policy=None, dataset_id="r1-real-staging"):
    """Build all documented competitors, preserving blockers and original evidence."""
    root, benchmark_root = Path(collection_root), Path(benchmark_root)
    policy = {} if policy is None else dict(policy)
    if policy and policy.get("schema_version") != "r1-build-policy-1.0":
        raise BuildBlockedError("Unknown build policy schema")
    event_path = Path(event_manifest).resolve() if isinstance(event_manifest, (str, Path)) else None
    event_payload = event_path.read_bytes() if event_path else None
    event_manifest = json.loads(event_payload) if event_payload else event_manifest
    imported_at = datetime.now(timezone.utc).isoformat()
    candidates_file = policy.get("candidates_file", "candidates_documentary_v1.json")
    inventory_file = policy.get("inventory_file", "inventory_documentary_v1.json")
    candidates = _json(root / candidates_file)
    inventory = _json(root / inventory_file)
    source_hashes = {str(root / name): _sha(root / name) for name in
                     (candidates_file, inventory_file)}
    project_root = Path(policy.get("project_root", Path.cwd())).resolve()

    def bind(relative, expected):
        path = (project_root / relative).resolve()
        path.relative_to(project_root)
        if not path.is_file() or _sha(path) != expected:
            raise BuildBlockedError("Policy documentary source missing/hash mismatch: " + str(relative))
        source_hashes[str(path)] = expected

    for evidence in policy.get("source_evidence_files", []):
        bind(evidence["path"], evidence["sha256"])
    for record in policy.get("instrument_records", []):
        if record.get("source_path"):
            bind(str(Path(record["source_root"]) / record["source_path"]), record["raw_object_hash"])
        if record.get("benchmark_source_path"):
            bind(str(Path(record["source_root"]) / record["benchmark_source_path"]), record["benchmark_source_hash"])
        known = record.get("benchmark_source_available_at")
        if known and _aware(known) > _aware(record["available_at"]):
            raise BuildBlockedError("Benchmark identity known after historical master availability")
    documentary_name = policy.get("documentary_manifest_file")
    if documentary_name:
        doc = _json(root / documentary_name)
        if doc.get("candidates_path") != candidates_file or doc.get("inventory_path") != inventory_file:
            raise BuildBlockedError("Documentary manifest does not bind the chosen inventory version")
        _verified_file(root, candidates_file, doc["candidates_sha256"])
        _verified_file(root, inventory_file, doc["inventory_sha256"])
        # Verify the self-contained input snapshots, not mutable collector
        # filenames that may have acquired a later documentary revision.
        for source in doc.get("evidence_sources", []):
            if isinstance(source, dict) and "snapshot_path" in source:
                _verified_file(root, source["snapshot_path"], source["sha256"])
                source_hashes[str(root / source["snapshot_path"])] = source["sha256"]
        source_hashes[str(root / documentary_name)] = _sha(root / documentary_name)
    calendar_query = _json(root / "calendar_query.json")
    payload = _verified_file(root, calendar_query["raw_path"], calendar_query["raw_sha256"])
    calendar_rows = [dict(zip(payload["fields"], row)) for row in payload["rows"]]
    calendar = sorted(r["calendar_date"] for r in calendar_rows if r["is_trading_day"] == "1")
    if not calendar or calendar[-1] > "2024-12-31":
        raise BuildBlockedError("Calendar empty or opens locked final holdout")
    availability_calendar = sorted(set(calendar + policy.get("availability_extra_sessions", [])))
    source_hashes[str(root / calendar_query["raw_path"])] = calendar_query["raw_sha256"]
    queries = {}
    for path in sorted((root / "query_cache").glob("*.json")):
        query = _json(path)
        if query.get("kind") != "history" or query.get("status") != "SUCCESS":
            continue
        code = query["code"]
        if code in queries:
            raise BuildBlockedError("Ambiguous multiple successful history snapshots: " + code)
        queries[code] = query
    overrides = {}
    for record in policy.get("instrument_records", []):
        overrides.setdefault(record["instrument_id"], []).append(record)
    qualified = set(policy.get("account_scenario", {}).get("product_qualified_instruments", []))
    rules = policy.get("historical_rules", [])
    blockers, instrument_rows, bar_rows, gap_report = [], [], [], {}
    for candidate in candidates:
        sid = candidate["code"]
        query = queries.get(sid)
        if query is None:
            blockers.append({"scope": sid, "reason": "NO_SUCCESSFUL_RAW_HISTORY"})
            raw, records = {}, []
        else:
            _verified_file(root, query["manifest_path"], query["manifest_sha256"])
            raw = _verified_file(root, query["raw_path"], query["raw_sha256"])
            normalized = _verified_file(root, query["normalized_path"], query["normalized_sha256"])
            for field in ("raw", "normalized", "manifest"):
                source_hashes[str(root / query[field + "_path"])] = query[field + "_sha256"]
            records = normalized["records"]
            if len(records) != query["row_count"]:
                raise BuildBlockedError("Normalized row count mismatch: " + sid)
        ingested = raw.get("ingested_at")
        listed = candidate.get("listing_date_from_current_master")
        delisted = candidate.get("delisting_date_from_current_master")
        base = {"instrument_id": sid, "asset_type": "ETF", "board": "ETF", "listed_on": listed,
                "delisted_on": None, "available_at": ingested, "account_verified": sid in qualified,
                "account_permission_basis": policy.get("account_scenario", {}).get("label", "UNVERIFIED"),
                "benchmark_id": candidate.get("category"), "industry": "BROAD_MARKET",
                "lot_size": None, "tick_size": None, "t_plus": None, "strategy_universe": "R1B",
                "revision_id": sid + "_CURRENT_METADATA_STAGING", "supersedes_id": None,
                "published_at": None, "publication_precision": "unknown", "vendor_first_seen_at": None,
                "ingested_at": ingested, "processed_at": ingested, "availability_mode": "live_capture",
                "source": "BaoStock current master; documentary classification inventory",
                "endpoint": "query_stock_basic", "source_record_id": sid,
                "raw_object_hash": source_hashes[str(root / candidates_file)],
                "license_profile_id": policy.get("license_profile_id"), "quality_status": "provisional",
                "historical_metadata_verified": False}
        if sid not in overrides:
            blockers.append({"scope": sid, "reason": "ORIGINAL_PIT_LISTING_AND_CATEGORY_EVIDENCE_REQUIRED"})
        prior = base
        for number, overlay in enumerate(sorted(overrides.get(sid, [{}]), key=lambda r: str(r.get("available_at", "")))):
            if overlay and number == 0 and not {"benchmark_id", "strategy_universe", "listed_on", "available_at"}.issubset(overlay):
                raise BuildBlockedError("Original historical identity must explicitly specify listing/category/universe: " + sid)
            merged = dict(prior, **overlay)
            if overlay and number:
                if "revision_id" not in overlay or overlay["revision_id"] == prior["revision_id"]:
                    raise BuildBlockedError("Historical master update needs a distinct revision_id: " + sid)
                merged["supersedes_id"] = overlay.get("supersedes_id", prior["revision_id"])
            instrument_rows.append(merged)
            prior = merged
        # Final documentary lifespan is for retrospective coverage only. Each
        # trading decision still reads the dated revision chain above.
        listed, delisted = prior.get("listed_on"), prior.get("delisted_on")
        expected = {day for day in calendar if listed and day >= listed and (not delisted or day < delisted)}
        observed = {r["date"] for r in records}
        missing, excess = sorted(expected - observed), sorted(observed - expected)
        if missing or excess:
            gap_report[sid] = {"missing_listed_sessions": missing, "outside_current_listing_interval": excess}
            blockers.append({"scope": sid, "reason": "LISTED_SESSION_COVERAGE", "missing": len(missing), "outside": len(excess)})
        for source in records:
            if source["instrument_id"] != sid or source["source_adjustflag"] != "3":
                raise BuildBlockedError("Raw-price identity/adjustflag mismatch")
            record = {k: source[k] for k in ("date", "instrument_id", "suspended")}
            record.update({k: _number(source.get(k)) for k in ("open", "high", "low", "close", "preclose", "volume", "amount")})
            record.update(_availability(record["date"], policy.get("market_availability"), availability_calendar))
            record["market_available_at"] = record["available_at"]
            record.update(historical_limits(record, candidate.get("category"), rules))
            record.update(revision_id=query["raw_sha256"][:16] + ":" + record["date"], supersedes_id=None,
                total_return_index=None, usage_scope="REPRESENTATIVE_SELECTION_ONLY", source="BaoStock",
                endpoint="query_history_k_data_plus(adjustflag=3)", source_record_id=sid + ":" + record["date"],
                raw_object_hash=query["raw_sha256"], vendor_first_seen_at=None, ingested_at=source["ingested_at"],
                processed_at=source["ingested_at"], license_profile_id=policy.get("license_profile_id"),
                quality_status="provisional", source_trade_status=source["source_trade_status"],
                normalization_issues=source.get("normalization_issues", []))
            bar_rows.append(record)
    bm_manifest = _json(benchmark_root / "manifest.json")
    for relative, expected in bm_manifest["files"].items():
        path = benchmark_root / relative
        if _sha(path) != expected:
            raise BuildBlockedError("Benchmark snapshot SHA256 mismatch: " + relative)
        source_hashes[str(path)] = expected
    benchmark_rows = []
    for row in _json(benchmark_root / "observations.json")["records"]:
        record = dict(row, total_return_index=float(row["total_return_index"]),
            revision_id=bm_manifest["files"]["raw/csi_h00300.payload"][:16] + ":" + row["date"], supersedes_id=None,
            vendor_first_seen_at=None, ingested_at=policy.get("benchmark_ingested_at", imported_at),
            processed_at=imported_at, source="CSI", endpoint=bm_manifest["source_endpoint"],
            source_record_id="H00300:" + row["date"], raw_object_hash=bm_manifest["files"]["raw/csi_h00300.payload"],
            license_profile_id=policy.get("license_profile_id"), quality_status="provisional")
        record.update(_availability(row["date"], policy.get("benchmark_availability"), availability_calendar))
        benchmark_rows.append(record)
    action_rows = normalize_actions(event_manifest, policy, imported_at)
    if event_path:
        source_hashes[str(event_path)] = hashlib.sha256(event_payload).hexdigest()
        evidence_root = event_path.parents[2] / event_manifest["source_root"]
        for event in event_manifest.get("canonical_actions", []):
            for digest in event.get("source_hashes", [event.get("source_sha256")]):
                evidence = evidence_root / "raw" / (digest + ".bin")
                if not evidence.is_file() or _sha(evidence) != digest:
                    raise BuildBlockedError("Official source snapshot missing/hash mismatch: " + str(evidence))
                source_hashes[str(evidence)] = digest
        for coverage in event_manifest.get("coverage", []):
            for field in ("report_hashes", "dividend_source_hashes", "dividend_annual_source_hashes", "split_source_hashes"):
                for digest in coverage.get(field, []):
                    evidence = evidence_root / "raw" / (digest + ".bin")
                    if not evidence.is_file() or _sha(evidence) != digest:
                        raise BuildBlockedError("Coverage proof snapshot missing/hash mismatch: " + str(evidence))
                    source_hashes[str(evidence)] = digest
    if not action_rows:
        blockers.append({"scope": "actions", "reason": "CANONICAL_OFFICIAL_ACTIONS_NOT_READY"})
    manifest = {"dataset_id": dataset_id, "schema_version": SCHEMA_VERSION, "dataset_version": "staging-1",
        "synthetic": False, "timezone": "Asia/Shanghai", "status": "STAGING_ONLY", "performance_evidence": False,
        "strategy_runs_permitted": False, "availability_mode": "historical_public_asof",
        "calendar_kind": "PROVIDER_CALENDAR_PENDING_REVIEW", "license_profile_id": policy.get("license_profile_id"),
        "units": {"volume": "shares_or_fund_units", "amount": "CNY", "price": "CNY"},
        "source_snapshot_hashes": source_hashes,
        "evidence_gates": {name: {"status": "PENDING_INDEPENDENT_REVIEW"} for name in EVIDENCE_GATES},
        "inventory_count": len(inventory) if isinstance(inventory, list) else len(inventory.get("records", inventory)),
        "documentary_competitor_count": len(candidates), "tr_coverage_start": "2015-01-01", "account_start": "2016-01-01",
        "build_policy": policy, "event_manifest_status": event_manifest.get("status")}
    manifest.update(availability_calendar=availability_calendar,
                    availability_calendar_evidence=policy.get("availability_calendar_evidence"),
                    signal_release_delay=policy.get("signal_release_delay", 0))
    dataset = Dataset(calendar, _frame(instrument_rows, REQUIRED["instruments"]), _frame(bar_rows, REQUIRED["bars"]),
                      _frame(action_rows, REQUIRED["actions"]), _frame(benchmark_rows, REQUIRED["benchmark"]), manifest)
    try:
        dependencies = representative_dependencies(dataset)
    except (ValueError, TypeError, KeyError) as exc:
        dependencies = {"status": "BLOCKED_METADATA_AVAILABILITY", "reason": str(exc), "required_full_history_instruments": []}
    declared = set(policy.get("required_full_history_instruments", []))
    required = set(dependencies["required_full_history_instruments"])
    if declared and declared != required:
        blockers.append({"scope": "dependencies", "reason": "DECLARED_UNION_DIFFERS_FROM_INDEPENDENT_SELECTOR",
                         "declared": sorted(declared), "recomputed": sorted(required)})
    full = required | declared  # Extra coverage is allowed; never remove an independent requirement.
    reconstructed = []
    for sid, frame in dataset.bars.groupby("instrument_id", sort=False):
        if sid not in full:
            reconstructed.append(frame)
            continue
        years = {int(d[:4]) for d in frame.date if d >= "2015-01-01"}
        missing_years = _coverage_complete(event_manifest, sid, years)
        frame = frame.copy()
        frame.loc[frame.date.ge("2015-01-01"), "usage_scope"] = "FULL_STRATEGY"
        if missing_years:
            blockers.append({"scope": sid, "reason": "OFFICIAL_ACTION_YEAR_COVERAGE_MISSING", "years": missing_years})
        else:
            frame, issues = reconstruct_total_return(frame, dataset.actions.loc[dataset.actions.instrument_id.eq(sid)])
            blockers.extend(issues)
        reconstructed.append(frame)
    dataset.bars = pd.concat(reconstructed, ignore_index=True) if reconstructed else dataset.bars
    manifest["representative_dependencies"] = dependencies
    manifest["required_full_history_instruments"] = sorted(full)
    manifest["build_blockers"] = blockers
    report = {"status": "STAGING_ONLY", "blockers": blockers, "listing_gaps": gap_report,
              "inventory_count": manifest["inventory_count"], "competitor_count": len(candidates),
              "required_full_history_instruments": sorted(full), "source_file_count": len(source_hashes)}
    try:
        report["dataset_audit"] = audit_dataset(dataset)
    except (ValueError, TypeError, KeyError) as exc:
        report["dataset_audit"] = {"status": "BLOCKED_DATA", "reason": str(exc)}
    return dataset, report


def write_staged(dataset, report, destination):
    """Write honest missing values; admission loader may and should reject them."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Use a new immutable staging directory")
    objects = {"calendar.json": dataset.calendar, "build_report.json": report}
    for name in TABLES:
        frame = getattr(dataset, name)
        objects[name + ".json"] = {"columns": list(frame.columns),
            "records": frame.astype(object).where(pd.notnull(frame), None).to_dict("records")}
    serialized = {name: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                  for name, value in objects.items()}
    manifest = dict(dataset.manifest, file_sha256={name: hashlib.sha256(payload).hexdigest() for name, payload in serialized.items()})
    serialized["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in serialized.items():
        with (destination / name).open("xb") as stream:
            stream.write(payload)
    return manifest
