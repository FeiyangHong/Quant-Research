"""M6 fixed M5 real cases, per-case source gates and independent input oracle.

Offline only. Reuses M5 source adapter and Decimal oracle without modifying
their files or M5 outputs. No strategy returns or performance evaluation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

import m5_execution as original
from quant_research.execution import run_backtest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/m6_stock_execution'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding='utf-8')


def blocked_expected(calendar):
    return pd.DataFrame([dict(date=day, quantity=0, sellable_quantity=0,
        cash_total=10000000., receivables=0., holdings_value=0.,
        dividend_tax_payable=0., dividend_tax_paid=0., cash_reserved=0.,
        potential_terminal_tax=0., cash_available=10000000., nav=10000000.,
        hypothetical_liquidation_nav=10000000., entitled_quantity=0,
        unknown_right_quantity=0) for day in calendar])


def main():
    gates = original.read(OUT / 'case_rule_gates.json')
    registration = original.read(original.OUT / 'registration.json')
    statuses = []
    for case in registration['cases']:
        name = case['case_id']
        gate = gates['cases'][name]
        passed = all(value['status'] == 'PASS' for value in gate['components'].values())
        rules = original.read(OUT / (name + '_rules.json'))
        if rules['verified'] is not passed:
            raise ValueError('Case source gate and adapter verification disagree')
        dataset, decisions = original.build(case, rules)
        dataset['manifest'].update(m6_case_source_gate=gate,
            rule_scope='Fixed original M5 case only; not general stock admission')
        # This existing oracle independently computes cash/fees/FIFO/events
        # from raw inputs and unchanged fixed instructions. It never reads the
        # main result or invokes production rate/accounting helpers.
        expected, predicted, settlements = original.independent_expected(case, dataset)
        if not passed:
            expected['status'] = 'CONDITIONAL_UNVERIFIED_RULE_INPUTS_NOT_REAL_RECONCILIATION'
            expected.to_csv(OUT / (name + '_conditional_expected.csv'), index=False)
            save(OUT / (name + '_conditional_predicted_fills.json'),
                 dict(status='CONDITIONAL_UNVERIFIED_RULE_INPUTS', fills=predicted, not_actual_fills=True))
            expected, predicted, settlements = blocked_expected(dataset['calendar']), [], []
        dataset['tax_settlements'] = settlements
        expected.to_csv(OUT / (name + '_expected.csv'), index=False)
        save(OUT / (name + '_predicted_fills.json'), predicted)
        snapshot = dict(calendar=dataset['calendar'], manifest=dataset['manifest'],
            decisions=decisions, tax_settlements=settlements,
            **{key: dataset[key].astype(object).where(dataset[key].notna(), None).to_dict('records')
               for key in ['instruments', 'bars', 'actions', 'tax_rules']})
        save(OUT / (name + '_inputs.json'), snapshot)
        result = run_backtest(dataset, decisions, registration['initial_cash_cny'],
                              slippage_multiplier=0, engineering_replay=True)
        differences = original.reconcile(result, expected)
        actual = result['fills'].to_dict('records')
        if len(actual) != len(predicted):
            differences.append(dict(field='fill_count', expected=len(predicted), actual=len(actual)))
        else:
            for expected_fill, actual_fill in zip(predicted, actual):
                for key, value in expected_fill.items():
                    if actual_fill[key] != value:
                        differences.append(dict(field='fill.' + key, expected=value, actual=actual_fill[key]))
        for key, table in result.items():
            if isinstance(table, pd.DataFrame):
                table.to_csv(OUT / (name + '_' + key + '.csv'), index=False)
        statuses.append(dict(case=name, status='FAIL' if differences else 'PASS' if passed else 'BLOCKED',
            source_gate_passed=passed, daily_rows=len(expected), differences=differences,
            predicted_fills=predicted, actual_fill_count=len(actual),
            has_actual_event_position=bool(result['positions'].quantity.max() > 0),
            missing_components=[key for key, value in gate['components'].items() if value['status'] != 'PASS'],
            broker_ledger_verification='UNVERIFIED'))
    files = ['src/quant_research/execution.py', 'scripts/m5_execution.py',
             'scripts/m6_stock_execution.py', 'reports/m5_execution/registration.json',
             'reports/m5_execution/registration_addendum.json']
    save(OUT / 'results.json', dict(purpose='ENGINEERING_ACCOUNTING_VALIDATION',
        data_origin='REAL', synthetic=False, performance_evidence=False,
        real_strategy_runs=0, holdout_access=False,
        observed_at=datetime.now(timezone.utc).isoformat(),
        command='.venv/Scripts/python.exe scripts/m6_stock_execution.py',
        original_registration_unchanged=True,
        code_and_registration_hashes={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
        cases=statuses))
    print(json.dumps(statuses, indent=2))
    if any(s['status'] == 'FAIL' for s in statuses):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
