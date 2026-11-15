"""Offline M6 content binding and not-run matrix; never fetches or backtests."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.budget import atomic_json

OUT=ROOT/'reports/m6_review'
BASE='5df2fc9f74dcc8ffc498e0a08562bb7f6156c958'
PROTECTED={
 'reports/real_data_phase3/results_summary.json':'c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb',
 'data/raw_m4_equity/budget.json':'44658bc3ba757c5bd3951e11106f42631143dac651fb40e089d3b1dbcb0ee8f6',
 'data/raw_m5_equity/budget.json':'89e0c9f7088c3f8bffa9af4f5d1cfe36347cd041ff1342ce578a91d9a78d8a82',
 'reports/m6_r1i/EXPERIMENT_REGISTRY.json':'9e799ccb30fddf9e51a4c1637362c9573a77f68dd5cc481004be2878992def96',
 'reports/m6_review/M5_INDEPENDENT_REVIEW_AND_M6_HANDOFF_2026-11-15.md':'6228f8b27d26730680b892f1da4c84524c4f259d0b39f0e1825fa39cf0758faf',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def matrix():
    p=ROOT/'reports/m6_r1i/EXPERIMENT_REGISTRY.json';reg=read(p)
    g=ROOT/'reports/m6_r1i/data_gate_decision.json';gate=read(g)
    if gate['status']!='DATA_BLOCKED':raise ValueError('This closeout cannot authorize or run a return matrix')
    rows=[dict(trial_id=s['trial_id'],period=s['period'],variant=s['variant'],initial_cash=s['initial_cash'],path=s['path'],
        status='NOT_RUN_DATA_BLOCKED',actual_run_id=None,performance_metrics=None,code_version_for_executed_run=None,
        execution_data_hash=None,reason=gate['specific_blockers']) for s in reg['trials']]
    if len(rows)!=56 or len({r['trial_id'] for r in rows})!=56:raise ValueError('Registry cardinality changed')
    atomic_json(ROOT/'reports/m6_r1i/matrix_status.json',dict(registration_commit='02d0f0d',registration_sha256=sha(p),
        data_gate_sha256=sha(g),registered_paths=56,executed_paths=0,failed_executed_paths=0,not_run_paths=56,
        scope_status='DATA_BLOCKED',candidate_evidence_status='FAILED_DATA_OR_ENGINE',
        candidate_evidence_reason='DATA_NOT_ADMITTED; not evidence of unprofitable strategy or unresolved fee-engine defect',
        primary_comparison='validation 2022-2024 100000 base R0 minus E0',primary_daily_mean_difference=None,
        primary_ci95=None,incremental_annual_fixed_cost_capacity_cny=None,annual_incremental_fixed_cost=None,
        economic_hurdle_status='BLOCKED_HURDLE_UNKNOWN_COST_AND_NO_VALID_RETURN_PATH',statistics_executed=False,rows=rows))


def bind():
    for name,want in PROTECTED.items():
        if sha(ROOT/name)!=want:raise ValueError('Protected content changed: '+name)
    changed=subprocess.check_output(['git','diff','--name-only',BASE,'--','reports/real_data_phase3',
        'reports/m5_review','reports/m5_execution','reports/m5_financial','reports/m5_market_cap','configs'],cwd=ROOT,text=True)
    if changed.strip():raise ValueError('Frozen artifacts changed: '+changed)
    matrix()
    budget=read(ROOT/'data/raw_m6/budget.json')
    if not all(a['terminal'] for a in budget['attempts']):raise ValueError('Unresolved collection request')
    if budget['used']!={'http_attempts':69,'baostock_wire_attempts':0,'new_body_bytes':7273077}:
        raise ValueError('Collection changed after registered finite stop')
    (OUT/'source_budget_snapshot.json').write_bytes((ROOT/'data/raw_m6/budget.json').read_bytes())
    atomic_json(OUT/'integrity.json',dict(base_commit=BASE,protected_hashes=PROTECTED,old_reports_and_configs_unchanged=True,
        source_budget_sha256=sha(ROOT/'data/raw_m6/budget.json'),all_69_requests_terminal=True,
        real_r1i_paths=0,real_r2_r3_alpha_paths=0,old_r1b_performance_replays=0))
    paths=set(ROOT.glob('src/quant_research/**/*.py'))|set(ROOT.glob('scripts/m6*.py'))|set(ROOT.glob('review_code/m6/*.py'))
    paths|={ROOT/p for p in ['scripts/m5_execution.py','scripts/m5_market_cap.py','scripts/m4_data_feasibility.py',
        'tests/test_m6_rates.py','tests/test_equity_execution.py','docs/M6_PLAN.md','docs/DECISION_LOG.md',
        'docs/IMPLEMENTATION_STATUS.md','docs/STRATEGY_SPEC.md','docs/STRATEGY_IMPLEMENTATION.md','docs/CODEX_HANDOFF.md']}
    for directory in ['m6_review','m6_r1i','m6_stock_execution','m6_stock_source']:
        paths|={p for p in (ROOT/'reports'/directory).rglob('*') if p.is_file()}
    # Receipts/version annotations are created after implementation commit;
    # excluding them avoids self-reference. All research outputs remain bound.
    excluded={'content_manifest.json','release_binding.json','delivery_receipt.json','session_usage.json','ci_job_log.txt','ci_receipt.json'}
    paths={p for p in paths if not (p.parent==OUT and p.name in excluded)}
    files={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}
    root_hash=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    atomic_json(OUT/'content_manifest.json',dict(baseline_commit=BASE,files=files,content_set_sha256=root_hash,
        exclusions=sorted(excluded),receipt_commit_binding='release_binding.json'))
    print(json.dumps(dict(files=len(files),content_set_sha256=root_hash,protected='PASS')))


def verify():
    manifest=read(OUT/'content_manifest.json');failures=[]
    for name,want in manifest['files'].items():
        if not (ROOT/name).exists() or sha(ROOT/name)!=want:failures.append(name)
    for name,want in PROTECTED.items():
        if not (ROOT/name).exists() or sha(ROOT/name)!=want:failures.append(name)
    if failures:raise ValueError('Missing/hash-mismatched original/content files: '+str(failures))
    print(json.dumps(dict(status='PASS',bound_files=len(manifest['files']),protected_files=len(PROTECTED))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['bind','verify']);args=parser.parse_args()
    bind() if args.mode=='bind' else verify()
