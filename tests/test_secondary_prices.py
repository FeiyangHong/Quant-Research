import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("secondary", Path(__file__).parents[1] / "scripts/collect_eastmoney_check.py")
secondary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secondary)


def payload(day="2024-12-31"):
    return json.dumps({"rc": 0, "data": {"code": "510300", "klines": [day + ",4,4.1,4.2,3.9,123,50000,1,1,0.1,2"]}}).encode()


def test_unadjusted_secondary_volume_unit_is_explicit():
    row, = secondary.parse_payload(payload(), "sh.510300", "2010-01-01", "2024-12-31")
    assert row["volume_lots"] == "123" and row["volume"] == "12300"
    assert row["close"] == "4.1"


def test_secondary_response_cannot_admit_holdout_or_wrong_identity():
    with pytest.raises(ValueError, match="holdout"):
        secondary.parse_payload(payload("2025-01-02"), "sh.510300", "2010-01-01", "2024-12-31")
    with pytest.raises(ValueError, match="identity"):
        secondary.parse_payload(payload(), "sh.510500", "2010-01-01", "2024-12-31")


def test_source_absence_is_not_fabricated_price_history():
    assert secondary.parse_payload(b'{"rc":0,"data":null}', "sh.512320", "2010-01-01", "2024-12-31") == []
    with pytest.raises(ValueError, match="application"):
        secondary.parse_payload(b'{"rc":1,"data":null}', "sh.512320", "2010-01-01", "2024-12-31")
