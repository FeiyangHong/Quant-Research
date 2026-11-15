"""Independent fixed-matrix and information-boundary assertions."""
import hashlib
import itertools
import json
from pathlib import Path

from quant_research.data import date_only_available_at

ROOT = Path(__file__).resolve().parents[2]
IDS = ['sz.159936', 'sz.159938', 'sz.159939', 'sz.159940',
       'sz.159944', 'sz.159945', 'sz.159946']


def test_registered_full32_no_profit_gate_and_separate_bootstrap():
    doc = json.loads((ROOT / 'reports/m7_cohort/EXPERIMENT_REGISTRY.json').read_text('utf-8'))
    assert doc['cohort'] == IDS
    rows = doc['trials']
    assert len(rows) == 32 and len({r['trial_id'] for r in rows}) == 32
    assert {(r['period'], r['variant'], r['path']) for r in rows} == set(itertools.product(
        ['development', 'validation'], ['E0', 'R0', 'E1', 'R1'],
        ['base', 'cost_2x', 'cost_3x', 'delay_1_session']))
    for row in rows:
        assert row['initial_cash'] == 100000 and row['risk_scaling'] is False
        assert row['scope'] == 'R1I_FIXED_COHORT_V1'
        assert row['statutory_tax_multiplier'] == 1
        assert row['annual_incremental_cost'] is None
        assert row['signal_release_delay'] == 1
        expected = {'base': (1, 1), 'cost_2x': (2, 1), 'cost_3x': (3, 1), 'delay_1_session': (1, 2)}[row['path']]
        assert (row['cost_multiplier'], row['execution_delay']) == expected
        assert row['slippage_multiplier'] == expected[0]
    assert doc['base_checkpoint'] == 'ACCOUNTING_AND_DATA_VALIDITY_ONLY_NOT_PROFIT_GATE'
    assert doc['no_final_holm'] is True
    assert doc['primary'] == 'validation 100000 base R0-E0'
    assert doc['bootstrap']['main_block'] == 60
    assert doc['bootstrap']['sensitivity_blocks'] == [20, 120]
    assert doc['bootstrap']['repetitions'] == 5000
    assert doc['bootstrap']['seed'] == 20261114
    assert doc['bootstrap']['synchronous_across_rules'] is True
    assert doc['bootstrap']['periods_separate'] is True


def test_hand_calendar_boundary_does_not_backdate_cohort():
    # Hand-selected exchange sessions; no weekday-generation oracle.
    sessions = ['2015-12-31', '2016-01-04', '2016-01-05', '2016-01-06',
                '2016-01-28', '2016-01-29', '2016-02-01', '2016-02-02', '2016-02-03']
    assert date_only_available_at('2016-01-04', sessions) == '2016-01-05T21:00:00+08:00'
    reg = json.loads((ROOT / 'reports/m7_cohort/EXPERIMENT_REGISTRY.json').read_text('utf-8'))
    assert reg['cohort_available_at'] == '2016-01-05T21:00:00+08:00'
    assert reg['first_anchor_not_before'] == '2016-01-29'


def test_old_dynamic_r1i_and_r1b_frozen():
    # Use Git identity rather than deriving a new expectation from changed files.
    import subprocess
    frozen = ['reports/m6_r1i/EXPERIMENT_REGISTRY.json',
              'reports/m6_r1i/matrix_status.json']
    for relative in frozen:
        old = subprocess.check_output(['git', 'show', 'da1003a:' + relative], cwd=ROOT)
        assert (ROOT / relative).read_bytes() == old
    summary = ROOT / 'reports/real_data_phase3/summary.json'
    if summary.exists():
        assert hashlib.sha256(summary.read_bytes()).hexdigest() == 'c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb'
