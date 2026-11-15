"""Synthetic fixed-position account reconciliation, never a strategy runner."""
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_research.engineering_replay import REPLAY_TAG, synthetic_fixture
from quant_research.execution import run_backtest


def independent_expected(calendar, case):
    """Closed-form fixture oracle. Does not read fills or call engine formulas.

    Two 200-share buys at CNY10: each costs 2005.02. Dividends are
    400*.25=100 and 400*.75=300. Disposal grosses 4000, costs 7.04.
    Each 200-share lot claims 200 gross; taxable at 20% through its
    natural month anniversary, 10% thereafter. No dynamic target model.
    """
    cash, receivable, paid, payable = Decimal('100000'), Decimal(0), Decimal(0), Decimal(0)
    shares = 0
    sale = 41 if case == 'ordinary_special' else 47 if case == 'late_exit' else None
    debit = None if sale is None else sale + 1
    rows = []
    for i, day in enumerate(calendar):
        if i in (21,23):
            shares += 200
            cash -= Decimal('2005.02')
        if i == 25:
            receivable += 100
        if i == 27:
            receivable -= 100
            cash += 100
        if i == 32:
            receivable += 300
        if i == 34:
            receivable -= 300
            cash += 300
        if i == sale:
            shares = 0
            cash += Decimal('3992.96')
            payable = Decimal('80') if sale == 41 else Decimal('40')
        if i == debit:
            cash -= payable
            paid += payable
            payable = Decimal(0)
        # Claim grosses per lot after each record close: 50 then 200.
        gross_each = Decimal('200') if i >= 31 else Decimal('50') if i >= 24 else Decimal(0)
        potential = Decimal(0)
        if shares:
            for acquired_index in (21,23):
                if i < acquired_index:
                    continue
                acquired = date.fromisoformat(calendar[acquired_index])
                month_end = acquired.replace(month=acquired.month + 1)
                potential += gross_each * (Decimal('.2') if date.fromisoformat(day) <= month_end else Decimal('.1'))
        reserve = payable + potential
        dead = case == 'unknown_rights' and i >= 42
        value = Decimal(0) if dead else shares * Decimal(10)
        nav = cash + value + receivable - payable
        rows.append(dict(date=day, quantity=shares, sellable_quantity=shares - (200 if i in (21,23) else 0),
            cash_total=float(cash), receivables=float(receivable), holdings_value=float(value),
            dividend_tax_payable=float(payable), dividend_tax_paid=float(paid), cash_reserved=float(reserve),
            cash_available=float(max(Decimal(0), cash-reserve)), nav=float(nav),
            hypothetical_liquidation_nav=float(nav-potential),
            ordinary_entitlement=400 if i>=24 else 0, special_entitlement=400 if i>=31 else 0,
            unknown_right_quantity=shares if dead else 0))
    return pd.DataFrame(rows)


def reconcile(result, expected):
    actual = result['nav'].set_index('date')
    failures = []
    for row in expected.to_dict('records'):
        day = row['date']
        positions = result['positions'].query('date == @day')
        for field in ('quantity','sellable_quantity'):
            got = positions[field].sum()
            if got != row[field]:
                failures.append(dict(date=day, field=field, expected=row[field], actual=float(got)))
        for field in ('cash_total','receivables','holdings_value','dividend_tax_payable','dividend_tax_paid',
                      'cash_reserved','cash_available','nav','hypothetical_liquidation_nav'):
            got = actual.loc[day, field]
            if abs(got-row[field]) > .0000001:
                failures.append(dict(date=day, field=field, expected=row[field], actual=float(got)))
        for action, field in [('ORDINARY','ordinary_entitlement'), ('SPECIAL','special_entitlement')]:
            claims = result['dividend_entitlements']
            got = claims.loc[(claims.date == day) & (claims.action_id == action), 'entitled_quantity'].sum()
            if got != row[field]:
                failures.append(dict(date=day, field=field, expected=row[field], actual=float(got)))
        rights = result['rights']
        got = rights.loc[(rights.date == day) & (rights.status == 'UNPRICED_DELISTED_RIGHT'), 'entitled_quantity'].sum()
        if got != row['unknown_right_quantity']:
            failures.append(dict(date=day, field='unknown_right_quantity', expected=row['unknown_right_quantity'], actual=float(got)))
    return failures


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'reports/m4_correctness/engineering_replay'
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for board in ('MAIN','CHINEXT'):
        for case in ('ordinary_special','late_exit','unknown_rights'):
            data, decisions = synthetic_fixture(board, case)
            result = run_backtest(data, decisions, 100000, slippage_multiplier=0, engineering_replay=True)
            expected = independent_expected(data['calendar'], case)
            failures = reconcile(result, expected)
            name = board.lower()+'_'+case
            for key, table in result.items():
                if isinstance(table, pd.DataFrame):
                    table.to_csv(output / (name+'_'+key+'.csv'), index=False)
            expected.to_csv(output / (name+'_independent_expected.csv'), index=False)
            snapshot = dict(calendar=data['calendar'], manifest=data['manifest'], decisions=decisions,
                tax_settlements=data['tax_settlements'], **{key:data[key].astype(object).where(data[key].notna(), None).to_dict('records')
                    for key in ('instruments','bars','actions','tax_rules')})
            (output / (name+'_inputs.json')).write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
            results.append(dict(case=name, daily_rows=len(expected), reconciliation_failures=failures,
                status='PASS' if not failures else 'FAIL', purpose=REPLAY_TAG, synthetic=True,
                source_class='INVENTED_TEST_INPUTS', real_market_evidence=False))
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())
              if p.suffix in ('.csv','.json') and p.name != 'provenance.json'}
    source_paths = ['src/quant_research/'+name+'.py' for name in
        ('temporal','data','strategy','execution','equity_accounting','engineering_replay')]
    source_paths += ['scripts/replay_equity_engineering.py', 'tests/test_m4_execution.py']
    source_hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in source_paths}
    provenance = dict(purpose=REPLAY_TAG, synthetic=True, performance_evidence=False,
        real_strategy_runs=0, holdout_access=False, source_note='All six fixtures are invented, including weekday calendars and source URL attestations. No real source is relabeled synthetic.',
        limitations=['No real-event ledger acceptance', 'Tax cash date and per-disposal rounding are explicit simulation conventions',
            'Real R2/R3 admission remains blocked', 'Unsupported share/rights/merger actions remain blocked'],
        cases=results, artifact_sha256=hashes, source_sha256=source_hashes)
    (output/'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))
    if any(case['status'] != 'PASS' for case in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
