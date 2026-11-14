import hashlib
import json

import pytest

from quant_research.admission import verify_attestation, split_sample
from quant_research.data import DataValidationError, EVIDENCE_GATES, synthetic_dataset


def test_admission_binds_reviewed_stage_and_each_source(tmp_path):
    evidence = tmp_path / "review.txt"
    evidence.write_text("independent evidence", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "manifest.json").write_text('{"file_sha256":{},"source_snapshot_hashes":{}}')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    review = dict(schema_version=1, decision="ADMIT_DAILY_SCREEN", reviewer="independent-test",
        reviewed_at="2026-11-15T00:00:00+08:00", qualifications=["test only"],
        stage_manifest_sha256=sha(stage / "manifest.json"), evidence_files={"review.txt": sha(evidence)},
        evidence_gates={g: dict(status="VERIFIED", reviewer="test", reviewed_at="2026-11-15T00:00:00+08:00",
            evidence=["review.txt"]) for g in EVIDENCE_GATES})
    attestation = tmp_path / "attestation.json"
    attestation.write_text(json.dumps(review))
    assert verify_attestation(stage, attestation, tmp_path)["reviewer"] == "independent-test"
    evidence.write_text("changed after review")
    with pytest.raises(DataValidationError, match="evidence hash mismatch"):
        verify_attestation(stage, attestation, tmp_path)
    (stage / "manifest.json").write_text("{}")
    with pytest.raises(DataValidationError, match="staging snapshot differs"):
        verify_attestation(stage, attestation, tmp_path)


def test_development_is_physically_separate_and_keeps_historical_identities():
    original = synthetic_dataset()
    development = split_sample(original, "development")
    assert max(development.calendar) <= "2021-12-31"
    assert max(development.bars.date) <= "2021-12-31"
    assert max(development.benchmark.date) <= "2021-12-31"
    assert max(development.actions.ex_date) <= "2021-12-31"
    assert "SYN_ETF_300_EXIT" in set(development.instruments.instrument_id)
    assert max(development.instruments.available_at.str[:10]) <= "2021-12-31"
    assert max(original.calendar) == "2024-12-31"
    assert len(split_sample(original, "validation").calendar) == len(original.calendar)
    with pytest.raises(DataValidationError, match="holdout is locked"):
        split_sample(original, "final")
