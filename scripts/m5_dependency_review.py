"""Read-only old-input dependency comparison. Never runs a strategy/account."""
import ast
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.data import Dataset
from quant_research.dependencies import representative_dependencies
from quant_research.providers.universe import provisional_amount_representatives

BASE='8a9977cb5538a3ffd3c07506035c0dca7c3a0f14'
OUT=ROOT/'reports/m5_review'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def original(path):return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT).decode('utf-8')

def main():
    dependency_source=original('src/quant_research/dependencies.py')
    old=types.ModuleType('m5_original_dependencies');exec(compile(dependency_source,'baseline_dependencies.py','exec'),old.__dict__)
    universe_source=original('src/quant_research/providers/universe.py')
    node=next(n for n in ast.parse(universe_source).body if isinstance(n,ast.FunctionDef) and n.name=='provisional_amount_representatives')
    namespace=dict(datetime=datetime,Decimal=Decimal,InvalidOperation=InvalidOperation,HISTORY_END='2024-12-31')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'baseline_universe.py','exec'),namespace)
    frozen_path=ROOT/'reports/real_data_phase3/results_summary.json'
    assert digest(frozen_path)=='c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb'
    frozen=read(frozen_path);reports=[]
    for period in ('development','validation'):
        folder=ROOT/'data/admitted_r1/phase2_v1'/period
        manifest=read(folder/'manifest.json');tables={};hashes={}
        for name in ('instruments','bars','actions','benchmark','calendar'):
            path=folder/(name+'.json');hashes[name]=digest(path)
            assert hashes[name]==manifest['file_sha256'][name+'.json']
            blob=read(path)
            tables[name]=blob if name=='calendar' else pd.DataFrame(blob['records'],columns=blob['columns'])
        data=Dataset(tables.pop('calendar'),manifest=manifest,**tables)
        before=old.representative_dependencies(data);after=representative_dependencies(data)
        differences=[dict(quarter_start=a['quarter_start'],before=a,after=b) for a,b in zip(before['schedule'],after['schedule']) if a!=b]
        assert len(before['schedule'])==len(after['schedule'])
        master=data.instruments.to_dict('records');first=data.instruments.drop_duplicates('instrument_id')
        candidates=[dict(code=r.instrument_id,category=r.benchmark_id,documented_index_categories=[r.benchmark_id],
            documented_listing_dates=[r.listed_on],snapshot_dates=data.calendar) for r in first.itertuples()]
        histories={sid:[dict(date=r.date,amount=str(r.amount),suspended=r.suspended) for r in frame.itertuples()]
                   for sid,frame in data.bars.groupby('instrument_id')}
        p_before=namespace['provisional_amount_representatives'](data.calendar,candidates,histories,master)
        p_after=provisional_amount_representatives(data.calendar,candidates,histories,master)
        provider_diff=[dict(quarter_start=a['quarter_start'],before=a,after=b) for a,b in zip(p_before['schedule'],p_after['schedule']) if a!=b]
        run_ids=[r['directory'] for r in frozen['runs'] if r['period']==period]
        reports.append(dict(period=period,source_hashes=hashes,manifest_sha256=digest(folder/'manifest.json'),
            quarterly_checks=len(after['schedule']),baseline_proof_matches_stored_manifest=before==manifest.get('representative_dependencies'),
            full_proof_equal=before==after,quarterly_differences=differences,
            required_before=before['required_full_history_instruments'],required_after=after['required_full_history_instruments'],
            provider_quarterly_differences=provider_diff,provider_proof_equal=p_before==p_after,
            frozen_run_ids_covered=run_ids,affected_run_ids=run_ids if differences or provider_diff else [],
            unknowns=['No complete persisted internal lookup trace; comparison is of archived admission inputs and registered dependency reconstruction.',
                      'Provider comparison reconstructs candidate/history wrappers from admitted master and amount rows; it is not a new independent historical-roster proof.']))
        print(period,len(run_ids),len(differences),len(provider_diff),flush=True)
    result=dict(status='READ_ONLY_COMPARISON_COMPLETE',baseline_commit=BASE,purpose='DEPENDENCY_CORRECTNESS_NOT_STRATEGY_PERFORMANCE',
        frozen_summary_sha256=digest(frozen_path),frozen_runs=448,invalidated_history_preserved=353,new_strategy_or_account_runs=0,
        baseline_dependency_sha256=hashlib.sha256(dependency_source.encode()).hexdigest(),
        baseline_provider_sha256=hashlib.sha256(universe_source.encode()).hexdigest(),periods=reports,
        source_sha256={p:digest(ROOT/p) for p in ['scripts/m5_dependency_review.py','src/quant_research/dependencies.py','src/quant_research/temporal.py','src/quant_research/strategy.py','src/quant_research/providers/universe.py']})
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'dependency_old_input_impact.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
