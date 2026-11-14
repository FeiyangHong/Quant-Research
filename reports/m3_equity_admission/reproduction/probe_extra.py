import sys,json,os,hashlib,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.baostock import canonical,utc_now,write_immutable
OUT=ROOT/'data/raw_equity_admission'
queries=[{'kind':'universe','day':'2024-12-31'}]
queries += [dict(kind='industry',code='sz.002796',date=d) for d in ['2016-01-04','2020-06-29','2020-07-13','2020-07-20']]
queries += [dict(kind='dividend',code='sz.300104',year=2017,yearType='operate')]
lock=ROOT/'data/.baostock_collection.lock'
fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
os.close(fd)
results=[]
try:
    for q in queries:
        cfg=dict(query=q,sdk_path=str(ROOT/'work/data_probe/baostock_sdk'))
        started=utc_now()
        try:
            p=subprocess.run([sys.executable,str(ROOT/'scripts/audit_equity_sources.py'),'--worker'],input=canonical(cfg),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
            data=json.loads(p.stdout)
        except subprocess.TimeoutExpired:
            data=dict(status='TIMEOUT',fields=[],rows=[],error='55 second hard process deadline')
        data.update(query=q,requested_at=started,ingested_at=utc_now(),source='BaoStock',available_at=None,vendor_first_seen_at=None,performance_evidence=False)
        sha=hashlib.sha256(canonical(data)).hexdigest()
        path=OUT/'raw'/('extra_'+sha+'.json')
        write_immutable(path,data)
        result=dict(query=q,status=data['status'],row_count=len(data['rows']),raw_path=path.as_posix(),sha256=sha)
        results.append(result)
        print(json.dumps(result),flush=True)
        time.sleep(1)
finally:lock.unlink()
write_immutable(OUT/'sdk_extra_manifest.json',dict(queries=results))
