"""End-to-end artifact and accounting checks using invented data only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_research.data import audit_dataset, load_dataset, save_dataset, synthetic_dataset
from quant_research.runner import run_experiment


REPO = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source_fixture():
    data = synthetic_dataset()
    # More than 252 sessions permits actual target construction and fills;
    # future corporate actions and revised metadata are outside this fixture.
    data.calendar = [day for day in data.calendar if day <= "2019-06-28"]
    data.bars = data.bars.loc[data.bars["date"].isin(data.calendar)].copy()
    data.benchmark = data.benchmark.loc[data.benchmark["date"].isin(data.calendar)].copy()
    data.actions = data.actions.iloc[:0].copy()
    data.instruments = data.instruments.loc[data.instruments["supersedes_id"].isna()].copy()
    data.manifest["coverage_end"] = data.calendar[-1]
    assert audit_dataset(data)["status"] == "SYNTHETIC_ONLY"
    return data


@pytest.fixture
def dataset(source_fixture):
    return deepcopy(source_fixture)


@pytest.fixture
def config():
    return read_json(REPO / "configs" / "r1b.json")


def events(root):
    return [json.loads(line) for line in (root / "trial_registry.jsonl").read_text(encoding="utf-8").splitlines()]


def assert_preserved_failure(root, fragment):
    records = events(root)
    assert [record["event"] for record in records] == ["REGISTERED", "FAILED"]
    assert records[0]["run_id"] == records[1]["run_id"]
    destination = root / records[0]["run_id"]
    assert fragment in read_json(destination / "failure.json")["reason"]
    assert (destination / "config.json").is_file()
    assert (destination / "provenance.json").is_file()
    assert not (destination / "nav.json").exists()
    assert not (root / ".runner.lock").exists()


def test_two_executions_produce_identical_tables_and_reconstructable_nav(dataset, config, tmp_path):
    first, metrics = run_experiment(dataset, config, tmp_path, REPO)
    second, repeat_metrics = run_experiment(dataset, config, tmp_path, REPO)
    assert first != second
    assert metrics["status"] == repeat_metrics["status"] == "SYNTHETIC_ENGINEERING_ONLY"
    assert metrics["economic_confirmation"] == "BLOCKED_HURDLE"
    assert read_json(first / "uncertainty.json")["status"] == "NOT_A_CONFIRMATORY_TEST"
    hashes = read_json(first / "table_hashes.json")
    assert hashes == read_json(second / "table_hashes.json")
    assert set(hashes) >= {"nav", "positions", "orders", "fills", "rejected_orders", "costs", "exposure", "cash_events"}
    for name, expected in hashes.items():
        assert hashlib.sha256((first / (name + ".json")).read_bytes()).hexdigest() == expected
    assert read_json(first / "decisions.json") == read_json(second / "decisions.json")
    assert [event["event"] for event in events(tmp_path)] == ["REGISTERED", "COMPLETED", "REGISTERED", "COMPLETED"]
    assert not (tmp_path / ".runner.lock").exists()
    provenance = read_json(first / "provenance.json")
    assert provenance["data_hash"] == read_json(second / "provenance.json")["data_hash"]
    for relative, expected in provenance["source_files"].items():
        assert hashlib.sha256((first / "source_snapshot" / relative).read_bytes()).hexdigest() == expected

    nav = pd.DataFrame(read_json(first / "nav.json")).set_index("date")
    cash = pd.DataFrame(read_json(first / "cash_events.json"))
    holdings = pd.DataFrame(read_json(first / "positions.json"))
    fills = pd.DataFrame(read_json(first / "fills.json"))
    assert not fills.empty and set(fills["side"]) == {"BUY", "SELL"}
    assert not holdings.empty and not cash.empty
    movements = cash.loc[cash["event"].isin(["BUY", "SELL", "DIVIDEND_PAID"])]
    reconstructed_cash = config["initial_cash"] + movements.groupby("date")["amount"].sum().reindex(nav.index, fill_value=0).cumsum()
    receivable_events = cash.loc[cash["event"].isin(["DIVIDEND_RECEIVABLE", "DIVIDEND_PAID"])].copy()
    receivable_events["change"] = np.where(receivable_events["event"].eq("DIVIDEND_PAID"), -receivable_events["amount"], receivable_events["amount"])
    reconstructed_receivables = receivable_events.groupby("date")["change"].sum().reindex(nav.index, fill_value=0).cumsum()
    holdings["reconstructed_value"] = holdings["quantity"] * holdings["price"]
    reconstructed_holdings = holdings.groupby("date")["reconstructed_value"].sum().reindex(nav.index, fill_value=0)
    np.testing.assert_allclose(reconstructed_cash, nav["cash_total"], rtol=0, atol=1e-7)
    np.testing.assert_allclose(reconstructed_receivables, nav["receivables"], rtol=0, atol=1e-7)
    np.testing.assert_allclose(reconstructed_holdings, nav["holdings_value"], rtol=0, atol=1e-7)
    np.testing.assert_allclose(reconstructed_cash + reconstructed_receivables + reconstructed_holdings,
                               nav["nav"], rtol=0, atol=1e-7)
    assert nav["cash_available"].ge(0).all()
    assert (holdings["quantity"] == holdings["sellable_quantity"] + holdings["locked_quantity"]).all()


@pytest.mark.parametrize("override,fragment", [
    ({"live_enabled": True}, "live_enabled"),
    ({"sample": "holdout"}, "holdout"),
    ({"risk_scaling": "false"}, "risk_scaling"),
    ({"unknown_execution_override": 123}, "Unknown"),
])
def test_invalid_config_is_registered_and_failure_is_preserved(dataset, config, tmp_path, override, fragment):
    config.update(override)
    with pytest.raises(ValueError, match=fragment):
        run_experiment(dataset, config, tmp_path, REPO)
    assert_preserved_failure(tmp_path, fragment)


def test_physical_holdout_dates_cannot_bypass_gate_with_synthetic_label(dataset, config, tmp_path):
    # This invented, discontinuous calendar is deliberately not market evidence.
    # Keep complete rows so the test reaches the physical holdout gate itself.
    old, future = dataset.calendar[-1], "2025-01-02"
    dataset.calendar[-1] = future
    for table in (dataset.bars, dataset.benchmark):
        mask = table["date"].eq(old)
        table.loc[mask, "date"] = future
        table.loc[mask, "available_at"] = future + "T16:00:00+08:00"
    dataset.manifest["coverage_end"] = future
    assert audit_dataset(dataset)["status"] == "SYNTHETIC_ONLY"
    with pytest.raises(ValueError, match="Final holdout is locked"):
        run_experiment(dataset, config, tmp_path, REPO)
    assert_preserved_failure(tmp_path, "Final holdout is locked")


def test_loaded_unverified_real_data_cannot_be_run_as_synthetic(dataset, config, tmp_path):
    # Flag mutation is a negative test, not a claim that generated rows are real.
    dataset.manifest["synthetic"] = False
    save_dataset(dataset, tmp_path / "quarantine")
    quarantined = load_dataset(tmp_path / "quarantine", allow_unverified=True)
    assert quarantined.manifest["synthetic"] is False
    assert audit_dataset(quarantined)["status"] == "BLOCKED_DATA"
    root = tmp_path / "runs"
    with pytest.raises(ValueError, match="Real data cannot be relabelled synthetic"):
        run_experiment(quarantined, config, root, REPO)
    assert_preserved_failure(root, "Real data cannot be relabelled synthetic")
