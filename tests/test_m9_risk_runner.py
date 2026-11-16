"""Registration and independent accounting gates, without real account runs."""
from pathlib import Path

import pytest

from quant_research.provenance import write_json
from quant_research.risk_budget import CLAIM_TYPE, RISK_SCOPE
from quant_research.risk_runner import (config_for, file_hash, validate_risk_config,
                                        verify_base_receipt)


def trial(path="base"):
    return dict(period="development", variant="VE", scope=RISK_SCOPE, claim_type=CLAIM_TYPE,
                initial_cash=100000, risk_scaling=True, signal_release_delay=1,
                execution_delay=1 if path != "delay_1_session" else 2,
                cost_multiplier={"base": 1, "cost_2x": 2, "cost_3x": 3, "delay_1_session": 1}[path],
                slippage_multiplier={"base": 1, "cost_2x": 2, "cost_3x": 3, "delay_1_session": 1}[path],
                annual_incremental_cost=None, seed=20261114)


def test_only_registered_arms_capital_and_execution_paths_are_open():
    for path in ("base", "cost_2x", "cost_3x", "delay_1_session"):
        validate_risk_config(config_for(trial(path)))
    for key, value in (("sample", "holdout"), ("sample", "synthetic"), ("initial_cash", 10000),
                       ("variant", "R0"), ("risk_scaling", False), ("annual_incremental_cost", 0),
                       ("signal_release_delay", 0), ("cost_multiplier", True), ("execution_delay", 3)):
        config = config_for(trial())
        config[key] = value
        with pytest.raises(ValueError):
            validate_risk_config(config)


def receipt_fixture(tmp_path):
    records = []
    for period in ("development", "validation"):
        for variant in ("VE", "CE", "VR"):
            trial_id = f"M9_{period}_{variant}_100000_base"
            private = tmp_path / "private" / trial_id
            public = tmp_path / "public" / "accounts" / trial_id
            write_json(private / "nav.json", [{"nav": 100000}])
            write_json(private / "fills.json", [])
            write_json(public / "nav.json", [{"nav": 100000}])
            records.append(dict(trial_id=trial_id, run_id=trial_id, path="base", status="COMPLETED",
                exported_tables={"nav.json": file_hash(public / "nav.json")},
                private_table_hashes={p.name: file_hash(p) for p in private.glob("*.json")}))
    receipt = dict(decision="PASS_DATA_AND_ACCOUNTING", author_role="INDEPENDENT_REVIEWER",
                   base_account_hashes={r["trial_id"]: r["exported_tables"] for r in records},
                   private_table_hashes={r["trial_id"]: r["private_table_hashes"] for r in records})
    path = tmp_path / "receipt.json"
    write_json(path, receipt)
    return records, receipt, path


def test_stress_gate_requires_all_six_and_independent_hashes(tmp_path):
    records, receipt, path = receipt_fixture(tmp_path)
    assert verify_base_receipt(path, records, tmp_path / "private", tmp_path / "public") == file_hash(path)
    with pytest.raises(ValueError, match="six"):
        verify_base_receipt(path, records[:-1], tmp_path / "private")
    receipt["author_role"] = "IMPLEMENTER"
    write_json(path, receipt)
    with pytest.raises(ValueError, match="Independent"):
        verify_base_receipt(path, records, tmp_path / "private")


@pytest.mark.parametrize("side", ["public", "private"])
def test_stress_gate_rechecks_reviewed_bytes_not_just_claimed_hashes(tmp_path, side):
    records, receipt, path = receipt_fixture(tmp_path)
    folder = tmp_path / side
    if side == "public":
        folder /= "accounts"
    write_json(folder / records[0]["run_id"] / "nav.json", [{"nav": 99999}])
    with pytest.raises(ValueError, match="changed"):
        verify_base_receipt(path, records, tmp_path / "private", tmp_path / "public")
