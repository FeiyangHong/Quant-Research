"""Non-author hand oracles. Invented data only, no strategy performance."""
from copy import deepcopy
from decimal import Decimal
import pandas as pd
import pytest

from quant_research.engineering_replay import synthetic_fixture
from quant_research.execution import run_backtest


def fixture(scoped=False):
    data, decisions = synthetic_fixture()
    data['actions'] = pd.DataFrame()
    data['tax_settlements'] = []
    if scoped:
        data['instruments']['market'] = 'SSE'
        data['tax_rules'] = data['tax_rules'].assign(
            asset_type='STOCK', market='ALL',
            component='STOCK_TRANSACTION_FEES', instrument_id='ALL')
    return data, decisions[:1]


def run(data, decisions, multiplier=1):
    return run_backtest(data, decisions, 100000, slippage_multiplier=0,
                        cost_multiplier=multiplier, engineering_replay=True)


def assert_same(left, right):
    assert set(left) == set(right)
    for key in left:
        if isinstance(left[key], pd.DataFrame):
            pd.testing.assert_frame_equal(left[key], right[key], obj=key)
        else:
            assert left[key] == right[key], key


def assert_blocked(result):
    assert result['fills'].empty
    assert not result['rejected_orders'].empty
    assert result['nav']['nav'].eq(100000).all()
    assert result['nav']['holdings_value'].eq(0).all()


def test_required_differential_and_independent_daily_decimal_oracle():
    data, decisions = fixture()
    original = run(data, decisions)
    row = original['fills'].iloc[0]
    assert (row['date'], row['quantity'], row['price']) == ('2023-08-01', 200, 10)
    # Hand expectation uses only pre-fixed quantity, price and fee constants.
    cash = Decimal('100000') - Decimal(200) * Decimal(10) - Decimal('5.00') - Decimal('0.02')
    assert cash == Decimal('97994.98')
    for _, day in original['nav'].iterrows():
        invested = day['date'] >= '2023-08-01'
        assert Decimal(str(day['cash_total'])) == (cash if invested else Decimal('100000'))
        assert Decimal(str(day['nav'])) == (cash + Decimal(2000) if invested else Decimal('100000'))
    changed = deepcopy(data)
    future = changed['tax_rules'].effective_from.eq('2023-08-28')
    changed['tax_rules'].loc[future, ['available_at', 'verified', 'source_url']] = [None, False, None]
    assert_same(original, run(changed, decisions))


@pytest.mark.parametrize('which', ['past', 'future'])
def test_irrelevant_time_rows_cannot_contaminate_any_ledger(which):
    data, decisions = fixture()
    baseline = run(data, decisions)
    index = 0 if which == 'past' else 2
    data['tax_rules'].loc[index, ['available_at', 'verified', 'source_url']] = [None, False, None]
    assert_same(baseline, run(data, decisions))


@pytest.mark.parametrize('dimension,value', [
    ('asset_type', 'ETF'), ('market', 'SZSE'),
    ('component', 'DIVIDEND_TAX'), ('instrument_id', 'SYNTHETIC_OTHER')])
def test_provably_unrelated_scope_cannot_contaminate_current_fee(dimension, value):
    data, decisions = fixture(scoped=True)
    baseline = run(data, decisions)
    extra = data['tax_rules'].iloc[1].to_dict()
    extra.update(available_at=None, verified=False, source_url=None)
    extra[dimension] = value
    data['tax_rules'] = pd.concat([data['tax_rules'], pd.DataFrame([extra])], ignore_index=True)
    assert_same(baseline, run(data, decisions))


@pytest.mark.parametrize('field,value', [
    ('available_at', None), ('available_at', '2023-08-01T09:31:00+08:00'),
    ('available_at', '2023-08-01T08:00:00'),
    ('source_url', None), ('verified', False),
    ('stamp_duty_sell', None), ('transfer_fee_both', -1),
    ('effective_from', None), ('effective_to', None),
    ('effective_from', '2023-08-02'),
])
def test_applicable_uncertainty_never_becomes_a_valid_fee(field, value):
    data, decisions = fixture()
    data['tax_rules'].loc[1, field] = value
    assert_blocked(run(data, decisions))


@pytest.mark.parametrize('field,value', [
    ('asset_type', None), ('market', None), ('component', None),
    ('instrument_id', None), ('market', 'UNREGISTERED_MARKET'),
])
def test_unknown_scope_not_silently_discarded(field, value):
    data, decisions = fixture(scoped=True)
    extra = data['tax_rules'].iloc[1].to_dict()
    extra[field] = value
    data['tax_rules'] = pd.concat([data['tax_rules'], pd.DataFrame([extra])], ignore_index=True)
    assert_blocked(run(data, decisions))


@pytest.mark.parametrize('invalid', ['verified_duplicate', 'unverified_duplicate', 'future_public_duplicate'])
def test_applicable_overlap_cannot_fallback_to_one_valid_row(invalid):
    data, decisions = fixture()
    extra = data['tax_rules'].iloc[1].to_dict()
    if invalid == 'unverified_duplicate':
        extra['verified'] = False
    if invalid == 'future_public_duplicate':
        extra['available_at'] = '2023-08-01T09:31:00+08:00'
    data['tax_rules'] = pd.concat([data['tax_rules'], pd.DataFrame([extra])], ignore_index=True)
    assert_blocked(run(data, decisions))


def test_row_order_invariance_for_valid_and_poisoned_future_rows():
    data, decisions = fixture(scoped=True)
    baseline = run(data, decisions)
    data['tax_rules'].loc[2, ['available_at', 'verified', 'source_url']] = [None, False, None]
    for order in ([2, 1, 0], [1, 0, 2], [0, 2, 1]):
        permuted = deepcopy(data)
        permuted['tax_rules'] = data['tax_rules'].iloc[order].reset_index(drop=True)
        assert_same(baseline, run(permuted, decisions))


@pytest.mark.parametrize('multiplier,expected_commission,expected_nav', [(1, 5, '99987.96'), (3, 15, '99967.96')])
def test_hand_roundtrip_tax_and_commission_stress(multiplier, expected_commission, expected_nav):
    data, decisions = fixture()
    sale = deepcopy(decisions[0])
    sale.update(decision_date=data['calendar'][22], execution_date=data['calendar'][23], weights={})
    sale['fixed_quantities'] = {next(iter(sale['fixed_quantities'])): 0}
    result = run(data, decisions + [sale], multiplier)
    assert result['fills']['quantity'].tolist() == [200, 200]
    assert result['fills']['commission'].tolist() == [expected_commission] * 2
    assert result['fills']['stamp_duty'].tolist() == [0, 2]
    assert result['fills']['transfer_fee'].tolist() == [.02, .02]
    # The engine stores aggregate cash in binary floats; compare currency cents.
    assert Decimal(str(result['nav'].iloc[-1]['nav'])).quantize(Decimal('.01')) == Decimal(expected_nav)


def test_etf_tax_scope_is_independent_of_incomplete_stock_rules():
    data, decisions = fixture()
    data['instruments']['asset_type'] = 'ETF'
    data['tax_rules'].loc[:, ['available_at', 'verified', 'source_url']] = [None, False, None]
    result = run(data, decisions)
    assert result['fills']['quantity'].tolist() == [200]
    assert result['fills']['fees'].tolist() == [5]
    assert Decimal(str(result['nav'].iloc[-1]['nav'])) == Decimal('99995.0')
