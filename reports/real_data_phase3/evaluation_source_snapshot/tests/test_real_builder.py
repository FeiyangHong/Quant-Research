import copy
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from quant_research.providers.real_builder import (
    BuildBlockedError, _availability, _verified_file, historical_limits,
    normalize_actions, reconstruct_total_return, write_staged)
from test_execution import fixture, decision
from quant_research.data import Dataset
from quant_research.execution import ExecutionBlockedError, run_backtest


def tr_bars(closes, suspended=None):
    days = pd.bdate_range("2022-08-24", periods=len(closes)).strftime("%Y-%m-%d").tolist()
    return pd.DataFrame([dict(date=day, instrument_id="ETF", close=close, suspended=bool(suspended and suspended[i]),
        volume=0 if suspended and suspended[i] else 100000, available_at=day + "T21:00:00+08:00",
        market_available_at=day + "T21:00:00+08:00") for i, (day, close) in enumerate(zip(days, closes))])


def test_eod_tr_keeps_raw_close_and_uses_new_basis_next_session():
    bars = tr_bars([7.236, 7.220, 6.300])
    action = pd.DataFrame([dict(ex_date=bars.iloc[1].date, action_type="SPLIT", effective_phase="EOD",
        share_factor=1.14539, available_at=bars.iloc[0].available_at)])
    result, issues = reconstruct_total_return(bars, action)
    assert not issues
    assert result.close.tolist() == bars.close.tolist()
    assert result.iloc[1].total_return_index == pytest.approx(100 * 7.220 / 7.236)
    assert result.iloc[1].valuation_close == pytest.approx(7.220 / 1.14539)
    assert result.iloc[2].total_return_index == pytest.approx(100 * 6.300 * 1.14539 / 7.236)


def test_bod_suspended_stale_old_quote_and_dividend_are_not_double_counted():
    bars = tr_bars([1., 1., 2.], suspended=[False, True, False])
    action = pd.DataFrame([dict(ex_date=bars.iloc[1].date, action_type="SPLIT", effective_phase="BOD",
        share_factor=.5, available_at=bars.iloc[0].available_at)])
    result, issues = reconstruct_total_return(bars, action)
    assert not issues and np.allclose(result.total_return_index, 100.)
    assert result.iloc[1].valuation_close == 2.
    div_bars = tr_bars([10., 9., 9.])
    dividend = pd.DataFrame([dict(ex_date=div_bars.iloc[1].date, action_type="CASH_DIVIDEND", effective_phase="BOD",
        cash_per_share=1., available_at=div_bars.iloc[0].available_at)])
    result, issues = reconstruct_total_return(div_bars, dividend)
    assert not issues and np.allclose(result.total_return_index, 100.)


def test_late_exact_ratio_delays_tr_availability_without_early_feature_values():
    bars = tr_bars([1., 1., 2., 2.], suspended=[False, True, False, False])
    known = bars.iloc[2].available_at
    actions = pd.DataFrame([dict(ex_date=bars.iloc[1].date, action_type="SPLIT", effective_phase="BOD",
        share_factor=.5, available_at=known)])
    result, _ = reconstruct_total_return(bars, actions)
    assert result.iloc[1].total_return_available_at == known
    assert result.iloc[1].available_at == bars.iloc[1].available_at
    assert result.iloc[1].market_available_at == bars.iloc[1].available_at
    assert result.iloc[0].available_at == bars.iloc[0].available_at
    visible = result.loc[pd.to_datetime(result.total_return_available_at) <= pd.Timestamp(bars.iloc[1].available_at)]
    assert list(visible.date) == [bars.iloc[0].date]
    future = actions.copy()
    future.loc[0, "ex_date"] = "2024-01-01"
    prefix, _ = reconstruct_total_return(bars.iloc[:1], future)
    assert prefix.iloc[0].total_return_index == result.iloc[0].total_return_index


def test_shenzhen_registration_close_and_official_ex_date_remain_distinct():
    event = dict(action_id="registration", instrument_id="TEST", type="SPLIT",
        announcement_date="2024-11-16", available_at="2024-11-18T21:00:00+08:00",
        record_date="2024-11-29", effective_date="2024-11-29", ex_date="2024-12-02",
        effective_phase="END_OF_DAY", split_ratio="2.5", fractional_share_rounding="CEIL",
        source_sha256="a" * 64, parse_status="HUMAN_RECONCILED_HASH_BOUND")
    row, = normalize_actions({"canonical_actions": [event]}, {}, "2026-11-15T00:00:00+08:00")
    assert row["ex_date"] == row["record_date"] == "2024-11-29"
    assert row["source_ex_date"] == "2024-12-02" and row["effective_phase"] == "EOD"


def test_canceled_plan_has_no_tr_effect_and_prelisting_does_not_apply_twice():
    bars = tr_bars([10., 10., 10.])
    actions = pd.DataFrame([dict(ex_date=bars.iloc[1].date, action_type="SPLIT", effective_phase="BOD",
        share_factor=.2, action_status="CANCELLED", available_at=bars.iloc[0].available_at),
        dict(ex_date="2020-01-01", action_type="SPLIT", effective_phase="BOD", share_factor=.5,
             action_usage_scope="PRE_LISTING_METADATA_ONLY", available_at="2020-01-02T21:00:00+08:00")])
    result, issues = reconstruct_total_return(bars, actions)
    assert not issues and np.allclose(result.total_return_index, 100.)


