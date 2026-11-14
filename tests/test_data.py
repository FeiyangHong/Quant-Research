"""Data boundary tests target leakage, lost identities and false evidence."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data import (
    Dataset, DataValidationError, EVIDENCE_GATES, PROVENANCE_COLUMNS,
    asof_records, audit_dataset, bars_asof, date_only_available_at,
    load_dataset, master_asof, save_dataset, synthetic_dataset,
)


@pytest.fixture(scope="module")
def full():
    return synthetic_dataset()


@pytest.fixture
def small(full):
    data = copy.deepcopy(full)
    data.calendar = data.calendar[:5]
    data.bars = data.bars.loc[data.bars["date"].isin(data.calendar)].copy()
    data.benchmark = data.benchmark.loc[data.benchmark["date"].isin(data.calendar)].copy()
    data.actions = data.actions.iloc[:0].copy()
    data.instruments = data.instruments.loc[data.instruments["supersedes_id"].isna()].copy()
    return data


def test_fixture_cannot_be_performance_evidence(full):
    report = audit_dataset(full)
    assert report["errors"] == []
    assert report["blockers"] == []
    assert report["status"] == "SYNTHETIC_ONLY"
    assert report["performance_evidence"] is False
    assert report["coverage"]["calendar_sessions"] == 1827
    assert len(full.instruments["instrument_id"].unique()) == 6
    assert set(full.actions["action_type"]) == {"SPLIT", "CASH_DIVIDEND", "DELISTING"}
    assert full.calendar[-1] < "2025-01-01"


def test_deterministic_generation(full):
    second = synthetic_dataset()
    pd.testing.assert_frame_equal(full.bars, second.bars)
    pd.testing.assert_frame_equal(full.instruments, second.instruments)
    assert full.manifest == second.manifest


def test_round_trip_hashes_empty_tables_and_immutable_snapshot(small, tmp_path):
    manifest = save_dataset(small, tmp_path / "v1")
    assert len(manifest["file_sha256"]) == 5
    restored = load_dataset(tmp_path / "v1")
    assert restored.calendar == small.calendar
    assert list(restored.actions.columns) == list(small.actions.columns)
    assert restored.actions.empty
    pd.testing.assert_frame_equal(restored.bars, small.bars.reset_index(drop=True), check_dtype=False)
    save_dataset(small, tmp_path / "v1")
    small.bars.loc[small.bars.index[0], "volume"] += 1
    with pytest.raises(FileExistsError):
        save_dataset(small, tmp_path / "v1")


def test_tampered_snapshot_rejected(small, tmp_path):
    save_dataset(small, tmp_path)
    path = tmp_path / "bars.json"
    payload = json.loads(path.read_text())
    payload["records"][0]["close"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataValidationError, match="Hash mismatch"):
        load_dataset(tmp_path)


def test_date_only_delay_strictly_next_session_including_weekend():
    calendar = ["2024-03-01", "2024-03-04", "2024-03-05", "2024-03-06"]
    assert date_only_available_at("2024-03-01", calendar) == "2024-03-04T21:00:00+08:00"
    assert date_only_available_at("2024-03-02", calendar) == "2024-03-04T21:00:00+08:00"
    assert date_only_available_at("2024-03-01", calendar, extra_delay=1) == "2024-03-05T21:00:00+08:00"
    with pytest.raises(DataValidationError, match="Calendar"):
        date_only_available_at("2024-03-06", calendar)


def test_cutoff_timezone_and_late_publication(small):
    records = pd.DataFrame([
        {"key": "before", "available_at": "2024-03-01T20:59:00+08:00"},
        {"key": "after", "available_at": "2024-03-01T21:01:00+08:00"},
        {"key": "overseas", "available_at": "2024-03-01T16:00:00-05:00"},
    ])
    assert asof_records(records, "2024-03-01T21:00:00+08:00", ["key"])["key"].tolist() == ["before"]
    with pytest.raises(DataValidationError, match="Timezone-aware"):
        bars_asof(small, "2018-01-02 21:00:00")


def test_future_revision_prefix_invariance(small):
    original = small.bars.iloc[0].copy()
    revised = original.copy()
    revised["revision_id"] += "_corrected"
    revised["supersedes_id"] = original["revision_id"]
    revised["available_at"] = "2020-01-01T16:00:00+08:00"
    revised["volume"] += 123456
    early = bars_asof(small, "2018-01-05T21:00:00+08:00")
    small.bars = pd.concat([small.bars, revised.to_frame().T], ignore_index=True)
    late_input_early_cutoff = bars_asof(small, "2018-01-05T21:00:00+08:00")
    pd.testing.assert_frame_equal(early.reset_index(drop=True), late_input_early_cutoff.reset_index(drop=True), check_dtype=False)
    later = bars_asof(small, "2020-01-01T21:00:00+08:00")
    match = later.loc[(later["date"] == original["date"]) & (later["instrument_id"] == original["instrument_id"])]
    assert len(match) == 1 and match.iloc[0]["volume"] == revised["volume"]
    assert not audit_dataset(small)["errors"]


def test_delisting_unknown_before_announcement_but_identity_retained(full):
    identity = "SYN_ETF_300_EXIT"
    before = master_asof(full, "2022-10-11T21:00:00+08:00").set_index("instrument_id")
    after = master_asof(full, "2023-01-01T21:00:00+08:00").set_index("instrument_id")
    assert pd.isna(before.loc[identity, "delisted_on"])
    assert after.loc[identity, "delisted_on"] == "2022-10-17"
    assert len(before) == len(after) == 6
    assert not ((full.bars["instrument_id"] == identity) & (full.bars["date"] >= "2022-10-17")).any()


def test_total_return_uses_only_effective_corporate_action(full):
    for _, action in full.actions.loc[full.actions["action_type"] != "DELISTING"].iterrows():
        bars = full.bars.loc[full.bars["instrument_id"] == action["instrument_id"]].reset_index(drop=True)
        event = bars.index[bars["date"] == action["ex_date"]][0]
        current, previous = bars.iloc[event], bars.iloc[event - 1]
        expected = (current["close"] * action["share_factor"] + action["cash_per_share"]) / previous["close"]
        assert current["total_return_index"] / previous["total_return_index"] == pytest.approx(expected)
        assert pd.Timestamp(action["available_at"]) < pd.Timestamp(action["ex_date"] + "T09:30:00+08:00")


@pytest.mark.parametrize("mutation,fragment", [
    (lambda d: d.bars.__setitem__("available_at", "2018-01-01 16:00:00"), "timezone-naive"),
    (lambda d: d.bars.__setitem__("high", 0), "inconsistent OHLC"),
    (lambda d: d.bars.__setitem__("volume", -1), "quantity sign"),
    (lambda d: d.bars.__setitem__("close", np.nan), "nonfinite"),
    (lambda d: d.instruments.__setitem__("account_verified", "true"), "requires boolean"),
    (lambda d: d.bars.__setitem__("available_at", d.bars["date"] + "T14:00:00+08:00"), "before session close"),
])
def test_bad_schema_never_silently_coerced(small, mutation, fragment):
    mutation(small)
    report = audit_dataset(small)
    assert report["status"] == "BLOCKED_DATA"
    assert any(fragment in error for error in report["errors"])


def test_duplicate_primary_key_and_equal_time_ambiguity(small):
    small.bars = pd.concat([small.bars, small.bars.iloc[:1]], ignore_index=True)
    report = audit_dataset(small)
    assert any("duplicate versioned primary key" in e for e in report["errors"])
    with pytest.raises(DataValidationError, match="Ambiguous"):
        bars_asof(small, "2018-01-05T21:00:00+08:00")


def test_broken_revision_chain_detected(small):
    small.bars.loc[small.bars.index[0], "supersedes_id"] = "not-there"
    assert any("invalid revision lineage" in e for e in audit_dataset(small)["errors"])


def test_missing_data_is_not_zero_or_suspension(small):
    small.bars = small.bars.iloc[1:]
    report = audit_dataset(small)
    assert report["status"] == "BLOCKED_DATA"
    assert report["coverage"]["missing_sessions_by_instrument"]["SYN_ETF_300"] == 1


def test_real_data_evidence_absence_fails_closed(small, tmp_path):
    small.manifest["synthetic"] = False
    report = audit_dataset(small)
    assert report["errors"] == []
    assert report["status"] == "BLOCKED_DATA"
    assert report["performance_evidence"] is False
    assert any("license unverified" in e for e in report["blockers"])
    save_dataset(small, tmp_path)
    with pytest.raises(DataValidationError):
        load_dataset(tmp_path)
    quarantined = load_dataset(tmp_path, allow_unverified=True)
    assert audit_dataset(quarantined)["status"] == "BLOCKED_DATA"


def test_real_date_only_cannot_be_promoted_to_same_day(small):
    small.manifest["synthetic"] = False
    # These are test placeholders, never supplier or license evidence.
    for name in ("instruments", "bars", "actions", "benchmark"):
        frame = getattr(small, name)
        for column in PROVENANCE_COLUMNS:
            frame[column] = "TEST_ONLY"
        frame["availability_mode"] = "historical_public_asof"
        frame["quality_status"] = "accepted"
        frame["publication_precision"] = "date_only"
        frame["published_at"] = "2018-01-01"
        frame["ingested_at"] = "2026-11-14T22:00:00+08:00"
        frame["processed_at"] = "2026-11-14T22:01:00+08:00"
        frame["raw_object_hash"] = "0" * 64
    report = audit_dataset(small)
    assert any("availability lower bound" in item for item in report["blockers"])

