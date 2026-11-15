"""Invented artifact fixtures test engineering gates, never financial conclusions."""
from copy import deepcopy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation import nav_metrics
from quant_research.provenance import digest, write_json


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("real_evaluator", ROOT / "scripts/evaluate_real_runs.py")
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def config(period="development"):
    return {"live_enabled": False, "sample": period, "universe": "R1B", "variant": "E0",
            "initial_cash": 100000, "risk_scaling": False, "cost_multiplier": 1,
            "slippage_multiplier": 1, "execution_delay": 1, "cash_delay_sessions": 0,
            "signal_release_delay": 1, "annual_incremental_cost": None,
            "primary_capital_confirmed": True, "seed": 20261114}


def grid(period="development"):
    entries = []
    for i, (capital, variant, scaling, path) in enumerate(itertools.product(ev.CAPITALS, ev.VARIANTS, (False, True), ev.PATHS)):
        c = dict(config(period), initial_cash=capital, variant=variant, risk_scaling=scaling,
                 cost_multiplier=path[0], slippage_multiplier=path[1],
                 execution_delay=path[2], cash_delay_sessions=path[3])
        entries.append({"config": c, "directory": "engineering_fixture_" + str(i), "metrics": {}})
    return entries


def save_registry(root, records):
    (root / "trial_registry.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


@pytest.fixture
def artifact(tmp_path):
    c = config()
    source = b"# INVENTED ENGINEERING FIXTURE ONLY\n"
    source_files = {"src/engineering_fixture.py": hashlib.sha256(source).hexdigest()}
    identity = {"config_hash": digest(c), "data_hash": "d" * 64, "source_hash": digest(source_files)}
    run_id = digest(identity)[:16] + "-20261115T000000Z"
    directory = tmp_path / run_id
    (directory / "source_snapshot/src").mkdir(parents=True)
    (directory / "source_snapshot/src/engineering_fixture.py").write_bytes(source)
    provenance = dict(identity, run_id=run_id, source_files=source_files, git_commit="engineering_fixture_only")
    write_json(directory / "config.json", c)
    write_json(directory / "provenance.json", provenance)
    write_json(directory / "data_audit.json", {"status": "PASSED", "performance_evidence": True,
                                               "errors": [], "blockers": [], "fixture": "INVENTED_TEST_ONLY"})
    dates = [f"{year}-01-04" for year in range(2016, 2022)]
    nav, positions = [], []
    for i, day in enumerate(dates):
        value = 1000. + i * 10
        nav.append({"date": day, "nav": 98995. + value, "cash_total": 98995., "cash_available": 98995.,
                    "cash_withdrawable": 98995., "cash_reserved": 0., "holdings_value": value, "receivables": 0.})
        positions.append({"date": day, "instrument_id": "INVENTED_ETF", "quantity": 100,
                          "price": value / 100, "market_value": value})
    fills = [{"date": dates[0], "order_id": "engineering_buy", "instrument_id": "INVENTED_ETF",
              "side": "BUY", "quantity": 100, "price": 10., "notional": 1000., "fees": 5.,
              "commission": 5., "stamp_duty": 0., "transfer_fee": 0., "slippage_cost": 0.}]
    tables = {name: [] for name in ev.REQUIRED_TABLES}
    tables.update(nav=nav, positions=positions, fills=fills,
                  costs=[{"date": dates[0], "total_cost": 5.}],
                  cash_events=[{"date": dates[0], "event": "BUY", "amount": -1005.}],
                  share_events=[{"date": "2015-04-14", "event": "PRE_ACCOUNT_METADATA_ONLY"}])
    for name, rows in tables.items():
        write_json(directory / (name + ".json"), rows)
    hashes = {name: ev.sha256(directory / (name + ".json")) for name in tables}
    metrics = dict(nav_metrics(pd.DataFrame(nav), c["initial_cash"]), run_id=run_id,
                   status="DAILY_SCREEN_ONLY", economic_confirmation="BLOCKED_HURDLE")
    write_json(directory / "metrics.json", metrics)
    write_json(directory / "table_hashes.json", hashes)
    write_json(directory / "decisions.json", [])
    write_json(directory / "execution_assumptions.json", {"fixture": "INVENTED_TEST_ONLY"})
    entry = {"config": c, "metrics": metrics, "directory": run_id}
    registered = dict(identity, run_id=run_id, config=c, event="REGISTERED")
    completed = {"run_id": run_id, "event": "COMPLETED", "status": "DAILY_SCREEN_ONLY", "table_hashes": hashes}
    save_registry(tmp_path, [registered, completed])
    return directory, entry, registered, completed


def verify(artifact):
    return ev.verify_run(*artifact, period="development")


def rebind_table(artifact, name, rows):
    directory, _, _, completed = artifact
    write_json(directory / (name + ".json"), rows)
    hashes = ev.read_json(directory / "table_hashes.json")
    hashes[name] = ev.sha256(directory / (name + ".json"))
    write_json(directory / "table_hashes.json", hashes)
    completed["table_hashes"] = hashes


def test_complete_grid_and_incomplete_duplicate_refusal():
    entries = grid()
    assert len(ev.validate_grid(entries, "development")) == 224
    with pytest.raises(ValueError, match="224 unique"):
        ev.validate_grid(entries[:-1], "development")
    entries[-1] = deepcopy(entries[0])
    with pytest.raises(ValueError, match="224 unique"):
        ev.validate_grid(entries, "development")


@pytest.mark.parametrize("field,value", [("sample", "final_holdout"), ("signal_release_delay", 0),
                                        ("annual_incremental_cost", 0), ("risk_scaling", "false")])
def test_frozen_contract_refuses_unsupported_settings(field, value):
    entries = grid()
    entries[0]["config"][field] = value
    with pytest.raises(ValueError):
        ev.validate_grid(entries, "development")


def test_reconciles_real_account_tables_without_pre_nav_share_metadata(artifact):
    row, returns, _ = verify(artifact)
    assert row["ledger_reconciliation"]["status"] == "PASS"
    assert row["fees_cny"] == 5
    assert returns.iloc[0] == pytest.approx(-5 / 100000)
    assert row["maximum_single_instrument_weight"] == pytest.approx(1050 / 100045)
    assert sum(y["additive_return_contribution_initial_capital"] for y in row["year_contributions"]) == pytest.approx(.00045)
    assert np.prod([1 + y["year_return"] for y in row["year_contributions"]]) - 1 == pytest.approx(.00045)


def test_altered_table_fails_bound_hash(artifact):
    (artifact[0] / "nav.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Table hash mismatch"):
        verify(artifact)


def test_altered_source_snapshot_fails_hash(artifact):
    (artifact[0] / "source_snapshot/src/engineering_fixture.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Source snapshot hash mismatch"):
        verify(artifact)


def test_consistently_rehashed_but_wrong_cash_ledger_is_rejected(artifact):
    rows = ev.read_json(artifact[0] / "cash_events.json")
    rows[0]["amount"] = -999.
    rebind_table(artifact, "cash_events", rows)
    with pytest.raises(ValueError, match="Ledger reconciliation failed"):
        verify(artifact)


def test_metric_cannot_disagree_with_nav_even_when_manifest_matches(artifact):
    metrics = artifact[1]["metrics"]
    metrics["cagr"] = .3
    write_json(artifact[0] / "metrics.json", metrics)
    with pytest.raises(ValueError, match="NAV metric mismatch: cagr"):
        verify(artifact)


def test_synthetic_or_blocked_artifacts_cannot_enter_real_evaluation(artifact):
    write_json(artifact[0] / "data_audit.json", {"status": "SYNTHETIC_ONLY", "performance_evidence": False})
    with pytest.raises(ValueError, match="real-data admission"):
        verify(artifact)


def test_registry_retains_failed_attempt_and_exact_config_later_completion(artifact):
    directory, entry, registered, completed = artifact
    old_id = directory.name.replace("000000", "000001")
    failed_dir = directory.parent / old_id
    shutil.copytree(directory, failed_dir)
    old_provenance = ev.read_json(failed_dir / "provenance.json")
    old_provenance["run_id"] = old_id
    write_json(failed_dir / "provenance.json", old_provenance)
    failed_registration = dict(registered, run_id=old_id)
    failure = {"run_id": old_id, "event": "FAILED", "error": "ValueError", "reason": "invented engineering failure"}
    write_json(failed_dir / "failure.json", failure)
    save_registry(directory.parent, [failed_registration, failure, registered, completed])
    _, _, audit = ev.audit_registry(directory.parent, [entry])
    assert audit["registered_attempts"] == 2
    assert audit["failed_attempts"] == 1
    assert audit["failures"][0]["failure"]["reason"] == failure["reason"]
    assert audit["failures"][0]["later_same_config_completed_runs"] == [directory.name]
    assert audit["failures"][0]["artifact_hashes"]["failure.json"] == ev.sha256(failed_dir / "failure.json")


def test_registry_refuses_pending_or_unlisted_completion(artifact):
    directory, entry, registered, completed = artifact
    save_registry(directory.parent, [registered])
    with pytest.raises(ValueError, match="Pending registered"):
        ev.audit_registry(directory.parent, [entry])
    save_registry(directory.parent, [registered, completed])
    with pytest.raises(ValueError, match="registry attempts and matrix manifest"):
        ev.audit_registry(directory.parent, [])


def test_zero_hurdle_is_separate_exploratory_and_never_formal_confirmation():
    rng = np.random.default_rng(25)
    candidate = pd.Series(rng.normal(0, .002, 300), index=pd.bdate_range("2022-01-03", periods=300))
    result = ev.inference_for_pair(candidate, candidate * 0)
    assert result["formal"]["status"] == "BLOCKED_HURDLE"
    assert result["formal"]["p_net"] is None
    # M7 separates descriptive uncertainty from the still-unknown fixed fee.
    assert result["formal"]["descriptive_status"] == "DESCRIPTIVE_INFERENCE"
    assert result["formal"]["economic_status"] == "BLOCKED_HURDLE"
    assert result["formal"]["daily_hurdle"] is None
    diagnostic = result["exploratory_zero_hurdle"]
    assert diagnostic["status"] == "EXPLORATORY_ZERO_INCREMENTAL_COST_ASSUMPTION"
    assert diagnostic["annual_incremental_cost_assumed_cny"] == 0
    assert diagnostic["multiplicity_confirmed"] is False
    assert diagnostic["factor_alpha"] is False
    assert [r["block_length"] for r in diagnostic["blocks"]] == [60, 20, 120]
    assert all(r["repetitions"] == 5000 for r in diagnostic["blocks"])
    assert all(r["status"] == "DESCRIPTIVE_INFERENCE" for r in diagnostic["blocks"])
    assert result["formal"]["ci95"] == diagnostic["blocks"][0]["ci95"]


def test_incomplete_matrix_writes_no_provisional_results(tmp_path):
    development, validation, output = (tmp_path / name for name in ("development", "validation", "output"))
    write_json(development / "matrix_summary.json", grid()[:-1])
    validation.mkdir()
    with pytest.raises(ValueError, match="224 unique"):
        ev.evaluate(development, validation, output)
    assert not output.exists()


@pytest.mark.parametrize("changed_core", [None, "src/quant_research/evaluation.py", "src/quant_research/provenance.py"])
def test_complete_orchestration_preserves_all_scenarios_and_not_ready_families(artifact, tmp_path, monkeypatch, changed_core):
    """Mocked run verification tests report wiring only, not real-data admission."""
    sample, _, _ = verify(artifact)
    development, validation, output = (tmp_path / name for name in ("dev_matrix", "val_matrix", "report"))
    for period, root in (("development", development), ("validation", validation)):
        write_json(root / "matrix_summary.json", grid(period))
    def registry(root, entries):
        identities = {r["directory"]: {} for r in entries}
        return identities, identities, {"status": "MOCKED_ENGINEERING_ONLY", "failed_attempts": 0,
                                        "completed_attempts": 224, "failures": []}
    sources = {relative: ev.sha256(ROOT / relative) for relative in
               ("scripts/evaluate_real_runs.py", "scripts/summarize_runs.py",
                "src/quant_research/evaluation.py", "src/quant_research/provenance.py")}
    # A separately versioned report repair is allowed; changing the frozen
    # inference or identity definitions is not.
    for relative in ("scripts/evaluate_real_runs.py", "scripts/summarize_runs.py"):
        sources[relative] = "0" * 64
    if changed_core:
        sources[changed_core] = "0" * 64
    def run(directory, entry, registered, completed, period):
        row = deepcopy(sample)
        row.update(period=period, config=entry["config"], directory=directory.name,
                   path=ev.PATHS[ev.config_key(entry["config"])[3:]])
        first, last = ev.PERIODS[period]
        dates = pd.Index([f"{year}-01-04" for year in range(first, last + 1)])
        row["year_contributions"] = [dict(sample["year_contributions"][0], year=year) for year in range(first, last + 1)]
        row["account_dates_sha256"] = digest(dates.tolist())
        row["provenance"]["source_hash"] = digest(sources)
        return row, pd.Series(0., index=dates), sources
    monkeypatch.setattr(ev, "audit_registry", registry)
    monkeypatch.setattr(ev, "verify_run", run)
    if changed_core:
        with pytest.raises(ValueError, match="Evaluator source differs from run snapshot"):
            ev.evaluate(development, validation, output)
        assert not output.exists()
        return
    report = ev.evaluate(development, validation, output)
    assert report["run_count"] == 448
    assert len(report["paired_effects"]) == 224
    assert len(report["stress_effects"]) == 384
    assert len(report["capital_effects"]) == 336
    assert report["formal_holm_placeholders"] == {"R1": 1., "R2": 1., "R3": 1., "R4": 1.}
    assert report["formal_four_families"]["R1"]["reasons"] == ["HURDLE_UNKNOWN", "PRIMARY_FINAL_CANDIDATE_UNFROZEN"]
    assert report["annual_incremental_cost_cny"] is None
    assert report["final_holdout_accessed"] is False
    assert report["factor_alpha"] is None
    assert len([r for r in report["paired_effects"] if "formal" in r["uncertainty"]]) == 8
    assert (output / "RESULTS.md").is_file()
    assert ev.read_json(output / "results_summary.json")["run_count"] == 448
