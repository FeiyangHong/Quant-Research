"""Discover all historical R1B competitors before calculating any returns."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quant_research.providers.baostock import BaoStockAdapter, Query, canonical, normalize_history, write_immutable
from quant_research.providers.universe import (build_inventory, collect_metadata, quarter_sessions,
                                              reconcile_inventory, provisional_amount_representatives)


def preserve_input(output, path):
    """Keep exact documentary JSON bytes even if another collector refreshes it."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    relative = Path("documentary_inputs") / (digest + ".json")
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("Immutable documentary input collision")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
    return {"path": path.as_posix(), "sha256": digest, "snapshot_path": relative.as_posix()}


def cached_collect(adapter, query, repair_failed=False):
    query.validate()
    key = hashlib.sha256(canonical(query.__dict__)).hexdigest()
    cache = adapter.output_dir / "query_cache" / (key + ".json")
    repairs = sorted(cache.parent.glob(key + "_repair*.json"))
    if cache.exists():
        entry = json.loads((repairs[-1] if repairs else cache).read_bytes())
        raw = (adapter.output_dir / entry["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
            raise ValueError("Query cache integrity failure")
        if entry["status"] == "SUCCESS" or not repair_failed or len(repairs) >= 2:
            return entry, json.loads(raw)
        # Explicit bounded repair after an identified session-interference
        # cause was removed. Original failed objects/manifests stay immutable.
        cache = cache.with_name(key + "_repair" + str(len(repairs) + 1) + ".json")
    entry = adapter.collect(query)
    payload = json.loads((adapter.output_dir / entry["raw_path"]).read_bytes())
    if entry["status"] == "SUCCESS" and query.kind == "history":
        normalized = normalize_history(payload)
        path = Path("normalized") / (key + ".json")
        entry["normalized_path"] = path.as_posix()
        entry["normalized_sha256"] = write_immutable(adapter.output_dir / path, normalized)
    write_immutable(cache, entry)
    print(json.dumps({"kind": query.kind, "code": query.code, "date": query.date, "status": entry["status"], "rows": entry["row_count"]}), flush=True)
    return entry, payload


def collect_inventory(adapter, sdk_path, repair_failed=False, revision=1):
    root = adapter.output_dir
    calendar_entry, calendar = cached_collect(adapter, Query("calendar", start="2010-01-01", end="2024-12-31"), repair_failed)
    if calendar["status"] != "SUCCESS":
        raise RuntimeError("Cannot enumerate without complete historical calendar")
    rows = [dict(zip(calendar["fields"], r)) for r in calendar["rows"]]
    sessions = [r["calendar_date"] for r in rows if r["is_trading_day"] == "1"]
    dates = sorted(set(quarter_sessions(sessions) + [sessions[0]]))
    entries, universes = [], []
    for day in dates:
        entry, payload = cached_collect(adapter, Query("universe", date=day), repair_failed)
        entries.append(entry)
        universes.append(payload)
    metadata_entries, metadata = [], []
    master_entry, master = collect_metadata(root, "master_all", sdk_path)
    metadata_entries.append(master_entry)
    metadata.append(master)
    # Existing archived metadata reads are cheap; no current-name hindsight
    # filter can discard an old identity before historical names are sought.
    for path in sorted((root / "metadata").glob("names_asof_*.json")):
        entry = json.loads(path.read_bytes())
        payload = json.loads((root / entry["raw_path"]).read_bytes())
        metadata_entries.append(entry)
        metadata.append(payload)
    attempted = {r.get("date") for r in metadata_entries}
    inventory = build_inventory(universes, metadata)
    no_gain_successes = 0
    while True:
        unknown = {r["code"] for r in inventory if not r["names"]}
        # Greedy historical-day coverage avoids querying every name/date when
        # one old snapshot can recover many withdrawn identities at once.
        ranked = []
        for day, payload in zip(dates, universes):
            if day in attempted or payload["status"] != "SUCCESS":
                continue
            index = payload["fields"].index("code")
            ids = {r[index] for r in payload["rows"]}
            ranked.append((len(ids & unknown), day))
        if not unknown or not ranked or max(ranked)[0] == 0:
            break
        _, day = max(ranked)
        attempted.add(day)
        entry, payload = collect_metadata(root, "names_asof", sdk_path, day)
        metadata_entries.append(entry)
        metadata.append(payload)
        inventory = build_inventory(universes, metadata)
        print(json.dumps({"kind": "historical_names", "date": day, "status": entry["status"],
                          "unresolved_names": sum(not row["names"] for row in inventory)}), flush=True)
        if payload["status"] == "SUCCESS" and sum(not row["names"] for row in inventory) >= len(unknown):
            no_gain_successes += 1
        if no_gain_successes >= 1:
            # Observed current-master filtering survives the date argument.
            # Do not repeat dozens of large queries that cannot recover dead
            # identities; retain those IDs for official disclosure discovery.
            break
        # A failed or stale provider must not create an unbounded sweep. The
        # full quarter request set is a finite upper bound, and all gaps remain.
    candidates = [r for r in inventory if r["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"]
    suffix = "" if revision == 1 else "_v" + str(revision)
    inventory_path = root / ("inventory" + suffix + ".json")
    candidates_path = root / ("candidates" + suffix + ".json")
    write_immutable(inventory_path, inventory)
    write_immutable(candidates_path, candidates)
    positions = {day: i for i, day in enumerate(sessions)}
    max_gap = max(positions[b] - positions[a] for a, b in zip(dates, dates[1:]))
    successful_dates = [entry["date"] for entry in entries if entry["status"] == "SUCCESS"]
    observed_max_gap = max((positions[b] - positions[a] for a, b in zip(successful_dates, successful_dates[1:])), default=None)
    manifest = {"schema_version": "r1-universe-discovery-1.0", "status": "DISCOVERY_REQUIRES_OFFICIAL_VERIFICATION",
                "performance_evidence": False, "calendar": calendar_entry, "snapshot_queries": entries,
                "metadata_queries": metadata_entries, "snapshot_dates": dates,
                "maximum_planned_snapshot_gap_trading_sessions": max_gap,
                "maximum_successful_snapshot_gap_trading_sessions": observed_max_gap,
                "all_requested_snapshots_succeeded": len(successful_dates) == len(dates), "minimum_listing_age_strategy": 252,
                "eligibility_coverage_logic": "Quarterly representatives are selected on previous-quarter final session: complete membership at every such endpoint covers every possible representative; snapshot-source completeness and exact-index histories require external evidence. Products living entirely between endpoints cannot be representatives.",
                "inventory_count": len(inventory), "candidate_count": len(candidates),
                "unresolved_name_codes": [r["code"] for r in inventory if not r["names"]],
                "inventory_path": inventory_path.name, "candidates_path": candidates_path.name,
                "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
                "candidates_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest()}
    write_immutable(root / ("universe_manifest" + suffix + ".json"), manifest)
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/raw_r1_universe/r1_2010_2024"))
    parser.add_argument("--sdk-path", type=Path)
    parser.add_argument("--stage", choices=["inventory", "histories", "all", "reconcile", "dependencies"], default="all")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--official-evidence", type=Path, nargs="*", default=[])
    parser.add_argument("--universe-manifest", type=Path)
    parser.add_argument("--history-manifest", type=Path)
    parser.add_argument("--master-records", type=Path)
    parser.add_argument("--repair-failed", action="store_true", help="Bounded explicit repair; preserve original failure snapshots")
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()
    if args.stage == "dependencies":
        if not all([args.candidates, args.universe_manifest, args.history_manifest]):
            parser.error("Dependencies requires candidates, universe-manifest and history-manifest")
        def checked(entry, label):
            raw = (args.output / entry[label + "_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry[label + "_sha256"]:
                raise ValueError("Dependency source hash mismatch: " + entry[label + "_path"])
            return json.loads(raw)
        inventory_manifest = json.loads(args.universe_manifest.read_bytes())
        calendar = checked(inventory_manifest["calendar"], "raw")
        sessions = [dict(zip(calendar["fields"], row)) for row in calendar["rows"]]
        sessions = [row["calendar_date"] for row in sessions if row["is_trading_day"] == "1"]
        candidates = json.loads(args.candidates.read_bytes())
        collection = json.loads(args.history_manifest.read_bytes())
        histories = {}
        for entry in collection["query_results"]:
            if entry["status"] != "SUCCESS":
                raise ValueError("Failed raw history cannot be dropped from competition: " + entry["code"])
            checked(entry, "raw")
            histories[entry["code"]] = checked(entry, "normalized")["records"]
        master = json.loads(args.master_records.read_bytes()) if args.master_records else None
        answer = provisional_amount_representatives(sessions, candidates, histories, master)
        paths = [args.candidates, args.universe_manifest, args.history_manifest] + ([args.master_records] if args.master_records else [])
        answer["sources"] = [preserve_input(args.output, path) for path in paths]
        answer["candidate_count"] = len(candidates)
        answer["history_row_count"] = sum(len(value) for value in histories.values())
        target = args.output / ("provisional_dependencies_v" + str(args.revision) + ".json")
        write_immutable(target, answer)
        print(json.dumps({"status": answer["status"], "representatives": answer["required_full_history_instruments"],
                          "membership_conflicts": len(answer["endpoint_membership_conflicts"]), "path": str(target)}))
        return
    if args.stage == "reconcile":
        if args.inventory is None or not args.official_evidence:
            parser.error("Reconcile requires --inventory and --official-evidence directories")
        inventory = json.loads(args.inventory.read_bytes())
        records, sources = [], []
        for directory in args.official_evidence:
            paths = sorted(directory.glob("*.json")) if directory.is_dir() else [directory]
            for path in paths:
                raw = path.read_bytes()
                value = json.loads(raw)
                for record in value if isinstance(value, list) else [value]:
                    if "candidate" in record:
                        records.append(record)
                    elif record.get("role", "").startswith("ORIGINAL_PUBLIC_"):
                        records.append({"candidate": {"code": record["instrument_id"]}, "listing_evidence": [record]})
                    elif "instrument_id" in record:
                        records.append({"candidate": {"code": record["instrument_id"]}, "annual_evidence": [record]})
                    elif "code" in record:
                        records.append({"candidate": {"code": record["code"]}, "identity_evidence": record})
                    else:
                        raise ValueError("Unrecognized documentary evidence record: " + str(path))
                sources.append(preserve_input(args.output, path))
        reconciled = reconcile_inventory(inventory, records)
        candidates = [row for row in reconciled if row["candidate_for_history_collection"]]
        inventory_path = args.output / ("inventory_documentary_v" + str(args.revision) + ".json")
        candidate_path = args.output / ("candidates_documentary_v" + str(args.revision) + ".json")
        manifest = {"schema_version": "r1-universe-documentary-1.0", "status": "DOCUMENTARY_STAGING_NOT_PIT_GATE",
                    "performance_evidence": False, "input_inventory": args.inventory.as_posix(),
                    "input_inventory_sha256": hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
                    "evidence_sources": sources, "inventory_count": len(reconciled), "candidate_count": len(candidates),
                    "inventory_path": inventory_path.name, "candidates_path": candidate_path.name,
                    "inventory_sha256": write_immutable(inventory_path, reconciled),
                    "candidates_sha256": write_immutable(candidate_path, candidates)}
        write_immutable(args.output / ("documentary_manifest_v" + str(args.revision) + ".json"), manifest)
        print(json.dumps({"status": manifest["status"], "candidate_count": len(candidates), "candidates_path": str(candidate_path)}))
        return
    adapter = BaoStockAdapter(args.output, sdk_path=args.sdk_path, timeout=30, min_interval=1, max_retries=1)
    # BaoStock anonymous login/logout is not safely independent across
    # concurrent clients. One repository-wide exclusive session collector.
    lock = Path(__file__).resolve().parents[1] / "data" / ".baostock_collection.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        parser.error("Another BaoStock collector holds data/.baostock_collection.lock; do not run anonymous sessions concurrently")
    with os.fdopen(lock_fd, "w") as stream:
        stream.write(str(os.getpid()))
    try:
        run(args, adapter)
    finally:
        lock.unlink()


def run(args, adapter):
    if args.stage in {"inventory", "all"}:
        candidates = collect_inventory(adapter, args.sdk_path, args.repair_failed, args.revision)
    else:
        candidates = json.loads((args.candidates or args.output / "candidates.json").read_text(encoding="utf-8"))
    if args.stage in {"histories", "all"}:
        # Core groups first is operational ordering, never performance ranking.
        candidates = sorted(candidates, key=lambda x: (x.get("category") not in {"CSI300", "CSI500", "CSI1000", "CHINEXT", "STAR50"}, x["code"]))
        results = []
        for row in candidates:
            result, _ = cached_collect(adapter, Query("history", code=row["code"], start="2010-01-01", end="2024-12-31"), args.repair_failed)
            results.append(result)
        name = "histories_" + hashlib.sha256(canonical([x["code"] for x in candidates])).hexdigest()[:12] + "_v" + str(args.revision) + ".json"
        write_immutable(adapter.output_dir / name, {"status": "STAGING_ONLY", "performance_evidence": False,
                                                  "query_results": results, "candidate_count": len(candidates),
                                                  "candidate_source_path": str(args.candidates) if args.candidates else None,
                                                  "candidate_source_sha256": hashlib.sha256(args.candidates.read_bytes()).hexdigest() if args.candidates else None})
    print(json.dumps({"status": "DISCOVERY_NOT_DATASET_GATE", "output": str(adapter.output_dir), "candidate_count": len(candidates)}), flush=True)


if __name__ == "__main__":
    main()
