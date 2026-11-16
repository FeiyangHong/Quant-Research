"""Read-only binding of the already admitted M8 originals for M9.

No collection, admission mutation, account execution, or source text export.
Run from the public checkout with --evidence-root pointing to the private M8
archive. The binding contains only identities, hashes, counts, and summaries.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_research.data import load_dataset, audit_dataset
from quant_research.liquid_cohort import LIQUID_SCOPE
from quant_research.liquid_runner import _verify_source_files
from quant_research.provenance import write_json
from quant_research.runner import dataset_hash

EXPERIMENT = "M9_ETF_RISK_BUDGET_V1"
COHORT = ["sh.512880", "sh.515000", "sh.512760", "sh.515880", "sh.512800",
          "sh.512710", "sh.512660", "sz.159939", "sh.512720", "sh.512290"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bind(evidence_root):
    evidence_root = Path(evidence_root).resolve()
    pointers = json.loads((ROOT / "reports/m8_public/LOCAL_AUDIT_POINTERS.json").read_bytes())
    source_hashes = {}
    datasets = {}
    formation_path = "reports/m8_rotation/COHORT_SELECTION.json"
    admission_path = "reports/m8_review/HOLDING_ADMISSION.json"
    event_path = "reports/m8_rotation/EVENT_MANIFEST.json"
    selection = json.loads((evidence_root / formation_path).read_bytes())
    events = json.loads((evidence_root / event_path).read_bytes())
    assert selection["selected_instruments"] == COHORT
    assert selection["status"] == "FORMED" and selection["scope"] == LIQUID_SCOPE
    assert selection["first_legal_signal_anchor"] == "2020-01-23"
    assert selection["formation_age_sessions"] == 60 and selection["trade_age_sessions"] == 252
    assert not selection["post2019_market_data_used"]
    assert not selection["future_survival_used"] and not selection["strategy_returns_inspected"]
    for sample, end in (("development", "2021-12-31"), ("validation", "2024-12-31")):
        relative = "data/m8_rotation/admitted_v1/" + sample
        directory = evidence_root / relative
        original_hashes = {p.name: sha(p) for p in sorted(directory.iterdir()) if p.is_file()}
        data = load_dataset(directory)
        m = data.manifest
        _verify_source_files(data, evidence_root)
        assert m["research_scope"] == LIQUID_SCOPE and m["synthetic"] is False
        assert m["cohort_selection_sha256"] == sha(evidence_root / formation_path)
        assert m["admission_attestation_sha256"] == sha(evidence_root / admission_path)
        assert m["admission_scope"] == "FULL_HOLDING_DEPENDENCIES"
        assert m["signal_release_delay"] == 1
        assert max(data.calendar) <= end and max(data.bars.date) <= end
        assert max(data.benchmark.date) <= end and max(data.actions.ex_date) <= end
        audit = audit_dataset(data)
        assert audit["status"] == "PASSED" and not audit["errors"] and not audit["blockers"]
        actual = dataset_hash(data)
        expected = {row["data_hash"] for row in pointers["accounts"] if row["period"] == sample}
        assert expected == {actual}, (sample, actual, expected)
        sources = dict(m["source_snapshot_hashes"])
        sources.update(m["admission_attestation"]["evidence_files"])
        for key, value in sources.items():
            if key in source_hashes:
                assert source_hashes[key] == value
            source_hashes[key] = value
        assert original_hashes == {p.name: sha(p) for p in directory.iterdir() if p.is_file()}
        datasets[sample] = dict(relative_path=relative, dataset_hash=actual,
            files=original_hashes, audit_status=audit["status"], sessions=len(data.calendar),
            bars=len(data.bars), actions=len(data.actions), first_session=min(data.calendar),
            last_session=max(data.calendar), funded_start="2020-01-01" if sample == "development" else "2022-01-01",
            source_snapshot_count=len(m["source_snapshot_hashes"]),
            admission_evidence_count=len(m["admission_attestation"]["evidence_files"]),
            raw_file_hashes_verified=True, source_evidence_verified=True,
            original_dataset_bytes_unchanged=True)
    for name in (formation_path, admission_path, event_path,
                 "reports/m8_review/FORMATION_INDEPENDENT_REVIEW.json",
                 "reports/m8_rotation/CANDIDATE_REVIEW.json",
                 "reports/m8_rotation/EXPERIMENT_REGISTRY.json",
                 "reports/m8_rotation/SOURCE_POLICY_ADDENDUM.md"):
        source_hashes[name] = sha(evidence_root / name)
    # Hash every exported pointer independently, including selection and event
    # records, and prohibit an original archive from redirecting outside itself.
    for relative, expected in source_hashes.items():
        path = (evidence_root / relative).resolve()
        path.relative_to(evidence_root)
        assert sha(path) == expected, relative
    formation = {k: selection[k] for k in ("formation_date", "cohort_available_at",
        "sampling_frame_sha256", "candidate_review_sha256", "formation_age_sessions",
        "trade_age_sessions", "selected_instruments", "counts", "first_legal_signal_anchor",
        "first_base_execution", "post2019_market_data_used", "future_survival_used", "strategy_returns_inspected")}
    formation.update(relative_path=formation_path, sha256=source_hashes[formation_path],
        candidate_count=len(selection["ETF_candidate_rows"]),
        non_etf_original_review_count=len(selection["non_ETF_original_reviews"]),
        qualified_count=sum(r["status"] == "QUALIFIED_INDEX_CANDIDATE" for r in selection["ETF_candidate_rows"]),
        deduplicated_index_representatives=len(selection["representative_ranking"]),
        formation_window_start=selection["formation_window"][0],
        formation_window_end=selection["formation_window"][-1],
        formation_window_sessions=len(selection["formation_window"]),
        candidate_summary=[{k: r[k] for k in ("instrument_id", "exact_index_id", "status")}
                           for r in selection["ETF_candidate_rows"]],
        representative_summary=[{k: r[k] for k in ("rank", "instrument_id", "exact_index_id", "selected")}
                                for r in selection["representative_ranking"]])
    event_summary = dict(relative_path=event_path, sha256=source_hashes[event_path],
        document_count=len(events["documents"]), fund_year_count=len(events["coverage"]),
        coverage_status_counts=dict(Counter(row["status"] for row in events["coverage"])),
        canonical_event_count=len(events["canonical_actions"]),
        event_type_counts=dict(Counter(row["type"] for row in events["canonical_actions"])),
        events=[{k: row.get(k) for k in ("action_id", "instrument_id", "type", "announcement_date",
            "available_at", "record_date", "ex_date", "source_sha256", "source_text_sha256", "source_path")}
                for row in events["canonical_actions"]],
        retrospective_coverage=[{k: row[k] for k in ("instrument_id", "year", "status",
            "report_publication_date", "role", "report_hashes")}
                for row in events["coverage"]],
        timing_rule="Retrospective completeness documents retain real publication dates; they are not earlier predictive inputs.")
    return dict(schema_version=1, experiment_id=EXPERIMENT, data_scope=LIQUID_SCOPE,
        claim_type="RISK_ALLOCATION_EXPLORATION", status="VERIFIED_REUSE_ONLY",
        verified_at=datetime.now(timezone.utc).isoformat(), evidence_root_mode="EXTERNAL_READ_ONLY",
        evidence_root_parameter="--evidence-root (local M8 archive; all paths below are relative)",
        new_market_requests=0, old_accounts_rerun=0, original_scope_or_manifest_modified=False,
        public_baseline="540fdf3a1946dfb12fe54698a22584446cbcf91a",
        original_m8=dict(formation=formation, events=event_summary,
            admission=dict(relative_path=admission_path, sha256=source_hashes[admission_path],
                decision="ADMIT_DAILY_SCREEN", scope="FULL_HOLDING_DEPENDENCIES")),
        datasets=datasets, original_file_sha256=dict(sorted(source_hashes.items())),
        original_file_count=len(source_hashes),
        public_scope="Hashes and non-price summaries only. Original raw prices, amounts, source text, and full ledgers remain external.",
        limitations=["Hash identity does not independently establish every underlying historical fact.",
            "Original admission is reused, not expanded; DAILY_SCREEN_ONLY remains in force.",
            "Public checkout cannot replay private source-dependent data admission without the original archive.",
            "Historical account permission is a research policy, not verified user brokerage permission."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/m9_risk/DATA_BINDING.json")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Binding already exists; do not rewrite frozen registration: " + str(args.output))
    result = bind(args.evidence_root)
    write_json(args.output, result)
    print(json.dumps(dict(status=result["status"], original_file_count=result["original_file_count"],
        binding_sha256=sha(args.output), datasets={k:v["dataset_hash"] for k,v in result["datasets"].items()})))


if __name__ == "__main__":
    main()
