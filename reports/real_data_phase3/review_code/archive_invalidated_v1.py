import json, hashlib
from pathlib import Path
from datetime import datetime, timezone
from quant_research.provenance import append_event, write_json

destination=Path('reports/real_data_phase3/superseded_v1')
destination.mkdir(exist_ok=False)
reason='FAILED_ENGINE_DECIMAL_ROUNDING: binary multiplication before ROUND_HALF_UP affected commission and odd-lot notional/slippage. Entire v1 source generation is ineligible; same configurations will be rerun.'
summary={'status':'INVALIDATED_ENGINE_RESULTS_NOT_ELIGIBLE_FOR_ALPHA', 'reason':reason,
    'original_commit':'1096a7f1d696dc644d8c0c39bca8d16e09a32f1a',
    'original_source_hash':'92359f6b8cb588dcec555599ecdb9c5ece4f992347684f0009ea371837051a64',
    'recorded_at':datetime.now(timezone.utc).isoformat(), 'strategy_parameters_changed':False,
    'data_changed':False, 'old_outputs_overwritten':False, 'holdout_opened':False,
    'periods':{},'attempts':[]}
for period in ('development','validation'):
    root=Path('runs/real_r1_'+period+'_v1')
    registry=root/'trial_registry.jsonl'
    events=[json.loads(line) for line in registry.read_text().splitlines()]
    registered={e['run_id']:e for e in events if e['event']=='REGISTERED'}
    terminal={e['run_id']:e for e in events if e['event'] in ('COMPLETED','FAILED')}
    for run_id in set(registered)-set(terminal):
        failure=dict(run_id=run_id,event='FAILED',error='ExternalTermination',reason=reason,
            actor='root: stop after independent engineering counterexample, not an economic selection')
        target=root/run_id/'failure.json'
        assert not target.exists()
        write_json(target,failure)
        append_event(registry,failure)
        terminal[run_id]=failure
    append_event(registry,dict(event='MATRIX_INVALIDATED',reason=reason,
        scope='Every v1 attempt remains archived; completion does not imply arithmetic acceptance'))
    copied=destination/(period+'_trial_registry.jsonl')
    copied.write_bytes(registry.read_bytes())
    summary['periods'][period]={'registered':len(registered),
        'completed':sum(e['event']=='COMPLETED' for e in terminal.values()),
        'failed':sum(e['event']=='FAILED' for e in terminal.values()),
        'registry_sha256':hashlib.sha256(copied.read_bytes()).hexdigest()}
    for run_id,registration in registered.items():
        folder=root/run_id
        entry=dict(period=period,run_id=run_id,config=registration['config'],
            terminal_event=terminal[run_id],interpretation='INVALIDATED_DO_NOT_INTERPRET_AS_RESEARCH_EVIDENCE',
            provenance=json.loads((folder/'provenance.json').read_bytes()),
            metrics=json.loads((folder/'metrics.json').read_bytes()) if (folder/'metrics.json').exists() else None,
            table_hashes=json.loads((folder/'table_hashes.json').read_bytes()) if (folder/'table_hashes.json').exists() else None)
        summary['attempts'].append(entry)
write_json(destination/'invalidated_attempts.json',summary)
print(summary['periods'])
