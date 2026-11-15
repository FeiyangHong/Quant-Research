"""Offline M5 evidence packaging; never runs a strategy or fetches a source."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.budget import atomic_json

OUT = ROOT / 'reports/m5_review'
BASE = '8a9977cb5538a3ffd3c07506035c0dca7c3a0f14'
SUMMARY = 'c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb'
M4_BUDGET = '44658bc3ba757c5bd3951e11106f42631143dac651fb40e089d3b1dbcb0ee8f6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    now = datetime.now(timezone.utc)
    assert digest(ROOT / 'reports/real_data_phase3/results_summary.json') == SUMMARY
    assert digest(ROOT / 'data/raw_m4_equity/budget.json') == M4_BUDGET
    ledger_path = ROOT / 'data/raw_m5_equity/budget.json'
    ledger = read(ledger_path)
    assert len(ledger['attempts']) == 59
    assert ledger['used'] == dict(http_attempts=52, baostock_wire_attempts=7, new_body_bytes=20764840)
    for row in ledger['attempts']:
        path = Path(row['raw_path'])
        assert row['terminal'] and path.stat().st_size == row['byte_count']
        assert digest(path) == row['sha256']
    frozen = OUT / 'budget_final.json'
    if frozen.exists():
        assert frozen.read_bytes() == ledger_path.read_bytes(), 'Never silently replace frozen budget'
    else:
        frozen.write_bytes(ledger_path.read_bytes())
    test_text = (OUT / 'final_pytest.txt').read_text(encoding='utf-8-sig')
    match = re.search(r'(\d+) passed(?:, (\d+) skipped)?(?:, .*?)? in ([\d.]+)s', test_text)
    assert match and 'FAILED ' not in test_text, 'Successful final suite receipt required'
    execution = read(ROOT / 'reports/m5_execution/provenance.json')
    finance = read(ROOT / 'reports/m5_financial/cost_and_work_units.json')
    market = read(ROOT / 'reports/m5_market_cap/cost_and_work_units.json')
    market_review = read(OUT / 'MARKET_CAP_INDEPENDENT.json')
    portability = read(OUT / 'PORTABILITY_ADDENDUM.json')
    # Sessions are intentionally rounded outwards and include waiting, never human work.
    sessions = [
        dict(agent='root', start='2026-11-15T10:48:00+00:00', end=now.isoformat()),
        dict(agent='financial_author_and_dependency_reviewer', seconds=finance['elapsed_session_seconds_conservative']),
        dict(agent='market_author_and_budget_implementation', seconds=market['session_seconds']),
        dict(agent='execution_author', seconds=execution['session_wall_seconds']),
        dict(agent='budget_recovery_agent', start='2026-11-15T11:14:00+00:00', end='2026-11-15T11:21:00+00:00'),
        dict(agent='independent_accounting_and_financial', start='2026-11-15T11:10:00+00:00', end='2026-11-15T11:22:41+00:00'),
        dict(agent='independent_market_including_portability_followup', seconds=market_review['total_review_intervals_seconds']),
        dict(agent='portability_reviewer', seconds=portability['conservative_session_wall_seconds']),
    ]
    for row in sessions:
        if 'seconds' not in row:
            row['seconds'] = (datetime.fromisoformat(row['end']) - datetime.fromisoformat(row['start'])).total_seconds()
        assert row['seconds'] >= 0
    total = sum(row['seconds'] for row in sessions)
    assert total < 16 * 3600
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE], cwd=ROOT, text=True).splitlines()
    assert not any(p.startswith(('reports/m4_', 'reports/real_data_phase3/')) for p in changed)
    paths = set()
    for pattern in ('src/quant_research/**/*.py', 'scripts/m5_*.py', 'tests/test_m5*.py', 'tests/fixtures/m5*.json',
                    'review_code/m5/**/*.py', 'reports/m5_*/*', 'reports/m5_*/*/*'):
        paths.update(p for p in ROOT.glob(pattern) if p.is_file())
    paths.update(ROOT / p for p in [
        'scripts/m4_data_feasibility.py', 'requirements.lock', 'pyproject.toml',
        'docs/M5_PLAN.md', 'docs/DATA_CONTRACT.md', 'docs/DECISION_LOG.md',
        'docs/IMPLEMENTATION_STATUS.md', 'docs/CODEX_HANDOFF.md', '.gitattributes',
        '.gitignore', 'README.md', '.github/workflows/tests.yml'])
    paths = {p for p in paths if p.name not in ('verification.json', 'release_binding.json')}
    report = dict(
        status='B_MAIN_CHAIN_ENGINEERING_PASSED_CORE_SOURCE_ADMISSION_INCOMPLETE',
        generated_at_utc=now.isoformat(), baseline_commit=BASE,
        code_commit_binding='See subsequent release_binding.json; code bytes below identify this tested tree',
        observed_parent_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        command='.venv/Scripts/python.exe -m pytest -q tests review_code',
        tests=dict(passed=int(match[1]), skipped=int(match[2] or 0), seconds=float(match[3]),
                   output_sha256=digest(OUT / 'final_pytest.txt')),
        sources=dict(final_budget_sha256=digest(ledger_path), receipt_count=59,
                     all_receipt_hashes_and_byte_counts_verified=True, used=ledger['used'], limits=ledger['limits'],
                     http_count_basis='50 direct HTTP attempts plus 2 public-index tool calls; backend unknown',
                     response_MiB=ledger['used']['new_body_bytes'] / 1024**2,
                     terminal_statuses=dict(Counter(r['status'] for r in ledger['attempts'])),
                     administrative_recovery='budget_recovery/attempt50_recovery_committed.json'),
        session_budget=dict(limit_seconds=57600, conservative_parallel_wall_seconds=total,
                            hours=total / 3600, includes_waits=True, human_labor_hours=None, sessions=sessions),
        constraints=dict(frozen_summary_sha256=SUMMARY, m4_budget_sha256=M4_BUDGET,
                         old_report_changes=[], valid_history=448, invalidated_or_aborted_history=353,
                         alpha_registrations=0, alpha_runs=0, etf_reruns=0, holdout_market_factor_strategy_reads=0,
                         deployment_capital_cny=100000, paper_live_enabled=False, purchases=0),
        task_status=dict(dependencies='PASS', durable_budget='PASS', financial='PARTIAL_F02_F03_ONLY',
                         real_account_events='BLOCKED_RULE_SOURCES', market_cap='PARTIAL_0_FORMAL_CHAINS',
                         governance='PASS_BOUNDARIES_FORMAL_ADMISSION_BLOCKED'),
        file_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)},
        final_commit_self_reference_note='Implementation commit is bound from a later metadata-only receipt; not invented here')
    atomic_json(OUT / 'verification.json', report)
    print(json.dumps(dict(tests=report['tests'], used=ledger['used'], parallel_wall_hours=total / 3600,
                         files=len(report['file_sha256'])), indent=2))


if __name__ == '__main__':
    main()
