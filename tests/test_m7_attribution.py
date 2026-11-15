"""Independent small account: fees and one receivable are each counted once."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('m7_evaluate', Path(__file__).parents[1] / 'scripts/m7_evaluate.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_known_three_day_account_reconciles_dividend_and_fees():
    tables = dict(
        nav=[dict(date='2023-01-03', nav=99995), dict(date='2023-01-04', nav=100105),
             dict(date='2023-01-05', nav=100100)],
        positions=[dict(date='2023-01-03', instrument_id='A', market_value=1000),
                   dict(date='2023-01-04', instrument_id='A', market_value=1100)],
        fills=[dict(date='2023-01-03', instrument_id='A', side='BUY', notional=1000, fees=5),
               dict(date='2023-01-05', instrument_id='A', side='SELL', notional=1100, fees=5)],
        cash_events=[dict(date='2023-01-04', instrument_id='A', event='DIVIDEND_RECEIVABLE', amount=10),
                     dict(date='2023-01-05', instrument_id='A', event='DIVIDEND_PAID', amount=10)])
    daily, annual, fees, error = MODULE.reconcile(tables, 100000, ['A', 'B'])
    assert [r['A'] for r in daily] == [-5, 110, -5]
    assert annual['2023'] == {'A': 100, 'B': 0}
    assert error == 0
    tables['nav'][-1]['nav'] += 10
    with pytest.raises(ValueError, match='reconciliation'):
        MODULE.reconcile(tables, 100000, ['A', 'B'])
