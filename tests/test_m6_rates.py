"""Synthetic counterexamples for tax applicability; never source evidence."""
from copy import deepcopy

import pandas as pd
import pytest

from quant_research.engineering_replay import synthetic_fixture
from quant_research.execution import run_backtest


def fixture():
    data, decisions = synthetic_fixture()
    data['actions'] = pd.DataFrame()
    data['tax_settlements'] = []
    return data, decisions[:1]


def replay(data, decisions):
    return run_backtest(data, decisions, 100000, slippage_multiplier=0,
                        engineering_replay=True)


def same_account(left, right):
    for key, value in left.items():
        if isinstance(value, pd.DataFrame):
            pd.testing.assert_frame_equal(value, right[key])


@pytest.mark.parametrize('index', [0, 2])
def test_unrelated_past_and_future_missing_clock_leave_all_tables_unchanged(index):
    data, decisions = fixture()
    base = replay(data, decisions)
    assert base['fills'].quantity.tolist() == [200]
    data['tax_rules'].loc[index, ['available_at', 'source_url']] = None
    data['tax_rules'].loc[index, 'verified'] = False
    same_account(base, replay(data, decisions))
    data['tax_rules'] = data['tax_rules'].iloc[::-1]
    same_account(base, replay(data, decisions))


@pytest.mark.parametrize('field,value', [
    ('available_at', None), ('available_at', '2023-08-01T10:00:00+08:00'),
    ('available_at', 'invalid'), ('verified', False), ('source_url', None),
    ('source_url', float('nan')), ('effective_from', None),
    ('effective_to', None), ('effective_from', '2023-02-30'),
    ('stamp_duty_sell', -1),
])
def test_applicable_invalid_rule_rejects(field, value):
    data, decisions = fixture()
    data['tax_rules'].loc[1, field] = value
    assert replay(data, decisions)['fills'].empty


@pytest.mark.parametrize('verified,known', [(True, '2022-04-28T21:00:00+08:00'),
                                          (False, None),
                                          (True, '2023-08-02T21:00:00+08:00')])
def test_overlapping_candidate_cannot_fall_back(verified, known):
    data, decisions = fixture()
    extra = dict(data['tax_rules'].iloc[1], verified=verified, available_at=known)
    data['tax_rules'] = pd.concat([data['tax_rules'], pd.DataFrame([extra])], ignore_index=True)
    result = replay(data, decisions)
    assert result['fills'].empty
    assert set(result['rejected_orders'].reason) == {'UNKNOWN_OR_AMBIGUOUS_STOCK_TAX_RULE'}


@pytest.mark.parametrize('field,default,other', [
    ('asset_type', 'STOCK', 'ETF'),
    ('market', 'SSE', 'SZSE'),
    ('component', 'STOCK_TRANSACTION_FEES', 'DIVIDEND_TAX'),
    ('instrument_id', 'ALL', 'OTHER_SECURITY'),
])
def test_provably_unrelated_scope_does_not_require_clock(field, default, other):
    data, decisions = fixture()
    data['instruments']['market'] = 'SSE'
    data['tax_rules'][field] = default
    base = replay(data, decisions)
    extra = dict(data['tax_rules'].iloc[1])
    extra.update({field: other, 'available_at': None, 'verified': False, 'source_url': None})
    data['tax_rules'] = pd.concat([data['tax_rules'], pd.DataFrame([extra])], ignore_index=True)
    same_account(base, replay(data, decisions))
    data['tax_rules'].loc[len(data['tax_rules']) - 1, field] = None
    assert replay(data, decisions)['fills'].empty


def test_etf_path_does_not_depend_on_stock_rates():
    data, decisions = fixture()
    data['instruments']['asset_type'] = 'ETF'
    base = replay(data, decisions)
    assert base['fills'].quantity.tolist() == [200]
    data['tax_rules'] = pd.DataFrame([{'effective_from': None, 'available_at': None}])
    same_account(base, replay(data, decisions))
