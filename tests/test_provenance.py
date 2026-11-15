import pytest
from quant_research.provenance import digest, validate_run_config


def test_canonical_hash():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_holdout_and_live_are_locked():
    base = dict(live_enabled=False, sample="synthetic", universe="R1B", variant="E0", initial_cash=100000)
    validate_run_config(base)
    for delta in ({"sample": "holdout"}, {"live_enabled": True}, {"universe": "R1I"}, {"execution_delay": 0}):
        with pytest.raises(ValueError):
            validate_run_config(dict(base, **delta))
