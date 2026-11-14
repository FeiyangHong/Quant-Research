"""Hash-bound independent admission and physically separated research samples."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .data import TABLES, EVIDENCE_GATES, DataValidationError, audit_dataset, load_dataset, save_dataset
from .dependencies import representative_dependencies
from .provenance import write_json


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_attestation(stage, attestation, repo):
    """A signed-off scope is data, not an automatic claim of source truth."""
    stage, attestation, repo = Path(stage), Path(attestation), Path(repo).resolve()
    review = json.loads(attestation.read_bytes())
    if review.get("schema_version") != 1 or review.get("decision") != "ADMIT_DAILY_SCREEN":
        raise DataValidationError("Independent daily-screen admission is required")
    if review.get("stage_manifest_sha256") != _sha(stage / "manifest.json"):
        raise DataValidationError("Reviewed staging snapshot differs")
    if not review.get("reviewer") or not review.get("reviewed_at") or not review.get("qualifications"):
        raise DataValidationError("Admission reviewer, date and scope limitations are required")
    gates = review.get("evidence_gates", {})
    if set(gates) != set(EVIDENCE_GATES):
        raise DataValidationError("Every registered evidence gate must be reviewed")
    for key, gate in gates.items():
        if (gate.get("status") != "VERIFIED" or not gate.get("reviewer")
                or not gate.get("reviewed_at") or not gate.get("evidence")):
            raise DataValidationError("Incomplete gate review: " + key)
    evidence = review.get("evidence_files", {})
    if not evidence:
        raise DataValidationError("Immutable admission evidence is required")
    for key, gate in gates.items():
        if any(ref not in evidence for ref in gate["evidence"]):
            raise DataValidationError("Gate evidence lacks a bound hash: " + key)
    for relative, expected in evidence.items():
        path = (repo / relative).resolve()
        try:
            path.relative_to(repo)
        except ValueError as exc:
            raise DataValidationError("Admission evidence escapes repository") from exc
        if not path.is_file() or _sha(path) != expected:
            raise DataValidationError("Admission evidence hash mismatch: " + relative)
    manifest = json.loads((stage / "manifest.json").read_bytes())
    for relative, expected in manifest["file_sha256"].items():
        path = (stage / relative).resolve()
        path.relative_to(stage.resolve())
        if _sha(path) != expected:
            raise DataValidationError("Staging file hash mismatch: " + relative)
    for relative, expected in manifest.get("source_snapshot_hashes", {}).items():
        path = (repo / relative).resolve()
        path.relative_to(repo)
        if _sha(path) != expected:
            raise DataValidationError("Primary source snapshot changed: " + relative)
    return review


def split_sample(dataset, sample):
    if sample not in ("development", "validation"):
        raise DataValidationError("Final holdout is locked")
    result = deepcopy(dataset)
    end = "2021-12-31" if sample == "development" else "2024-12-31"
    result.calendar = [d for d in result.calendar if d <= end]
    if not result.calendar or result.calendar[-1] >= "2025-01-01":
        raise DataValidationError("Invalid research sample calendar")
    # Original dated master revisions, not a current-membership slice. The
    # full admission evidence may describe later periods; no later prices or
    # realized corporate actions enter the development feature tables.
    result.instruments = result.instruments.loc[result.instruments.available_at.str[:10].le(end)].copy()
    identities = set(result.instruments.instrument_id)
    result.bars = result.bars.loc[result.bars.date.le(end) & result.bars.instrument_id.isin(identities)].copy()
    result.benchmark = result.benchmark.loc[result.benchmark.date.le(end)].copy()
    result.actions = result.actions.loc[result.actions.ex_date.le(end)
        & result.actions.instrument_id.isin(identities)].copy()
    result.manifest.update(dataset_id="real-r1b-" + sample, dataset_version="admitted-v1",
        sample=sample, coverage_start=result.calendar[0], coverage_end=result.calendar[-1],
        funded_account_start="2016-01-01" if sample == "development" else "2022-01-01",
        warmup_is_not_account_return=True)
    # A later action revision must never leave a broken lineage after slicing.
    # All actions included here are before the sample boundary; their own
    # availability remains enforced by both features and accounting.
    result.manifest["representative_dependencies"] = representative_dependencies(result)
    result.manifest["required_full_history_instruments"] = result.manifest["representative_dependencies"]["required_full_history_instruments"]
    result.manifest.pop("file_sha256", None)
    return result


def admit_samples(stage, attestation, output, repo):
    review = verify_attestation(stage, attestation, repo)
    dataset = load_dataset(stage, allow_unverified=True)
    if dataset.manifest.get("synthetic") is not False or dataset.manifest.get("build_blockers"):
        raise DataValidationError("Only an error-free real staging dataset can be admitted")
    if any(d >= "2025-01-01" for d in dataset.calendar):
        raise DataValidationError("Final holdout is locked")
    dataset.manifest.update(status="ADMITTED_DAILY_SCREEN", strategy_runs_permitted=True,
        calendar_kind="VERIFIED_EXCHANGE_CALENDAR", evidence_gates=review["evidence_gates"],
        admission_attestation=review, admission_attestation_sha256=_sha(attestation),
        admitted_stage_manifest_sha256=_sha(Path(stage) / "manifest.json"),
        performance_evidence_scope="CONDITIONAL_DAILY_SIMULATION_ONLY")
    for name in TABLES:
        if not getattr(dataset, name).quality_status.isin(["provisional", "accepted"]).all():
            raise DataValidationError("Quarantined or missing rows cannot be promoted: " + name)
        getattr(dataset, name).loc[:, "quality_status"] = "accepted"
    summaries = {}
    for sample in ("development", "validation"):
        split = split_sample(dataset, sample)
        report = audit_dataset(split)
        if report["status"] != "PASSED":
            raise DataValidationError("Admission audit failed: " + json.dumps(report))
        destination = Path(output) / sample
        save_dataset(split, destination)
        write_json(destination / "admission_audit.json", report)
        summaries[sample] = dict(path=str(destination), manifest_sha256=_sha(destination / "manifest.json"),
            sessions=len(split.calendar), bars=len(split.bars), actions=len(split.actions),
            first_session=split.calendar[0], last_session=split.calendar[-1], status=report["status"])
    write_json(Path(output) / "sample_manifest.json", summaries)
    return summaries
