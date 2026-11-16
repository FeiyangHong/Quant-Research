"""Run only the frozen M8 matrix, base checkpoint then registered stresses."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.liquid_runner import run_liquid_experiment
from quant_research.data import load_dataset
from quant_research.provenance import digest, source_provenance, write_json
from quant_research.runner import dataset_hash

REPORT = ROOT / 'reports/m8_rotation'


def read(path):
    return json.loads(Path(path).read_bytes())


def config_for(trial):
    fields = ('variant', 'initial_cash', 'risk_scaling', 'signal_release_delay',
              'execution_delay', 'cost_multiplier', 'slippage_multiplier',
              'annual_incremental_cost', 'seed')
    return dict({key: trial[key] for key in fields}, protocol_version='phase2-mvp-0.1',
                live_enabled=False, sample=trial['period'], universe=trial['scope'],
                primary_capital_confirmed=True, claim_type='economic_increment')


def checkpoint(rows, output):
    bases = [r for r in rows if r['path'] == 'base' and r['status'] == 'COMPLETED']
    if len(bases) != 8:
        raise RuntimeError('Exactly eight completed base accounts required')
    checks = []
    for row in bases:
        path = output / row['run_id']
        nav = read(path / 'nav.json')
        if not nav or any(n['valuation_uncertainty'] for n in nav):
            raise RuntimeError('Base account has unresolved valuation or empty calendar')
        residual = max(abs(n['nav'] - n['cash_total'] - n['holdings_value']
                           - n['receivables'] + n['dividend_tax_payable']) for n in nav)
        if residual > 1e-7:
            raise RuntimeError('Base account conservation failed')
        if any(n['cash_total'] < -1e-8 for n in nav):
            raise RuntimeError('Negative cash in unlevered account')
        checks.append(dict(trial_id=row['trial_id'], sessions=len(nav),
                           nav_conservation_max_abs_cny=residual,
                           first_date=nav[0]['date'], last_date=nav[-1]['date'],
                           valuation_uncertainty=False))
    result = dict(status='PASS_DATA_AND_ACCOUNTING_ONLY', profitability_is_not_a_gate=True,
                  continue_registered_24_stresses=True, accounts=checks)
    write_json(REPORT / 'BASE_CHECKPOINT.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admitted', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/m8_real')
    parser.add_argument('--phase', choices=['base', 'stress'], required=True)
    args = parser.parse_args()
    registry = read(REPORT / 'EXPERIMENT_REGISTRY.json')
    records_path = REPORT / 'ACCOUNT_PATHS.json'
    records = read(records_path) if records_path.exists() else []
    if args.phase == 'stress':
        checkpoint(records, args.output)
        independent = read(ROOT / 'reports/m8_review/BASE_INDEPENDENT_REVIEW.json')
        expected = {r['trial_id']: r['exported_tables'] for r in records if r['path'] == 'base'}
        if (independent.get('decision') != 'PASS_DATA_AND_ACCOUNTING'
                or independent.get('author_role') != 'INDEPENDENT_REVIEWER'
                or independent.get('base_account_hashes') != expected):
            raise RuntimeError('Eight base accounts require independent hash-bound accounting review')
    wanted = [r for r in registry['trials'] if (r['path'] == 'base') == (args.phase == 'base')]
    source_hash = source_provenance(ROOT)['source_hash']
    datasets = {s: load_dataset(args.admitted / s) for s in ('development', 'validation')}
    data_hashes = {sample: dataset_hash(dataset) for sample, dataset in datasets.items()}
    for previous in records:
        if previous.get('code_hash') != source_hash or previous.get('data_hash') != data_hashes[previous['period']]:
            raise RuntimeError('Code/data changed after base: retain original and register any correctness replay first')
    for trial in wanted:
        old = [r for r in records if r['trial_id'] == trial['trial_id']]
        if old:
            raise RuntimeError('Existing path is immutable; do not silently rerun: ' + trial['trial_id'])
        if source_provenance(ROOT)['source_hash'] != source_hash:
            raise RuntimeError('Sources changed within M8 matrix phase')
        config = config_for(trial)
        try:
            destination, metrics = run_liquid_experiment(datasets[trial['period']], config, args.output, ROOT)
        except BaseException as exc:
            records.append(dict(trial, status='FAILED', error=type(exc).__name__, reason=str(exc)))
            write_json(records_path, records)
            raise
        provenance = read(destination / 'provenance.json')
        exported = REPORT / 'accounts' / trial['trial_id']
        exported.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for original in sorted(destination.glob('*.json')):
            target = exported / original.name
            shutil.copyfile(original, target)
            hashes[original.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        records.append(dict(trial, status='COMPLETED', actual_run_id=destination.name,
                            run_id=destination.name, actual_config_hash=digest(config),
                            code_commit=provenance['git_commit'], code_hash=provenance['source_hash'],
                            data_hash=provenance['data_hash'], registration_hash=provenance['registration_hash'],
                            metrics=metrics, exported_tables=hashes,
                            artifact_directory=exported.relative_to(ROOT).as_posix()))
        write_json(records_path, records)
        print(trial['trial_id'], destination.name, metrics['status'], flush=True)
    if args.phase == 'base':
        checkpoint(records, args.output)
    expected = 8 if args.phase == 'base' else 32
    if len(records) != expected or any(r['status'] != 'COMPLETED' for r in records):
        raise RuntimeError('M8 phase coverage differs from fixed registration')


if __name__ == '__main__':
    main()
