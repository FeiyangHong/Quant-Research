"""Synthetic dual-clock regressions; not performance evidence."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.data import master_asof
from quant_research.execution import run_backtest
from quant_research.strategy import _prepare, _snapshot
from quant_research.temporal import master_record, master_snapshot, TemporalStateError
from quant_research.engineering_replay import synthetic_fixture, REPLAY_TAG
from quant_research.execution import ExecutionBlockedError
from test_equity_execution import stock_fixture, decision, rules


def test_published_future_grant_does_not_trade_early():
    data = stock_fixture()
    data['instruments']['account_verified'] = False
    update = data['instruments'].iloc[0].to_dict()
    update.update(account_verified=True, available_at=data['calendar'][19] + 'T20:00:00+08:00',
                  effective_from=data['calendar'][25])
    data['instruments'] = pd.concat([data['instruments'], pd.DataFrame([update])], ignore_index=True)
    at = pd.Timestamp(data['calendar'][20] + 'T21:00:00+08:00')
    assert not bool(master_asof(SimpleNamespace(**data), at).iloc[0].account_verified)
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result['fills'].empty


def test_execution_future_revocation_is_not_early_risk_exit():
    data = stock_fixture()
    update = data['instruments'].iloc[0].to_dict()
    update.update(account_verified=False, available_at=data['calendar'][22] + 'T20:00:00+08:00',
                  effective_from=data['calendar'][27])
    data['instruments'] = pd.concat([data['instruments'], pd.DataFrame([update])], ignore_index=True)
    result = run_backtest(data, [decision(data)], 100000, tax_rules=rules())
    assert result['orders'].query("intent_type == 'RISK_EXIT'").iloc[0].decision_date == data['calendar'][27]


def test_expiry_retains_position_and_blocks_unknown_rule_sales():
    data = stock_fixture()
    data['instruments']['effective_to'] = data['calendar'][24]
    result = run_backtest(data, [decision(data), decision(data, 25, 0)], 100000, tax_rules=rules())
    assert list(result['fills'].side) == ['BUY']
    assert result['positions'].iloc[-1].quantity == result['fills'].iloc[0].quantity
    assert 'UNKNOWN_INSTRUMENT_ASOF' in set(result['rejected_orders'].reason)


def test_standalone_etf_delisting_marks_unknown_rights():
    data = stock_fixture()
    data['instruments']['asset_type'] = 'ETF'
    ex = data['calendar'][24]
    data['actions'] = pd.DataFrame([dict(action_id='X', instrument_id='A', action_type='DELISTING',
        ex_date=ex, available_at=ex + 'T08:00:00+08:00', recovery_per_share=None)])
    result = run_backtest(data, [decision(data)], 100000)
    assert result['nav'].iloc[-1].valuation_uncertainty
    assert not result['accounting_timing_eligible']
    assert result['positions'].iloc[-1].quantity > 0
    assert not result['cash_events'].event.isin(['LIQUIDATION_PAID', 'DIVIDEND_PAID']).any()


def state(start=None, end=None, known='2020-01-01T08:00:00+08:00', **extra):
    return dict(instrument_id='A', effective_from=start, effective_to=end, available_at=known, **extra)


def test_shared_half_open_endpoints_timezone_and_unbounded_missing():
    frame = pd.DataFrame([state('2020-01-02','2020-01-03')])
    for stamp, expected in [('2020-01-01T15:59:59Z',False), ('2020-01-01T16:00:00Z',True),
                            ('2020-01-02T15:59:59Z',True), ('2020-01-02T16:00:00Z',False)]:
        cutoff = pd.Timestamp(stamp)
        assert (not master_snapshot(frame,cutoff).empty) is expected
        assert (not _snapshot(_prepare(frame),cutoff,['instrument_id'],True).empty) is expected
        assert (not master_asof(SimpleNamespace(instruments=frame),cutoff).empty) is expected
    assert master_record([state()], pd.Timestamp('2024-01-01T00:00:00+08:00')) is not None


def test_expired_successor_never_revives_old_unbounded_state():
    rows = [state(), state('2020-02-01','2020-03-01', known='2020-01-15T00:00:00+08:00')]
    assert master_record(rows, pd.Timestamp('2020-03-01T00:00:00+08:00')) is None


def test_old_interval_correction_does_not_erase_current_state():
    rows = [state('2020-01-01','2020-02-01', revision_id='A'),
        state('2020-02-01',known='2020-01-15T00:00:00+08:00',revision_id='B',supersedes_id='A'),
        state('2020-01-01','2020-01-30', known='2020-03-01T00:00:00+08:00',revision_id='A2',supersedes_id='A')]
    # Transition and correction can legitimately both point at A. They are
    # not two corrections of the same effective interval.
    assert master_record(rows,pd.Timestamp('2020-03-02T00:00:00+08:00'))['revision_id'] == 'B'


def test_future_linked_transition_and_shifted_correction_are_distinct():
    rows = [state(revision_id='A'), state('2020-02-01', known='2020-01-15T00:00:00+08:00',
        revision_id='B', supersedes_id='A')]
    at = pd.Timestamp('2020-01-20T00:00:00+08:00')
    assert master_record(rows,at)['revision_id'] == 'A'
    rows[1]['revision_kind'] = 'CORRECTION'
    assert master_record(rows,at) is None


def test_same_announcement_distinct_intervals_and_conflict_failclosed():
    rows = [state('2020-01-01','2020-02-01'),state('2020-02-01')]
    assert master_record(rows,pd.Timestamp('2020-02-02T00:00:00+08:00'))['effective_from'] == '2020-02-01'
    with pytest.raises(TemporalStateError,match='Ambiguous'):
        master_record([state(),state()],pd.Timestamp('2020-02-02T00:00:00+08:00'))
    with pytest.raises(TemporalStateError,match='ISO dates'):
        master_record([state('2020-01-01T10:00:00+08:00')],pd.Timestamp('2020-02-02T00:00:00+08:00'))


@pytest.mark.parametrize('board',['MAIN','CHINEXT'])
@pytest.mark.parametrize('case',['ordinary_special','late_exit','unknown_rights'])
def test_main_ledger_daily_independent_fixture_reconciliation(board,case):
    from importlib.util import spec_from_file_location, module_from_spec
    from pathlib import Path
    spec = spec_from_file_location('m4_oracle',Path(__file__).resolve().parents[1]/'scripts/replay_equity_engineering.py')
    oracle = module_from_spec(spec)
    spec.loader.exec_module(oracle)
    data, targets = synthetic_fixture(board,case)
    result = run_backtest(data,targets,100000,slippage_multiplier=0,engineering_replay=True)
    assert result['purpose'] == REPLAY_TAG and not result['performance_evidence']
    assert oracle.reconcile(result,oracle.independent_expected(data['calendar'],case)) == []
    assert result['tax_events'].get('actual_debit_date',pd.Series(dtype=object)).isna().all()
    if case == 'late_exit':
        assert 'SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS' in set(result['rejected_orders'].reason)
    if case == 'unknown_rights':
        assert result['nav'].iloc[-1].valuation_uncertainty


@pytest.mark.parametrize('mutation', ['real','holdout','classification','future_limit','wrong_limit','bonus'])
def test_engineering_evidence_and_unsupported_event_gates(mutation):
    data, targets = synthetic_fixture()
    if mutation == 'real':
        data['manifest']['synthetic'] = False
    elif mutation == 'holdout':
        data['calendar'].append('2025-01-02')
    elif mutation == 'classification':
        data['actions']['tax_category'] = 'UNKNOWN'
    elif mutation == 'bonus':
        data['actions'].loc[0,'action_type'] = 'SPLIT'
        data['actions']['share_factor'] = 2.
    elif mutation == 'future_limit':
        data['bars']['limit_rule_available_at'] = '2024-01-01T00:00:00+08:00'
    elif mutation == 'wrong_limit':
        data['bars']['upper_limit'] = 12.
    if mutation in ('future_limit','wrong_limit'):
        # Failed buys leave no tax liability, so remove this fixture's fixed
        # tax debit; it must not invent liability just to complete the replay.
        data['tax_settlements'] = []
        result = run_backtest(data,targets,100000,engineering_replay=True)
        assert result['fills'].empty
        assert result['rejected_orders'].reason.str.startswith('HISTORICAL_LIMIT').any()
    else:
        with pytest.raises(ExecutionBlockedError):
            run_backtest(data,targets,100000,engineering_replay=True)


def test_terminal_record_close_retains_claim_reserve_without_future_cash():
    data, targets = synthetic_fixture()
    # Cut off exactly on the first record date, before ex-date and payment.
    data['calendar'] = data['calendar'][:25]
    data['bars'] = data['bars'].loc[data['bars'].date <= data['calendar'][-1]]
    data['actions'] = data['actions'].iloc[:1]
    data['tax_settlements'] = []
    result = run_backtest(data,targets[:2],100000,slippage_multiplier=0,engineering_replay=True)
    last = result['nav'].iloc[-1]
    assert last.cash_reserved == 20 and last.receivables == 0
    assert last.dividend_tax_payable == 0 and last.dividend_tax_paid == 0
    assert result['dividend_entitlements'].entitled_quantity.sum() == 400
    assert not result['cash_events'].event.eq('DIVIDEND_PAID').any()


@pytest.mark.parametrize('start,board,ratio', [
    ('2016-01-04','MAIN',.10), ('2016-01-04','CHINEXT',.10),
    ('2020-07-01','CHINEXT',.10), ('2020-08-03','CHINEXT',.20),
    ('2024-11-01','MAIN',.10), ('2024-11-01','CHINEXT',.20)])
def test_integrated_historical_limit_scope_endpoints_and_chinext_reform(start,board,ratio):
    data = stock_fixture(start)
    data['instruments']['board'] = board
    data['instruments']['ipo_regime'] = 'APPROVAL'
    data['manifest'] = synthetic_fixture()[0]['manifest']
    data['bars']['upper_limit'] = 10*(1+ratio)
    data['bars']['lower_limit'] = 10*(1-ratio)
    data['bars']['limit_reference_price'] = 10.
    data['bars']['listing_session'] = 2000
    data['bars']['limit_terms_verified'] = True
    data['bars']['limit_source_url'] = 'https://example.test/invented-fixture'
    data['bars']['limit_rule_available_at'] = data['bars']['date']+'T08:00:00+08:00'
    data['tax_rules'] = synthetic_fixture()[0]['tax_rules']
    result = run_backtest(data,[decision(data)],100000,engineering_replay=True)
    assert list(result['fills'].side) == ['BUY']
    assert result['fills'].purpose.eq(REPLAY_TAG).all()


@pytest.mark.parametrize('fixed', [None, [], ['A'], {'': 100}, {None: 100}, {'A': True},
                                 {'A': -100}, {'A': 100.}, {'A': 101}])
def test_invalid_fixed_targets_are_rejected_before_any_instrument_lookup(fixed):
    data, targets = synthetic_fixture()
    data['actions'] = pd.DataFrame()
    data['tax_settlements'] = []
    targets[0]['weights'] = {}
    targets[0]['fixed_quantities'] = fixed
    with pytest.raises(ExecutionBlockedError, match='mapping'):
        run_backtest(data, targets[:1], 100000, engineering_replay=True)


def test_fixed_targets_may_omit_unused_weight_mapping():
    data, targets = synthetic_fixture()
    data['actions'] = pd.DataFrame()
    data['tax_settlements'] = []
    for target in targets:
        del target['weights']
    result = run_backtest(data, targets, 100000, engineering_replay=True)
    assert list(zip(result['fills'].side, result['fills'].quantity)) == [('BUY',200),('BUY',200),('SELL',400)]
