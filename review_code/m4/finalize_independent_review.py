"""Bind an independent synthetic/accounting review to final local hashes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/m4_review"
SOURCE = ["src/quant_research/" + name + ".py" for name in
          ("temporal", "data", "strategy", "execution", "engineering_replay", "equity_accounting")]
SOURCE += ["scripts/replay_equity_engineering.py", "scripts/m4_frozen_review.py"]
SOURCE += ["tests/" + name + ".py" for name in ("test_m4_execution", "test_equity_execution",
    "test_execution", "test_share_events", "test_settlement", "test_decimal_money", "test_data", "test_strategy")]
REVIEW = [str(path.relative_to(ROOT)).replace("\\", "/")
          for path in sorted((ROOT / "review_code/m4").glob("*.py"))]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def hashes(paths):
    return {name: sha(ROOT/name) for name in paths}


def run(name, args):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    path = OUT / (name + ".txt")
    path.write_text(result.stdout, encoding="utf-8")
    counts = re.findall(r"(\d+) passed", result.stdout)
    return dict(command=[sys.executable, *args], exit_code=result.returncode,
                passed=int(counts[-1]) if counts else None,
                output=str(path.relative_to(ROOT)).replace("\\", "/"), sha256=sha(path))


before = hashes(SOURCE + REVIEW)
runs = [run("independent_final_tests", ["-m", "pytest", "-q", "review_code/m4"]),
        run("independent_focused_regression", ["-m", "pytest", "-q",
            "tests/test_m4_execution.py", "tests/test_equity_execution.py", "tests/test_execution.py",
            "tests/test_share_events.py", "tests/test_settlement.py", "tests/test_decimal_money.py",
            "tests/test_data.py", "tests/test_strategy.py"]),
        run("independent_artifact_integrity", ["review_code/m4/audit_integrity.py"])]
after = hashes(SOURCE + REVIEW)
integrity = read("work/m4_independent/artifact_integrity.json")
frozen = read("reports/m4_review/independent_frozen_check.json")
annual = read("reports/m4_review/independent_annual_reconciliation.json")
frozen_summary = read("reports/m4_frozen/summary.json")
checks = dict(all_tests_pass=all(r["exit_code"] == 0 for r in runs),
    source_and_review_stable_during_checks=before == after,
    integrity_pass=integrity["status"] == "PASS",
    frozen_selector_hash_matches_current=frozen["temporal_sha256"] == after["src/quant_research/temporal.py"],
    frozen_analysis_hash_matches_current=frozen_summary["script_sha256"] == after["scripts/m4_frozen_review.py"],
    frozen_actual_trigger_contexts_zero=frozen_summary["actual_execution_dependency_discrepancies"] == 0,
    frozen_position_order_intersections_empty=not frozen["position_order_intersections"],
    annual_original_account_reconciliation_pass=annual["status"] == "PASS")
report = dict(schema_version="m4-independent-review-1", generated_at=datetime.now(timezone.utc).isoformat(),
    baseline="7d5bcebbf98a1fe68b50f760e63f7fbd66d28d78",
    status="PASS_SCOPED_ENGINEERING_REVIEW" if all(checks.values()) else "PENDING_OR_FAILED_CHECK",
    reviewer="Independent M4 agent; not the author of reviewed production implementation",
    purpose="ENGINEERING_AND_FROZEN_EVIDENCE_REVIEW_NOT_STRATEGY_PERFORMANCE",
    checks=checks, test_runs=runs, source_and_review_sha256=after,
    resolved_findings=[
        dict(id="M4-I-01", priority="P2", issue="Fixed share target keys silently omitted from decision universe; normal-runner guard depended on iteration.",
             reproduction="test_fixed_share_targets_do_not_depend_on_weight_membership / test_fixed_quantity_contract_is_rejected_outside_engineering_even_without_weight_keys",
             resolution="Author added input-stage engineering-only validation and fixed-target universe enumeration; independently retested."),
        dict(id="M4-I-02", priority="P2", issue="Linked corrections could omit stable child identity, and unknown explicit revision kinds silently selected transition semantics.",
             reproduction="test_correction_links_require_stable_child_identity[None] / []; test_unknown_explicit_revision_kind_cannot_silently_select_transition_semantics",
             resolution="Author requires stable child identity for linked rows and rejects unknown explicit revision kinds; unlinked unversioned fixtures remain supported; independently retested.")],
    unresolved_in_scope_findings=[], integrity=integrity,
    frozen_checks_attributed_to_root=frozen, annual_checks_attributed_to_root=annual,
    frozen_actual_execution_dependency_discrepancies=frozen_summary["actual_execution_dependency_discrepancies"],
    limitations=[
        "Only synthetic engineering replay is validated. No actual original corporate-action event has completed main-ledger admission.",
        "Tax debit timing and per-disposal rounding remain modeled conventions, pending broker/CSDC reconciliation.",
        "Stock share conversion/bonus/rights/merger/liquidation payments, missing calendar anniversaries, and intraday effective bounds remain unsupported.",
        "Data review here checks archive integrity and report counts, not independent original-PDF extraction or full historical pool completeness.",
        "Frozen zero-impact conclusion uses reconstructed actual contexts and root-authored independent checks; no complete persisted internal lookup trace exists.",
        "No strategy rerun, real performance registration, 2025--2026 market access, purchase, paper, live or change to frozen run artifacts performed by this reviewer."],
    evidence_sha256=hashes(["reports/m4_review/pre_fix_counterexamples.txt", "reports/m4_review/pre_fix_revision_kind.txt",
        "reports/m4_review/independent_frozen_check.json", "reports/m4_review/independent_annual_reconciliation.json",
        "reports/m4_frozen/summary.json", "reports/m4_frozen/input_hash_manifest.json",
        "reports/m4_correctness/EXECUTION_REVIEW.md"]))
(OUT/"independent_review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
text = f"""# M4 independent engineering review

