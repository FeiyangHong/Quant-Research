"""Bounded M4 source audit. No strategy execution or performance calculation.

All network calls share the persisted attempt/byte budget. Reruns use a fresh
label and consume remaining budget; existing objects are never overwritten.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/raw_m4_equity'
REPORT = ROOT / 'reports/m4_data'
SNAPSHOT_DATE = '2020-07-31'
LIMITS = {'http_attempts':160, 'baostock_wire_attempts':20, 'new_body_bytes':120*1024*1024}

def now():
    return datetime.now(timezone.utc).isoformat()

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def budget():
    path = OUT/'budget.json'
    if not path.exists():
        save(path, {'registered_at':now(), 'snapshot_date':SNAPSHOT_DATE, 'limits':LIMITS,
                    'used':dict.fromkeys(LIMITS,0), 'attempts':[], 'human_reviews':0,
                    'purchases_cny':0, 'transient_retries_allowed':1,
                    'byte_semantics':'HTTP response bodies plus BaoStock decoded UTF-8 responses; not transport overhead'})
    return json.loads(path.read_text(encoding='utf-8'))

def begin(kind, label, **extra):
    b=budget()
    if b['used'][kind] >= b['limits'][kind] or b['used']['new_body_bytes'] >= b['limits']['new_body_bytes']:
        raise RuntimeError('M4 hard budget exhausted before request')
    b['used'][kind]+=1
    rec={'id':len(b['attempts'])+1,'kind':kind,'label':label,'started_at':now(),**extra}
    b['attempts'].append(rec);save(OUT/'budget.json', b)
    return rec['id']

def finish(idx, payload, started, **extra):
    b=budget();b['used']['new_body_bytes']+=len(payload)
    if b['used']['new_body_bytes']>b['limits']['new_body_bytes']:
        raise RuntimeError('Body byte cap breached')
    sha=hashlib.sha256(payload).hexdigest()
    path=OUT/'objects'/f'{sha}.bin';path.parent.mkdir(exist_ok=True)
    if not path.exists():path.write_bytes(payload)
    rec=b['attempts'][idx-1]
    rec.update(byte_count=len(payload),sha256=sha,raw_path=str(path),elapsed_seconds=round(time.perf_counter()-started,6),ingested_at=now(),**extra)
    save(OUT/'budget.json',b)
    return rec

def fetch(label,url,body=None):
    validate_document_url(url)
    idx=begin('http_attempts',label,url=url,request_body=body,method='POST' if body else 'GET')
    started=time.perf_counter();payload=b''
    try:
        req=Request(url,data=body.encode() if body else None,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/','Content-Type':'application/x-www-form-urlencoded'})
        with urlopen(req,timeout=35) as response:
            remaining=budget()['limits']['new_body_bytes']-budget()['used']['new_body_bytes']
            while len(payload)<remaining:
                chunk=response.read(min(65536,remaining-len(payload)))
                if not chunk:break
                payload+=chunk
            rec=finish(idx,payload,started,status='FETCHED' if len(payload)<remaining else 'TRUNCATED_BUDGET',http_status=response.status,content_type=response.headers.get('Content-Type'))
    except Exception as exc:
        rec=finish(idx,payload,started,status='FAILED',error=f'{type(exc).__name__}: {exc}')
    save(OUT/'manifests'/f'{label}_{idx:04d}.json',rec)
    # Convenience pointer only. Immutable request identities remain in the ledger
    # and the ID-suffixed manifests; a repeated label cannot erase evidence.
    save(OUT/'manifests'/f'{label}.json',rec)
    return rec

def query_cninfo(label,code,key,dates):
    bounds=dates.split('~')
    if len(bounds)!=2 or not ('1990-01-01'<=bounds[0]<=bounds[1]<='2024-12-31'):
        raise ValueError('Bounded pre-2025 documentary range required')
    # CNInfo stock parameter requires the organization id, found from the fixed M3 listing.
    org=''
    for p in (ROOT/'data/raw_equity_admission/http').glob('cninfo_revision_candidates*.bin'):
        for r in json.loads(p.read_bytes()).get('announcements',[]):
            if r['secCode']==code:org=r.get('orgId','')
    if not org and code=='600518':org='gssh0600518'
    if not org:raise ValueError('Organization ID must be verified; blank silently loses issuer filter')
    body=urlencode(dict(pageNum=1,pageSize=100,column='szse',tabName='fulltext',stock=f'{code},{org}',searchkey=key,secid='',plate='',category='',trade='',seDate=dates,sortName='time',sortType='asc',isHLtitle='false'))
    return fetch(label,'https://www.cninfo.com.cn/new/hisAnnouncement/query',body)

def date_only_clock(publication, trading_dates):
    later=sorted(d for d in set(trading_dates) if d>publication)
    if len(later)<2:raise ValueError('Verified calendar needs availability and execution dates')
    return {'available_at':later[0]+'T21:00:00+08:00','earliest_execution':later[1]}

def validate_document_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in {'www.cninfo.com.cn','static.cninfo.com.cn','www.csrc.gov.cn','www.sse.com.cn','www.szse.cn','investor.szse.cn','disc.static.szse.cn'}:
        raise ValueError('Explicit primary-source HTTPS host required')
    for found in re.findall(r'(20\d\d)-\d\d-\d\d',parsed.path):
        if int(found)>=2025:raise ValueError('Post-2024 documents sealed')

def collect_baostock():
    lock=OUT/'baostock.session.lock'
    with lock.open('x') as handle:handle.write(now())
    sys.path.insert(0,str(ROOT/'work/data_probe/baostock_sdk'))
    import baostock as bs
    import baostock.security.sectorinfo as sectors
    import baostock.util.socketutil as sock
    old_send=sock.send_msg
    active=['login']
    def send(msg):
        idx=begin('baostock_wire_attempts',active[0]);started=time.perf_counter()
        result=old_send(msg)
        finish(idx,(result or '').encode(),started,status='RETURNED' if result else 'FAILED')
        return result
    sock.send_msg=send;socket.setdefaulttimeout(25)
    summaries=[]
    def query(label,func):
        active[0]=label;started=time.perf_counter()
        result=func();rows=[];fields=getattr(result,'fields',[]) or []
        if fields and result.error_code=='0':
            while result.next():rows.append(result.get_row_data())
        obj={'label':label,'snapshot_date':SNAPSHOT_DATE,'fields':fields,'rows':rows,'error_code':result.error_code,'error_msg':result.error_msg,'elapsed_seconds':round(time.perf_counter()-started,6),'processed_at':now()}
        save(OUT/'baostock'/f'{label}.json',obj)
        summaries.append({k:v for k,v in obj.items() if k!='rows'}|{'row_count':len(rows)})
        print(label,result.error_code,len(rows),flush=True)
        return result.error_code=='0'
    try:
        if query('login',lambda:bs.login()):
            for label,func in [
                ('full_universe_20200731',lambda:bs.query_all_stock(day=SNAPSHOT_DATE)),
                ('full_daily_20200731',lambda:bs.query_daily_history_k_AStock(date=SNAPSHOT_DATE)),
                ('full_industry_20200731',lambda:bs.query_stock_industry(date=SNAPSHOT_DATE)),
                ('st_20200731',lambda:sectors.query_st_stocks(date=SNAPSHOT_DATE)),
                ('starst_20200731',lambda:sectors.query_starst_stocks(date=SNAPSHOT_DATE)),
                ('terminated_20200731',lambda:sectors.query_terminated_stocks(date=SNAPSHOT_DATE)),
                ('calendar_2017_2024',lambda:bs.query_trade_dates(start_date='2017-01-01',end_date='2024-12-31'))]:
                if (OUT/'baostock'/f'{label}.json').exists():continue
                if budget()['used']['baostock_wire_attempts']>=18:break
                query(label,func)
            query('logout',lambda:bs.logout())
    finally:
        save(REPORT/'baostock_request_summary.json',summaries)
        lock.unlink()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['register','baostock','query','fetch']);parser.add_argument('--label');parser.add_argument('--code');parser.add_argument('--key');parser.add_argument('--dates');parser.add_argument('--url');args=parser.parse_args()
    if args.action=='register':print(json.dumps(budget(),ensure_ascii=False))
    elif args.action=='baostock':collect_baostock()
    elif args.action=='query':print(json.dumps(query_cninfo(args.label,args.code,args.key,args.dates),ensure_ascii=False))
    else:print(json.dumps(fetch(args.label,args.url),ensure_ascii=False))