def test_reconstruction_never_invents_unknown_publication_time():
    unknown = _availability("2020-01-01", {})
    assert unknown["available_at"] is None and unknown["published_at"] is None
    declared = _availability("2020-01-01", dict(mode="historical_public_asof", available_clock="21:00:00",
        reconstruction_basis="TEST_ONLY_POLICY", source_url="https://example.test/rule"))
    assert declared["available_at"] == "2020-01-01T21:00:00+08:00"
    assert declared["published_at"] is None and declared["publication_precision"] == "unknown"
    with pytest.raises(BuildBlockedError):
        _availability("2020-01-01", dict(mode="historical_public_asof", available_clock="14:00:00",
            reconstruction_basis="test", source_url="https://example.test/rule"))


def test_historical_limits_require_rule_and_preserve_exrights_reference():
    record = dict(date="2022-08-29", instrument_id="ETF", preclose=6.304)
    assert historical_limits(record, "CSI500", [])["upper_limit"] is None
    rule = dict(benchmark_id="CSI500", effective_from="2020-01-01", effective_to="2024-12-31",
        available_at="2019-12-01T21:00:00+08:00", limit_ratio=.1, tick_size=.001,
        source_url="https://example.test/rule", rule_id="test")
    limits = historical_limits(record, "CSI500", [rule])
    assert limits["upper_limit"] == 6.934 and limits["lower_limit"] == 5.674
    assert limits["limit_reference_price"] == 6.304
    with pytest.raises(BuildBlockedError, match="Overlapping"):
        historical_limits(record, "CSI500", [rule, rule])


def test_source_hash_mismatch_and_escape_are_rejected(tmp_path):
    source = tmp_path / "record.json"
    source.write_text('{"value":1}', encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert _verified_file(tmp_path, "record.json", digest) == {"value": 1}
    with pytest.raises(BuildBlockedError, match="SHA256"):
        _verified_file(tmp_path, "record.json", "0" * 64)
    with pytest.raises(BuildBlockedError, match="outside"):
        _verified_file(tmp_path, "../escape.json", digest)


def test_action_mapper_preserves_date_only_and_requires_separate_cash_policy():
    event = dict(action_id="div", instrument_id="ETF", type="DIVIDEND", announcement_date="2020-01-01",
        available_at="2020-01-02T21:00:00+08:00", ex_date="2020-01-06", record_date="2020-01-03",
        scheduled_pay_date="2020-01-08", cash_per_share=".1", source_sha256="a" * 64,
        source_url="https://example.test/issuer", parse_status="PARSED_LABELED_TABLE")
    row = normalize_actions({"canonical_actions": [event]}, {}, "2026-01-01T00:00:00+00:00")[0]
    assert row["action_type"] == "CASH_DIVIDEND" and row["published_at"] == "2020-01-01"
    assert row["publication_precision"] == "date_only"
    assert "cash_settlement_verified" not in row and "settlement_mode" not in row


def test_late_ratio_published_date_comes_from_final_document_not_schedule():
    event = dict(action_id="late", instrument_id="ETF", type="SPLIT", announcement_date="2015-04-03",
        available_at="2015-04-16T21:00:00+08:00", ex_date="2015-04-14", split_ratio=".28032483",
        effective_phase="SUSPENDED_SESSION", source_sha256="f" * 64)
    manifest = {"canonical_actions": [event], "documents": [{"pdf_sha256": "f" * 64, "publication_date": "2015-04-15"}]}
    row = normalize_actions(manifest, {}, "2026-01-01T00:00:00+00:00")[0]
    assert row["announcement_date"] == "2015-04-03"
    assert row["published_at"] == "2015-04-15"
    assert row["available_at"] == "2015-04-16T21:00:00+08:00"
    event["status"], event["split_ratio"] = "CANCELLED", None
    row = normalize_actions({"canonical_actions": [event]}, {}, "2026-01-01T00:00:00+00:00")[0]
    assert row["share_factor"] is None and row["action_status"] == "CANCELLED"


def test_staging_writes_nulls_and_never_claims_gate_admission(tmp_path):
    data = fixture(days=2)
    manifest = {"status": "STAGING_ONLY", "performance_evidence": False, "strategy_runs_permitted": False,
                "evidence_gates": {"source": {"status": "PENDING_INDEPENDENT_REVIEW"}}}
    data["bars"]["upper_limit"] = None
    ds = Dataset(data["calendar"], data["instruments"], data["bars"], data["actions"], pd.DataFrame(), manifest)
    target = tmp_path / "staged"
    saved = write_staged(ds, {"status": "STAGING_ONLY"}, target)
    assert saved["performance_evidence"] is False
    assert json.loads((target / "bars.json").read_text())["records"][0]["upper_limit"] is None
    with pytest.raises(FileExistsError):
        write_staged(ds, {}, target)


def test_prelisting_share_metadata_retained_without_applying_to_secondary_market_account():
    data = fixture()
    data["instruments"].loc[data["instruments"].instrument_id.eq("ETF_A"), "listed_on"] = data["calendar"][25]
    data["actions"] = pd.DataFrame([dict(action_id="prelisting", instrument_id="ETF_A", action_type="SPLIT",
        action_usage_scope="PRE_LISTING_METADATA_ONLY", effective_phase="BOD", share_factor=.69448528,
        ex_date=data["calendar"][23], available_at=data["calendar"][24] + "T21:00:00+08:00")])
    result = run_backtest(data, [decision(data, 26)], 100000, cost_multiplier=0, slippage_multiplier=0)
    assert result["share_events"].iloc[0].status == "PRE_LISTING_METADATA_ONLY"
    assert result["positions"].iloc[-1].quantity == 3000
    invalid = copy.deepcopy(data)
    invalid["instruments"].loc[invalid["instruments"].instrument_id.eq("ETF_A"), "listed_on"] = data["calendar"][20]
    with pytest.raises(ExecutionBlockedError, match="Pre-listing share metadata"):
        run_backtest(invalid, [], 100000)