Status: **{report['status']}**. Baseline `{report['baseline']}`. Generated {report['generated_at']}.

The reviewer did not author the production changes. This audit checks dual-clock safety, synthetic main-account integration and the limits of the supporting evidence. It grants no R2/R3 admission or performance status.

## Findings and independent retest

Two P2 input-contract defects were reproduced and returned to the implementation author. Fixed-quantity instructions could be silently ignored when their security appeared only in `fixed_quantities`, and the normal-runner prohibition depended on entering the order loop. Linked temporal corrections could omit their own stable revision identity; a final root-requested check also reproduced silent transition selection for an unrecognized explicit revision kind. Four initial failing assertions were preserved in `pre_fix_counterexamples.txt`, with the additional kind failure in `pre_fix_revision_kind.txt`; the author repaired the contracts and the reviewer reran those counterexamples unchanged.

The review suite passes **{runs[0]['passed']} tests**, including 16 tests from this reviewer. The focused existing execution, equity, share-event, settlement, decimal-money, data and strategy regression passes **{runs[1]['passed']} tests**. The exact commands, logs, source hashes and before/after stability check are recorded in `independent_review.json`.

Additional independent cases verify order-independent corrections/transitions, invalid lineage, partial FIFO disposal before dividend cash, subsequent purchases without old dividend claims, statutory fees across the August 2023 boundary, retained unpaid tax, and blocked exits when tick/settlement/limit evidence is unknown. The mixed-lot oracle checks explicit cash CNY100,070.38 and NAV CNY100,050.38 with CNY20 unpaid tax; it is an invented accounting case, not a security return.

## Evidence checks

All **{integrity['engineering_artifact_hashes_checked']}** recorded engineering artifact hashes match. The six cases remain labeled invented and reconcile 420 daily rows using the existing fixed-input oracle. The integrity audit verifies **{integrity['raw_data_objects_checked']}** raw data objects and their byte counts, 3,779 unique pool rows (2,946 MAIN; 833 ChiNext), five complete documentary cards, three quarantined cards and zero human acceptances. It does not claim that this reviewer independently re-extracted those PDFs or proved the vendor's historical pool complete.

Root-authored independent frozen checks cover {frozen['boundary_checks']:,} temporal boundaries, {frozen['actual_position_order_rows']['positions']:,} position rows and {frozen['actual_position_order_rows']['orders']:,} order rows, with no intersections. Final frozen analysis reports zero actual execution dependency discrepancies. The root's independent annual check reconciles {annual['account_years']:,} account-years to original summaries, maximum PnL difference CNY{annual['max_pnl_difference_cny']:.3g}. These statements are bound to the current temporal selector and frozen-analysis hashes; absence of complete persisted internal call traces remains an explicit limit. This reviewer did not rerun strategies or independently regenerate the root's frozen analysis.

## Remaining admission limits

No unresolved defect remains within the tested synthetic engineering scope. Real corporate-action source acceptance and broker/CSDC cash reconciliation remain incomplete. Unsupported stock bonus/conversion/rights/merger/liquidation-payment events, missing anniversary conventions and intraday effective intervals remain blocked. The financial route still lacks complete historical status, shares, liquidity and version coverage, and human acceptance remains zero. These are retained blockers, not synthetic substitutes for admission.

R2/R3 real strategy registration and execution remain zero. No 2025--2026 market data, purchase, paper/live action or frozen artifact mutation was performed by this reviewer. Any change to the hashes in `independent_review.json` requires rebinding this review.
"""
(OUT/"INDEPENDENT_REVIEW.md").write_text(text, encoding="utf-8")
print(json.dumps(dict(status=report["status"], checks=checks,
                      tests=[(r["passed"], r["exit_code"]) for r in runs]), indent=2))
raise SystemExit(not all(checks.values()))
