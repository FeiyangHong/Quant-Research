"""Check retained failed-generation identities without analyzing old returns.

The source archive embeds metrics. This audit deliberately projects only run
identities, configurations, provenance hashes and terminal metadata. It never
summarizes, compares or selects using the embedded performance fields.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY = "reports/real_data_phase3/superseded_v1/invalidated_attempts.json"
ENGINE_REVIEW = "reports/real_data_phase3/execution_review_v1_failed.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load(path):
    return json.loads(Path(path).read_bytes())


def projected_attempt(row):
    return {"run_id": row["run_id"], "period": row["period"], "config": row["config"],
            "interpretation": row["interpretation"],
            "provenance": {key: row["provenance"][key] for key in ("config_hash", "data_hash", "source_hash")},
            "terminal_event": row["terminal_event"], "table_hashes": row["table_hashes"]}


def audit_history(root=ROOT):
    root = Path(root)
    original_path, review_path = root / HISTORY, root / ENGINE_REVIEW
    archive = load(original_path)
    review = load(review_path)
    attempts = [projected_attempt(row) for row in archive["attempts"]]
    require(archive["status"] == "INVALIDATED_ENGINE_RESULTS_NOT_ELIGIBLE_FOR_ALPHA", "v1 is not invalidated")
    require(all(archive[key] is False for key in
                ("data_changed", "holdout_opened", "old_outputs_overwritten", "strategy_parameters_changed")),
            "Invalidation changed data, holdout, outputs or strategy parameters")
    require(len(attempts) == 353 and len({row["run_id"] for row in attempts}) == 353, "Require all353 unique v1 attempts")
    require(Counter(row["terminal_event"]["event"] for row in attempts) == Counter({"COMPLETED": 352, "FAILED": 1}),
            "v1 attempt outcome count differs")
    require(review["status"] == "FAILED_ENGINE_FEE_ROUNDING" and review["numerical_finding_count"] == 63,
            "Missing independent engineering failure")
    require(review["finding_counts"] == {"DECIMAL_COMMISSION_ROUNDING": 46, "DECIMAL_NOTIONAL_ROUNDING": 6,
                                        "DECIMAL_SLIPPAGE_AMOUNT_ROUNDING": 11}, "Engineering finding inventory differs")
    old_plan_path = root / "reports/real_data_phase3/registered_plan.json"
    old_plan = load(old_plan_path)
    registered_configs = {row["config_hash"]: row["config"] for row in old_plan["trials"]}
    require(archive["original_source_hash"] == old_plan["source_hash"], "Invalidation source differs from v1 registration")
    evidence = {HISTORY: sha(original_path), ENGINE_REVIEW: sha(review_path),
                old_plan_path.relative_to(root).as_posix(): sha(old_plan_path)}
    periods = {}
    preserved_hashes = {}
    completed_table_files = 0
    for period, expected in (("development", {"REGISTERED": 224, "COMPLETED": 224}),
                             ("validation", {"REGISTERED": 129, "COMPLETED": 128, "FAILED": 1})):
        archived_path = root / "reports/real_data_phase3/superseded_v1" / (period + "_trial_registry.jsonl")
        current_path = root / "runs" / ("real_r1_" + period + "_v1") / "trial_registry.jsonl"
        archived_bytes, current_bytes = archived_path.read_bytes(), current_path.read_bytes()
        require(sha(archived_path) == archive["periods"][period]["registry_sha256"], "Archived registry hash differs")
        require(current_bytes.startswith(archived_bytes), "v1 root registry was rewritten instead of appended")
        records = [json.loads(line) for line in archived_bytes.splitlines() if line.strip()]
        counts = Counter(row["event"] for row in records)
        expected_counts = Counter(expected)
        require(counts in (expected_counts, expected_counts + Counter({"MATRIX_INVALIDATED": 1})),
                "Archived terminal counts differ")
        registered, terminals = {}, {}
        for record in records:
            if record["event"] == "MATRIX_INVALIDATED":
                continue
            identity = record["run_id"]
            if record["event"] == "REGISTERED":
                require(identity not in registered, "Duplicate v1 registration")
                registered[identity] = record
            else:
                require(identity in registered and identity not in terminals, "Invalid v1 terminal chronology")
                terminals[identity] = record
        require(set(registered) == set(terminals), "Unclosed archived v1 attempt")
        extra = [json.loads(line) for line in current_bytes[len(archived_bytes):].splitlines() if line.strip()]
        current_records = records + extra
        require(Counter(row["event"] for row in current_records) == expected_counts + Counter({"MATRIX_INVALIDATED": 1})
                and current_records[-1]["event"] == "MATRIX_INVALIDATED",
                "Root registry lacks unique final invalidation marker")
        require(not extra if counts["MATRIX_INVALIDATED"] else len(extra) == 1,
                "Unexpected changes after archived registry")
        rows = [row for row in attempts if row["period"] == period]
        require({row["run_id"] for row in rows} == set(registered), "v1 attempt archive omits a registry identity")
        for row in rows:
            identity, provenance = row["run_id"], row["provenance"]
            require(row["interpretation"] == "INVALIDATED_DO_NOT_INTERPRET_AS_RESEARCH_EVIDENCE", "Attempt not marked ineligible")
            require(digest(row["config"]) == provenance["config_hash"], "Invalidated configuration hash differs")
            require(registered_configs.get(provenance["config_hash"]) == row["config"], "Unregistered v1 configuration")
            require(registered[identity]["config"] == row["config"], "Registry/config mismatch")
            require(all(registered[identity][key] == provenance[key] for key in provenance), "Registry provenance mismatch")
            require(provenance["source_hash"] == archive["original_source_hash"], "Untracked v1 source generation")
            archived_terminal = row["terminal_event"]
            actual_terminal = terminals[identity]
            require(all(actual_terminal.get(key) == value for key, value in archived_terminal.items()),
                    "Archived terminal event differs")
            missing_terminal_fields = set(actual_terminal) - set(archived_terminal)
            require(not missing_terminal_fields or (actual_terminal["event"] == "FAILED"
                    and missing_terminal_fields == {"recorded_at"}), "Archived terminal omits material fields")
            directory = root / "runs" / ("real_r1_" + period + "_v1") / identity
            require(directory.is_dir(), "Invalidated run directory is missing")
            require(load(directory / "config.json") == row["config"], "Preserved v1 config was changed")
            actual_provenance = load(directory / "provenance.json")
            require(all(actual_provenance[key] == value for key, value in provenance.items()),
                    "Preserved v1 provenance was changed")
            for filename in ("config.json", "provenance.json"):
                path = directory / filename
                preserved_hashes[path.relative_to(root).as_posix()] = sha(path)
            if terminals[identity]["event"] == "COMPLETED":
                require(row["table_hashes"] == terminals[identity]["table_hashes"], "Completed table identities differ")
                require(load(directory / "table_hashes.json") == row["table_hashes"], "Preserved table manifest changed")
                for name, expected_hash in row["table_hashes"].items():
                    require(name.replace("_", "").isalpha(), "Invalid retained table name")
                    path = directory / (name + ".json")
                    require(sha(path) == expected_hash, "Invalidated output table was removed or overwritten")
                    preserved_hashes[path.relative_to(root).as_posix()] = expected_hash
                    completed_table_files += 1
            else:
                failure_path = directory / "failure.json"
                failure = load(failure_path)
                require(all(actual_terminal.get(key) == value for key, value in failure.items()),
                        "Preserved aborted-attempt failure record changed")
                preserved_hashes[failure_path.relative_to(root).as_posix()] = sha(failure_path)
        for path in (archived_path, current_path):
            evidence[path.relative_to(root).as_posix()] = sha(path)
        periods[period] = {"registered": len(registered), "terminal_counts": dict(Counter(r["event"] for r in terminals.values())),
                           "unique_final_invalidation_marker_verified": True,
                           "archive_includes_invalidation_marker": bool(counts["MATRIX_INVALIDATED"])}
    prior_inventory_path = root / "work/independent_inventory_development_review.json"
    if prior_inventory_path.exists():
        prior = load(prior_inventory_path)
        require(prior["status"] == "ALL_224_DEVELOPMENT_PASS", "Unexpected earlier inventory result")
        evidence[prior_inventory_path.relative_to(root).as_posix()] = sha(prior_inventory_path)
    result = {"schema_version": 1, "status": "SUPERSEDED_V1_HISTORY_COMPLETE_ENGINE_FAILED",
              "reviewer": "/root/independent_admission", "reviewed_at": datetime.now(timezone.utc).isoformat(),
              "attempts_retained": 353, "completed_but_invalidated": 352, "aborted_and_invalidated": 1,
              "expected_full_replacement_configurations": 448, "periods": periods,
              "preserved_completed_table_files_hash_verified": completed_table_files,
              "preserved_artifact_identity_hash_count": len(preserved_hashes),
              "preserved_artifact_inventory_sha256": digest(preserved_hashes),
              "engineering_finding_counts": review["finding_counts"], "evidence_files": evidence,
              "history_auditor_sha256": sha(__file__),
              "old_inventory_verdict_scope": "Earlier PASS applies only to funded sessions, units/share rounding and dividend entitlement/model dates. It does not override failed price/fee/notional/slippage arithmetic or make v1 returns usable.",
              "failed_terminal_timestamp_note": "The aborted attempt archive retains failure.json fields; its append-time recorded_at is supplied by the hash-bound registry. Other terminal fields must agree exactly.",
              "old_performance_fields_analyzed_or_used_for_selection": False,
              "incidental_display_disclosure": "A bounded initial structure read displayed the first invalidated attempt's embedded metrics. No configuration, endpoint or window choice was based on it; subsequent reads project identity/status/hash fields only.",
              "scope": "Local registry and failure-history completeness. No old-return comparison, statistical confirmation or new source admission."}
    digest(result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_history()
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "attempts_retained", "engineering_finding_counts")}))
