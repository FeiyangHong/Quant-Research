"""Explicit accounting replay contract; no strategy or admission entry point."""
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
from .equity_accounting import EquityAccountingBlocked, daily_limit_ratio

REPLAY_TAG = "ENGINEERING_REPLAY_NOT_STRATEGY_PERFORMANCE"


def validate_replay(dataset, calendar):
    manifest = dataset.get('manifest', {}) if isinstance(dataset, dict) else dataset.manifest
    if manifest.get('purpose') != REPLAY_TAG or manifest.get('synthetic') is not True:
        raise EquityAccountingBlocked('Engineering replay currently requires explicitly synthetic fixtures; real admission remains blocked')
    if not calendar or any(not '2016-01-01' <= day <= '2024-12-31' for day in calendar):
        raise EquityAccountingBlocked('Engineering replay scope 2016--2024; final holdout is locked')
    if manifest.get('account_type') != 'DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE':
        raise EquityAccountingBlocked('Engineering replay requires explicit reviewed taxpayer')


def verify_daily_limits(meta, row, day):
    """Validate supplied raw limits using point-in-time rule/reference evidence."""
    if row is None or row.get('limit_terms_verified') is not True or not str(row.get('limit_source_url', '')).startswith('https://'):
        raise EquityAccountingBlocked('HISTORICAL_LIMIT_EVIDENCE_REQUIRED')
    known = pd.Timestamp(row.get('limit_rule_available_at'))
    if pd.isna(known) or known.tzinfo is None or known > pd.Timestamp(day + 'T09:30:00+08:00'):
        raise EquityAccountingBlocked('HISTORICAL_LIMIT_NOT_KNOWN_AT_OPEN')
    ratio = daily_limit_ratio(board=meta.get('board'), day=day, is_st=meta.get('is_st'),
        listed_on=meta.get('listed_on'), listing_session=row.get('listing_session'),
        ipo_regime=meta.get('ipo_regime'), special_session=row.get('special_session', False),
        delisting_started_on=meta.get('delisting_started_on'))
    if ratio is None:
        raise EquityAccountingBlocked('UNBOUNDED_IPO_SESSION_UNSUPPORTED')
    try:
        reference, tick = Decimal(str(row.get('limit_reference_price'))), Decimal(str(meta.get('tick_size')))
        if not reference.is_finite() or reference <= 0 or tick <= 0:
            raise ValueError
        expected = [(reference * (1 + sign * ratio) / tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick for sign in (1, -1)]
        if expected != [Decimal(str(row.get('upper_limit'))), Decimal(str(row.get('lower_limit')))]:
            raise EquityAccountingBlocked('HISTORICAL_LIMIT_PRICE_MISMATCH')
    except (ValueError, ArithmeticError):
        raise EquityAccountingBlocked('HISTORICAL_LIMIT_REFERENCE_REQUIRED') from None


def synthetic_fixture(board='MAIN', case='ordinary_special'):
    """Invented prices/calendar/actions, explicitly not records of a security.

    Fixed 200 then 400 shares; both cash dividends belong to both FIFO lots.
    The calendar is pandas weekdays, NOT a verified exchange calendar.
    """
    if board not in ('MAIN', 'CHINEXT') or case not in ('ordinary_special', 'late_exit', 'unknown_rights'):
        raise ValueError('Unknown synthetic replay case')
    calendar = pd.bdate_range('2023-07-03', periods=70).strftime('%Y-%m-%d').tolist()
    source = 'https://example.test/m4-invented-fixture-not-real-evidence'
    sid = 'SYNTHETIC_' + board
    meta = dict(instrument_id=sid, asset_type='STOCK', board=board, listed_on='2010-01-04',
        delisted_on=None, available_at='2015-01-01T00:00:00+08:00', account_verified=True,
        industry='SYNTHETIC_INDUSTRY', lot_size=100, tick_size=.01, t_plus=1,
        status='NORMAL', is_st=False, ipo_regime='APPROVAL')
    ratio = .1 if board == 'MAIN' else .2
    bars = [dict(date=day, instrument_id=sid, open=10., high=11., low=9., close=10.,
        volume=10000000, amount=100000000, upper_limit=10*(1+ratio), lower_limit=10*(1-ratio),
        suspended=(case=='late_exit' and 41 <= i < 46), available_at=day+'T16:00:00+08:00',
        limit_terms_verified=True, limit_source_url=source, limit_rule_available_at=day+'T08:00:00+08:00',
        listing_session=3000+i, special_session=False, limit_reference_price=10.) for i, day in enumerate(calendar)]
    actions = [dict(action_id=kind, instrument_id=sid, action_type='CASH_DIVIDEND',
        record_date=calendar[rec], ex_date=calendar[rec+1], pay_date=calendar[rec+3],
        available_at=calendar[rec-1]+'T20:00:00+08:00', cash_per_share=amount,
        cash_dividend_kind=kind, tax_category='ORDINARY_CASH_DIVIDEND', terms_verified=True,
        source_url=source, settlement_mode='SYNTHETIC_SCHEDULED_SIMULATION')
        for kind, rec, amount in [('ORDINARY', 24, .25), ('SPECIAL', 31, .75)]]
    if case == 'unknown_rights':
        actions.append(dict(action_id='DEAD', instrument_id=sid, action_type='DELISTING',
            ex_date=calendar[42], available_at=calendar[41]+'T20:00:00+08:00', recovery_per_share=None))
    fees = [dict(effective_from=a, effective_to=b, stamp_duty_sell=s, transfer_fee_both=t,
        verified=True, source_url=source, available_at=known) for a,b,s,t,known in [
            ('2016-01-01','2022-04-28',.001,.00002,'2015-07-09T21:00:00+08:00'),
            ('2022-04-29','2023-08-27',.001,.00001,'2022-04-28T21:00:00+08:00'),
            ('2023-08-28','2024-12-31',.0005,.00001,'2023-08-27T21:00:00+08:00')]]
    targets = [(20,200),(22,400)] + ([] if case=='unknown_rights' else [(40,0)])
    decisions = [dict(decision_date=calendar[i], execution_date=calendar[i+1], weights={sid:.04} if qty else {},
        reference_prices={sid:10.}, adv20={sid:1e8}, fixed_quantities={sid:qty}) for i,qty in targets]
    # Five failed actual sale attempts stop retries. For the late-exit case a
    # new fixed instruction on session46 creates the verifiable later exit.
    if case == 'late_exit':
        decisions.append(dict(decision_date=calendar[46], execution_date=calendar[47], weights={},
            reference_prices={sid:10.}, adv20={sid:1e8}, fixed_quantities={sid:0}))
    tax = 80 if case=='ordinary_special' else 40
    debit_index = 42 if case=='ordinary_special' else 48
    settlements = [] if case=='unknown_rights' else [dict(settlement_id='MODELED_TAX',
        debit_date=calendar[debit_index], amount=tax, terms_verified=True, source_url=source,
        mode='RULE_BASED_SIMULATION')]
    dataset = dict(calendar=calendar, instruments=pd.DataFrame([meta]), bars=pd.DataFrame(bars),
        actions=pd.DataFrame(actions), tax_rules=pd.DataFrame(fees), tax_settlements=settlements,
        manifest=dict(synthetic=True, purpose=REPLAY_TAG,
            account_type='DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE',
            provenance='All securities, prices, calendar, event terms and dates invented; rules are test scenarios'))
    return dataset, decisions
