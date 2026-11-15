"""Independent M4 temporal/rights counterexamples; no market performance."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.data import master_asof
from quant_research.strategy import _prepare, _snapshot
from quant_research.execution import run_backtest


def row(revision='a', start='2020-01-01', end=None, known='2019-12-01T21:00:00+08:00', allowed=True, parent=None):
    return dict(instrument_id='A', asset_type='ETF', board='ETF', listed_on='2010-01-01',
                delisted_on=None, account_verified=allowed, benchmark_id='CSI300', industry='BROAD',
                lot_size=100, tick_size=.001, t_plus=1, status='NORMAL', revision_id=revision,
                supersedes_id=parent, effective_from=start, effective_to=end, available_at=known)


def selected(records, at):
    frame = pd.DataFrame(records)
    a = master_asof(SimpleNamespace(instruments=frame), pd.Timestamp(at))
    b = _snapshot(_prepare(frame), pd.Timestamp(at), ['instrument_id'], master=True)
    assert list(a.revision_id) == list(b.revision_id)
    return list(a.revision_id)


@pytest.mark.parametrize('allowed', [True, False])
@pytest.mark.parametrize('linked', [True, False])
def test_future_state_does_not_advance_economic_clock(allowed, linked):
    rows = [row(allowed=not allowed), row('b', '2020-02-01', known='2020-01-15T21:00:00+08:00',
                                        allowed=allowed, parent='a' if linked else None)]
    assert selected(rows, '2020-01-31T21:00:00+08:00') == ['a']
    assert selected(rows, '2020-02-01T00:00:00+08:00') == ['b']


def test_end_exclusive_no_predecessor_resurrection():
    rows = [row(), row('b', '2020-02-01', '2020-03-01', '2020-01-15T21:00:00+08:00', parent='a')]
    assert selected(rows, '2020-02-29T23:59:59+08:00') == ['b']
    assert selected(rows, '2020-03-01T00:00:00+08:00') == []


def test_old_interval_correction_does_not_erase_new_state():
    rows = [row(end='2020-02-01'), row('b', '2020-02-01', known='2020-01-20T21:00:00+08:00'),
            row('a2', '2020-01-01', '2020-02-01', '2020-03-01T21:00:00+08:00', parent='a')]
    assert selected(rows, '2020-03-02T21:00:00+08:00') == ['b']


def test_visible_correction_shortens_interval_without_reviving_original():
    rows = [row(), row('a2', '2020-01-01', '2020-02-01', '2020-02-05T21:00:00+08:00', parent='a')]
    assert selected(rows, '2020-02-04T21:00:00+08:00') == ['a']
    assert selected(rows, '2020-02-05T21:00:00+08:00') == []


def test_timezone_and_unknown_upper_bound():
    rows = [row(start='2020-02-01')]
    assert selected(rows, '2020-01-31T15:59:59+00:00') == []
    assert selected(rows, '2020-01-31T16:00:00+00:00') == ['a']
    assert selected(rows, '2024-12-31T21:00:00+08:00') == ['a']


def test_same_state_same_clock_conflict_rejected():
    with pytest.raises(ValueError):
        selected([row(), row('b', allowed=False)], '2020-01-31T21:00:00+08:00')


def account(master):
    days = pd.bdate_range('2020-01-01', periods=35).strftime('%Y-%m-%d').tolist()
    bars = pd.DataFrame([dict(instrument_id='A', date=d, open=10., high=11., low=9., close=10.,
                             volume=1e7, amount=1e8, upper_limit=11., lower_limit=9., suspended=False,
                             available_at=d+'T16:00:00+08:00') for d in days])
    return dict(calendar=days, instruments=pd.DataFrame(master), bars=bars, actions=pd.DataFrame())


def instruction(data, index, buy=True):
    return dict(decision_date=data['calendar'][index], execution_date=data['calendar'][index+1],
                weights={'A': .3} if buy else {}, reference_prices={'A': 10.}, adv20={'A': 1e8})


def test_expired_metadata_does_not_authorize_sell_or_release_cash():
    data = account([row(end='2020-02-03')])
    result = run_backtest(data, [instruction(data, 20), instruction(data, 24, False)], 100000)
    assert list(result['fills'].side) == ['BUY']
    positions = result['positions']
    assert positions.iloc[-1].quantity == positions.iloc[0].quantity > 0
    assert result['nav'].iloc[-1].cash_total == result['nav'].loc[result['nav'].date == data['calendar'][21], 'cash_total'].iloc[0]


def test_etf_standalone_delisting_keeps_uncertain_rights_no_cash():
    data = account([row()])
    ex = data['calendar'][25]
    data['actions'] = pd.DataFrame([dict(action_id='exit', instrument_id='A', action_type='DELISTING',
                                       ex_date=ex, available_at=ex+'T08:00:00+08:00', recovery_per_share=None)])
    result = run_backtest(data, [instruction(data, 20)], 100000)
    later = result['nav'].loc[result['nav'].date >= ex]
    assert later.valuation_uncertainty.all()
    assert (later.holdings_value == 0).all()
    assert (later.receivables == 0).all()
    assert later.cash_total.nunique() == 1
    assert result['positions'].iloc[-1].quantity > 0
    assert not result['accounting_timing_eligible']
