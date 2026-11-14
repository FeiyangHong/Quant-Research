from pathlib import Path
import hashlib,json,subprocess
from quant_research.provenance import digest
r=Path('F:/QuantTrade/Quant-Research')
b=r/'reports/real_data_phase3'
v=json.loads((b/'evaluation_provenance.json').read_bytes())
s=json.loads((b/'results_summary.json').read_bytes())
p=json.loads((b/'registered_plan_v2.json').read_bytes())
assert s['evaluation_provenance']==v
assert digest(v['source_files'])==v['source_hash']
for rel,sha in v['source_files'].items():
    payload=(b/'evaluation_source_snapshot'/rel).read_bytes()
    assert hashlib.sha256(payload).hexdigest()==sha,rel
    committed=subprocess.check_output(['git','show',v['git_commit']+':'+rel],cwd=r)
    assert committed==payload,rel
assert s['provenance']['source_hash']==p['source_hash']
assert {digest(x['config']) for x in s['runs']}=={x['config_hash'] for x in p['trials']}
assert s['run_count']==448 and len(s['runs'])==448
assert not s['valuation_review']['accounting_timing_ineligible_runs']
assert not s['valuation_review']['runs_with_uncertain_valuation']
report={'status':'PASS','scope':'evaluation source snapshot and committed bytes; complete preregistered config identities; not an additional statistical test','source_files_verified':len(v['source_files']),'evaluation_git_commit':v['git_commit'],'evaluation_source_hash':v['source_hash'],'execution_source_hash':p['source_hash'],'configurations':448,'results_summary_sha256':hashlib.sha256((b/'results_summary.json').read_bytes()).hexdigest(),'evaluation_provenance_sha256':hashlib.sha256((b/'evaluation_provenance.json').read_bytes()).hexdigest()}
(b/'PUBLICATION_CHECK.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(report))