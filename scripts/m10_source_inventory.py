"""Offline M10 source inventory; no collectors, strategy calls or secret discovery.

Reads only explicit project code/configuration and the frozen M3--M6 evidence
index below. Raw payloads are hashed, never decoded or copied to the output.
Only literal environment names declared in project Python are checked, and
only presence is reported. This is an inventory, not a new data-admission gate.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path


EVIDENCE = (
    "reports/m3_equity_admission/source_manifest.json",
    "reports/m3_equity_admission/revision_candidate_queue.json",
    "reports/m3_equity_admission/DATA_AUDIT.md",
    "reports/m4_data/source_manifest.json",
    "reports/m4_data/coverage_summary.json",
    "reports/m4_data/financial_vintage_cases.json",
    "reports/m4_data/normalized_events.json",
    "reports/m5_financial/manifest.json",
    "reports/m5_financial/collection_manifest.json",
    "reports/m5_financial/canonical_facts.json",
    "reports/m5_financial/report_coverage.json",
    "reports/m5_market_cap/source_manifest.json",
    "reports/m5_market_cap/coverage_summary.json",
    "reports/m6_stock_source/request_manifest.json",
    "reports/m6_stock_source/source_contract_decision.json",
    "reports/m6_stock_source/batch_observations.json",
    "reports/m6_stock_source/fixed_denominator_coverage.json",
    "reports/m6_stock_execution/local_evidence_index.json",
    "reports/m6_stock_execution/results.json",
)
PROVIDERS = {
    "baostock": "src/quant_research/providers/equity_audit.py",
    "eastmoney_historical_shares": "scripts/m6_stock_source.py",
    "official_documents": "scripts/m5_sources.py",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def literal_environment_names(path):
    """Recognize explicit os.getenv / os.environ literals; do not import code."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = set()
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call):
            label = ast.unparse(node.func)
            if label in {"os.getenv", "os.environ.get", "os.environ.setdefault"} and node.args:
                key = node.args[0]
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
    return names


def references(value):
    if isinstance(value, dict):
        path = next((value.get(k) for k in ("raw_path", "path", "local_raw_path", "source_document_path") if value.get(k)), None)
        sha = value.get("sha256") or value.get("source_document_hash")
        if path and sha:
            yield str(path), sha
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def source_path(root, supplied):
    path = Path(supplied)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Evidence path is outside the explicitly supplied archive")
    relative = resolved.relative_to(root).as_posix()
    explicit_reused_dependencies = {"scripts/m4_data_feasibility.py", "scripts/m4_data_build.py", "data/admitted_r1/phase2_v1/development/calendar.json"}
    if not relative.startswith(("data/raw_equity_admission/", "data/raw_m4_equity/", "data/raw_m5_equity/", "data/raw_m6/", "reports/")) and relative not in explicit_reused_dependencies:
        raise ValueError("Evidence path is outside the named M3--M6 evidence scopes")
    return resolved, relative


