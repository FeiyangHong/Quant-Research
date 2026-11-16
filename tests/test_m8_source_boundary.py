"""Offline request checks; no network or budget is consumed by these tests."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest


@pytest.fixture
def source(tmp_path, monkeypatch):
    location = Path(__file__).resolve().parents[1] / 'scripts/m8_sources.py'
    spec = importlib.util.spec_from_file_location('m8_source_guard_test', location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    report = tmp_path / 'reports/m8_rotation'
    report.mkdir(parents=True)
    (report / 'COHORT_SELECTION.json').write_text(json.dumps(dict(
        status='FORMED', selected_instruments=['sh.512880'])), encoding='utf-8')
    (report / 'SOURCE_POLICY_ADDENDUM.md').write_text('Invented guard fixture', encoding='utf-8')
    return module


def test_prices_require_frozen_member_raw_basis_and_pre2025_window(source):
    query = dict(secid='1.512880', fqt='0', beg='20190101', end='20241231')
    url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?'
    source.validate_url(url + urlencode(query), dates='2019-01-01~2024-12-31', route='selected_raw_prices')
    for changes in ({'secid': '1.512000'}, {'fqt': '1'}, {'end': '20251113'}):
        with pytest.raises(ValueError):
            source.validate_url(url + urlencode(dict(query, **changes)),
                dates='2019-01-01~2024-12-31', route='selected_raw_prices')
    with pytest.raises(ValueError):
        source.validate_url(url + urlencode(query), dates='2019-01-01~2025-01-01', route='selected_raw_prices')


def test_retrospective_exception_does_not_open_market_or_general_2025_reports(source):
    url = 'https://query.sse.com.cn/commonQuery.do?'
    query = dict(SECURITY_CODE='512880', TITLE='2024年年度报告',
                 START_DATE='2025-01-01', END_DATE='2025-04-30')
    source.validate_url(url + urlencode(query), dates='2025-01-01~2025-04-30',
                        route='retrospective_2024_annual')
    for changes in ({'SECURITY_CODE': '512000'}, {'TITLE': '2025年第一季度报告'}, {'END_DATE': '2025-12-31'}):
        with pytest.raises(ValueError):
            source.validate_url(url + urlencode(dict(query, **changes)),
                dates='2025-01-01~2025-04-30', route='retrospective_2024_annual')
    with pytest.raises(ValueError):
        source.validate_url('https://push2his.eastmoney.com/api/qt/stock/kline/get',
            dates='2025-01-01~2025-04-30', route='retrospective_2024_annual')
