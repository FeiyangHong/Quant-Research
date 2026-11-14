import hashlib, importlib.util, json, sys, time
from pathlib import Path
import pandas as pd
from quant_research.data import Dataset
from quant_research.execution import run_backtest
from quant_research.provenance import write_json

oldpath=Path('work/execution_decimal_before_projection.py')
spec=importlib.util.spec_from_file_location('quant_research._decimal_reference',oldpath)
oracle=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=oracle
spec.loader.exec_module(oracle)
report={'purpose':'ENGINE_PROJECTION_EQUIVALENCE_ONLY_NOT_ALPHA_SELECTION',
    'reference_source_sha256':hashlib.sha256(oldpath.read_bytes()).hexdigest(),
    'optimized_source_sha256':hashlib.sha256(Path('src/quant_research/execution.py').read_bytes()).hexdigest(),
    'records':[]}
for period,variant,scaling in [('development','R1',True),('validation','R0',True)]:
    root=Path('runs/real_r1_'+period+'_v1')
    registrations=[json.loads(s) for s in (root/'trial_registry.jsonl').read_text().splitlines()]
    ids={r['run_id'] for r in registrations if r['event']=='COMPLETED'}
    reg=next(r for r in registrations if r['event']=='REGISTERED' and r['run_id'] in ids
        and r['config']['variant']==variant and r['config']['risk_scaling']==scaling
        and r['config']['initial_cash']==100000 and r['config']['cost_multiplier']==3)
    cfg=reg['config']; folder=root/reg['run_id']
    data_root=Path('data/admitted_r1/phase2_v1')/period
    manifest=json.loads((data_root/'manifest.json').read_bytes())
    objects={}
    for name in ['calendar']+list(('instruments','bars','actions','benchmark')):
        content=(data_root/(name+'.json')).read_bytes()
        assert hashlib.sha256(content).hexdigest()==manifest['file_sha256'][name+'.json']
        objects[name]=json.loads(content)
    dataset=Dataset(objects['calendar'],*(pd.DataFrame(objects[name]['records'],columns=objects[name]['columns'])
        for name in ['instruments','bars','actions','benchmark']),manifest)
    decisions=json.loads((folder/'decisions.json').read_bytes())
    outputs=[]; durations=[]
    destination=Path('work/engine_projection_equivalence')/period
    for name,fn in [('reference',oracle.run_backtest),('optimized',run_backtest)]:
        started=time.perf_counter()
        result=fn(dataset,decisions,cfg['initial_cash'],cost_multiplier=cfg['cost_multiplier'],
            slippage_multiplier=cfg['slippage_multiplier'],cash_delay_sessions=cfg.get('cash_delay_sessions',0),
            start_date='2016-01-01' if period=='development' else '2022-01-01')
        durations.append(time.perf_counter()-started)
        hashes={}
        for key,value in result.items():
            if isinstance(value,pd.DataFrame):
                content=value.to_json(orient='records',date_format='iso',double_precision=15).encode('utf-8')
                path=destination/name/(key+'.json'); path.parent.mkdir(parents=True,exist_ok=True)
                assert not path.exists(); path.write_bytes(content)
                hashes[key]=hashlib.sha256(content).hexdigest()
        outputs.append(hashes)
    assert outputs[0]==outputs[1]
    report['records'].append(dict(period=period,source_registered_attempt=reg['run_id'],config=cfg,
        dataset_manifest_sha256=hashlib.sha256((data_root/'manifest.json').read_bytes()).hexdigest(),
        decisions_sha256=hashlib.sha256((folder/'decisions.json').read_bytes()).hexdigest(),
        ledger_table_hashes=outputs[0],reference_seconds=durations[0],optimized_seconds=durations[1],
        result='ALL_11_TABLES_BYTE_IDENTICAL'))
    print(period,report['records'][-1]['result'],durations,flush=True)
write_json('reports/real_data_phase3/ENGINE_PROJECTION_EQUIVALENCE.json',report)