def build(root):
    root = root.resolve()
    evidence = {name: json_read(root / name) for name in EVIDENCE if name.endswith(".json")}
    card_paths = sorted((root / "reports/m5_financial/human_review").glob("*.json"))
    cards = [json_read(path) for path in card_paths]
    source_metadata = [{"path": name, "sha256": digest(root / name), "bytes": (root / name).stat().st_size} for name in EVIDENCE]
    source_metadata += [{"path": path.relative_to(root).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size} for path in card_paths]

    configuration = sorted((root / "configs").glob("*.json")) + [root / "pyproject.toml"]
    inspected_code = sorted((root / "src").rglob("*.py")) + sorted((root / "scripts").glob("*.py"))
    env = sorted(set().union(*(literal_environment_names(path) for path in inspected_code)))
    all_refs = {}
    groups = []
    for name, value in evidence.items():
        rows = []
        for given, expected in references(value):
            path, relative = source_path(root, given)
            key = (relative, expected)
            if key not in all_refs:
                exists = path.is_file()
                actual = digest(path) if exists else None
                kind = "RAW_ARCHIVE" if relative.startswith("data/raw_") else "HISTORICAL_CODE" if relative.startswith("scripts/") else "REUSED_DERIVED_OR_CALENDAR"
                all_refs[key] = {"path": relative, "kind": kind, "expected_sha256": expected, "actual_sha256": actual,
                                 "bytes": path.stat().st_size if exists else None,
                                 "status": "MATCH" if actual == expected else "MISMATCH" if exists else "MISSING"}
            rows.append(key)
        groups.append({"evidence": name, "reference_occurrences": len(rows), "distinct_path_hash_pairs": len(set(rows)),
                       "matched_distinct_pairs": sum(all_refs[key]["status"] == "MATCH" for key in set(rows))})
    raw = sorted(all_refs.values(), key=lambda row: (row["path"], row["expected_sha256"]))
    coverage = evidence["reports/m4_data/coverage_summary.json"]
    financial = evidence["reports/m4_data/financial_vintage_cases.json"]
    facts = evidence["reports/m5_financial/canonical_facts.json"]
    batch = evidence["reports/m6_stock_source/batch_observations.json"]
    cap = evidence["reports/m6_stock_source/source_contract_decision.json"]
    observed = evidence["reports/m6_stock_source/fixed_denominator_coverage.json"]["rows"]
    return {
        "schema_version": "m10-local-source-inventory-1",
        "purpose": "REUSED_ARCHIVE_COUNTS_AND_HASHES_NOT_NEW_DATA_ADMISSION",
        "primary_status": "BLOCKED_DATA_CAPABILITY",
        "required_period": ["2016-01-01", "2024-12-31"],
        "complete_2016_2024_monthly_common_pools_verified": 0,
        "requested_monthly_anchors": 108,
        "coverage_denominator_warning": "3779 is the one-date provider main/ChiNext snapshot, not the 2016--2024 universe or a qualified universe.",
        "project_configuration": {
            "scopes": ["configs/*.json", "pyproject.toml", "src/**/*.py", "scripts/*.py"],
            "configuration_files": [{"path": path.relative_to(root).as_posix(), "sha256": digest(path)} for path in configuration],
            "inspected_python_file_count": len(inspected_code),
            "inspected_python_content_manifest_sha256": hashlib.sha256(json.dumps({path.relative_to(root).as_posix(): digest(path) for path in inspected_code}, sort_keys=True).encode()).hexdigest(),
            "declared_environment_presence": [{"name": name, "present": name in os.environ} for name in env],
            "environment_values_printed": False,
            "credential_directories_scanned": False,
            "implemented_source_entrypoints": [{"provider": name, "path": path, "sha256": digest(root / path)} for name, path in PROVIDERS.items()],
            "full_pit_subscription_or_export": "NOT_CONFIGURED_OR_VERIFIED_WITHIN_INSPECTED_PROJECT_SCOPE",
            "limitation": "No claim about accounts, exports or permissions outside the explicit project scope; literal Python environment declarations only.",
        },
        "snapshot_2020_07_31": {key: coverage[key] for key in ("snapshot_date", "all_security_response_rows", "all_A_daily_rows", "main_chinext_denominator", "boards", "vendor_st_counts", "trade_status_counts", "coverage", "nonST_size_percentile_denominator")},
        "financial_archive": {
            "m3_correction_pdf_candidates": len(evidence["reports/m3_equity_admission/revision_candidate_queue.json"]["cases"]),
            "attempted_issuer_period_cases": financial["attempted_issuer_period_cases"],
            "complete_documentary_pairs": financial["complete_documentary_pairs"],
            "quarantined_cases": financial["quarantined_cases"],
            "human_review_card_count": len(cards),
            "human_accepted": sum(card["human_accepted"] is True for card in cards),
            "human_signatures_present": sum(bool(card["human_review"]["signature"]) for card in cards),
            "required_human_accepted": 20,
            "canonical_field_version_rows": len(facts),
            "canonical_source_pdf_hashes": len({fact["source_document_hash"] for fact in facts}),
            "numerical_engineering_factor_cases": evidence["reports/m5_financial/manifest.json"]["case_count"],
            "partial_report_coverage_contracts": len(evidence["reports/m5_financial/report_coverage.json"]),
            "full_pool_version_chain": "UNKNOWN_NOT_ADMITTED",
            "freshness_policy": None,
        },
        "shares_archive": {
            "structural_document_crosschecks": 5,
            "broad_batch_event_rows": batch["all_page_rows"],
            "broad_batch_unique_ids": batch["all_page_unique_ids"],
            "fixed_snapshot_ids_observed_in_broad_batch": batch["fixed_pool_ids_observed"],
            "five_id_batch_event_rows": sum(case["event_rows"] for case in cap["route1_cases"]),
            "formal_pit_share_count_non_null": sum(row["formal_pit_share_count"] is not None for row in observed),
            "formal_market_cap_non_null": sum(row["formal_market_cap"] is not None for row in observed),
            "source_revision_chain_available": batch["revision_chain_available"],
            "historical_data_license_verified": batch["explicit_historical_data_license_verified"],
            "prior_full_provider_pagination_estimate": {"requests": cap["route1_full_pagination_requests"], "bytes": cap["route1_full_pagination_bytes_estimate"], "scope": cap["estimate_basis"], "new_requests_authorized": False},
        },
        "engineering_event_cases": [{key: case[key] for key in ("case", "status", "source_gate_passed", "daily_rows", "actual_fill_count", "has_actual_event_position", "missing_components", "broker_ledger_verification")} for case in evidence["reports/m6_stock_execution/results.json"]["cases"]],
        "evidence_files": source_metadata,
        "archive_reference_groups": groups,
        "archive_hash_check": {
            "distinct_path_hash_pairs": len(raw),
            "matched": sum(row["status"] == "MATCH" for row in raw),
            "missing": sum(row["status"] == "MISSING" for row in raw),
            "mismatched": sum(row["status"] == "MISMATCH" for row in raw),
            "raw_archive_objects": sum(row["kind"] == "RAW_ARCHIVE" for row in raw),
            "raw_archive_objects_matched": sum(row["kind"] == "RAW_ARCHIVE" and row["status"] == "MATCH" for row in raw),
            "historical_code_drift": [row["path"] for row in raw if row["kind"] == "HISTORICAL_CODE" and row["status"] != "MATCH"],
            "distinct_content_hashes": len({row["expected_sha256"] for row in raw}),
            "local_reused_bytes_by_distinct_path": sum({row["path"]: row["bytes"] or 0 for row in raw}.values()),
            "byte_semantics": "Existing local bytes read for hashes; not new source responses or network acquisition bytes.",
            "objects": raw,
        },
        "new_acquisition_by_this_inventory": {"external_requests": 0, "source_response_bytes": 0, "cash_spend": 0},
        "strategy_performance_run": False,
        "market_factor_strategy_holdout_opened": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.archive_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = result["archive_hash_check"]
    print(json.dumps({key: value for key, value in summary.items() if key != "objects"}))
    if any(row["status"] != "MATCH" and row["kind"] != "HISTORICAL_CODE" for row in summary["objects"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
