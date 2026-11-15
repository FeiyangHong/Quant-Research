"""Parent-authorized audit of completed runs from the intentionally stopped v1."""
import json
from pathlib import Path
import runpy

api=runpy.run_path('work/review_real_execution.py')
root=Path('runs/real_r1_validation_v1')
events=[json.loads(line) for line in (root/'trial_registry.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
registered={e['run_id']:e for e in events if e['event']=='REGISTERED'}
completed=[e['run_id'] for e in events if e['event']=='COMPLETED']
data=api['Data']('data/admitted_r1/phase2_v1/validation',Path('.').resolve())
results=[]
for i,name in enumerate(completed):
    try:result=api['audit_run'](root/name,registered[name]['config'],data)
    except Exception as error:
        result=dict(run_id=name,status='FAIL',error=str(error))
        print(json.dumps(result),flush=True)
    results.append(result)
    if (i+1)%16==0:print(json.dumps(dict(completed=i+1,total=len(completed))),flush=True)
report=dict(status='FAILED_ENGINE_FEE_ROUNDING',period='validation',matrix_complete=False,
    expected_runs=224,reviewed_completed_runs=len(results),runs=results,
    numerical_findings=sum(len(r.get('findings',[])) for r in results),
    other_failed_runs=sum(r['status']=='FAIL' for r in results),
    raw_quote_rows_verified=len(data.checked_bars),raw_objects_verified=len(data.raw_cache),
    audit_code_sha256=api['sha'](Path('work/review_real_execution.py')))
Path('work/execution_review_validation_v1_stopped.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='runs'}),flush=True)
