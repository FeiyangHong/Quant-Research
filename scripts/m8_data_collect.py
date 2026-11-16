"""Bounded M8 documentary/2019 formation collection, reusing immutable originals."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from functools import lru_cache
from urllib.parse import urlencode

from m8_sources import ROOT, OUT, fetch, baostock_session, exclusive_lock
from m8_data_candidates import REPORT, save, sha
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.baostock import HISTORY_FIELDS, Query, validate_response

def issue(label,url,body=None,dates='2010-01-01~2019-12-31',headers=None,route='official_documents'):
    path=REPORT/'request_log.json'
    rows=json.loads(path.read_bytes()) if path.exists() else []
    old=[r for r in rows if r['label']==label]
    if old:
        if (old[-1]['url'],old[-1].get('body'))!=(url,body):raise ValueError('Request identity collision')
        if old[-1].get('receipt'):return old[-1]['receipt']
        raise ValueError('Unresolved registered request')
    # The durable ledger is authoritative if concurrent summary writers lost a row.
    ledger_path=OUT/'budget.json'
    prior=[r for r in json.loads(ledger_path.read_bytes())['attempts'] if r.get('label')==label] if ledger_path.exists() else []
    if prior:
        if len(prior)!=1 or (prior[0].get('url'),prior[0].get('request_body'))!=(url,body) or not prior[0].get('terminal'):
            raise ValueError('Unresolved or conflicting durable request')
        return prior[0]
    rec=dict(label=label,url=url,body=body,dates=dates,route=route,headers=headers,registered_at=datetime.now(timezone.utc).isoformat())
    with exclusive_lock(REPORT/'request_summary.lock'):
        rows=json.loads(path.read_bytes()) if path.exists() else []
        if any(r['label']==label for r in rows):raise ValueError('Concurrent duplicate request')
        rows.append(rec);save(path,rows)
    save(REPORT/'requests'/(label+'.json'),rec)
    rec['receipt']=fetch(label,url,body,dates=dates,scope='rotation',headers=headers,route=route)
    with exclusive_lock(REPORT/'request_summary.lock'):
        rows=json.loads(path.read_bytes());rows=[rec if r['label']==label else r for r in rows];save(path,rows)
    print(label,rec['receipt']['status'],rec['receipt'].get('byte_count'),flush=True)
    return rec['receipt']

def document(label, row, dates='2010-01-01~2019-12-31'):
    cap=known_sources().get(row['source_url']) or issue(label,row['source_url'],dates=dates)
    fact=dict(row,receipt=cap)
    if cap.get('status') in ('FETCHED','SUCCESS'):
        if sha(cap['raw_path'])!=cap['sha256']:raise ValueError('Source changed')
        txt=OUT/'text'/(cap['sha256']+'.txt');txt.parent.mkdir(parents=True,exist_ok=True)
        if not txt.exists():
            run=subprocess.run(['pdftotext','-layout',str(cap['raw_path']),str(txt)],capture_output=True,timeout=45)
            if run.returncode:raise ValueError('Source PDF extraction failed')
        fact.update(text_path=str(txt),text_sha256=sha(txt))
    return fact

def formation_documents():
    result=[];seen_hash={}
    for path in (REPORT/'titles').glob('formation*.json'):
        data=json.loads(path.read_bytes());sid=data['instrument_id']
        for row in data['records']:
            import re
            title=row['title']
            needed=('终止上市' in title and '提示' not in title) or (any(x in title for x in ['修订','修改','更名']) and ('合同' in title or '更名' in title)) or (sid=='sh.515000' and ('招募说明书' in title or title.endswith('基金合同')))
            if not needed:continue
            import hashlib
            label='formation_supp_'+sid+'_'+row['publication_date']+'_'+hashlib.sha256(row['source_url'].encode()).hexdigest()[:10]
            # Same exact original URL from completed M8 captures is reusable.
            book=json.loads((OUT/'budget.json').read_bytes())
            old=next((r for r in book['attempts'] if r.get('url')==row['source_url'] and r.get('status')=='FETCHED'),None)
            if old:
                fact=dict(row,receipt=old,text_path=str(OUT/'text'/(old['sha256']+'.txt')))
                fact['text_sha256']=sha(fact['text_path']);result.append(fact)
                save(REPORT/'formation_documents.json',result);continue
            result.append(document(label,row))
            save(REPORT/'formation_documents.json',result)

@lru_cache(maxsize=1)
def known_sources():
    found={}
    for path in (ROOT/'data').glob('raw_*/budget.json'):
        if path.parent==OUT:continue
        data=json.loads(path.read_bytes())
        for r in data.get('attempts',[]):
            if r.get('url') and r.get('raw_path') and r.get('byte_count',0)>0 and r.get('status') in ('FETCHED','SUCCESS'):
                found[r['url']]=r
    for path in (ROOT/'data').glob('raw_*/**/captures/*.json'):
        r=json.loads(path.read_bytes())
        if r.get('status')=='SUCCESS' and r.get('request',{}).get('url'):
            r=dict(r,raw_path=str(path.parent.parent/r['raw_path']),ingested_at=r.get('fetched_at'))
            found[r['request']['url']]=r
    return found

def documents():
    freeze=json.loads((REPORT/'CANDIDATE_FREEZE_RECEIPT.json').read_bytes())
    if sha(REPORT/'CANDIDATE_REVIEW.json')!=freeze['sha256']:raise ValueError('Candidate freeze changed')
    rows=json.loads((REPORT/'CANDIDATE_REVIEW.json').read_bytes())['records']
    sources=known_sources();seen={};facts=[]
    rows=sorted(rows,key=lambda r:(not r['instrument_id'].startswith(('sh.51','sz.159')),r['instrument_id']))
    for r in rows:
        if r['status']!='PENDING_ORIGINAL_PRODUCT_REVIEW':continue
        e=r['keyword_evidence'][0];url=e['source_url'];sid=r['instrument_id']
        cap=sources.get(url) or seen.get(url) or issue('listing_'+sid,url)
        seen[url]=cap
        fact=dict(instrument_id=sid,listing=e,receipt=cap,reused_source=url in sources)
        if cap.get('status') in ('FETCHED','SUCCESS'):
            raw=Path(cap['raw_path'])
            if sha(raw)!=cap['sha256']:raise ValueError('Original source hash mismatch')
            txt=OUT/'text'/(cap['sha256']+'.txt');txt.parent.mkdir(parents=True,exist_ok=True)
            if not txt.exists():
                run=subprocess.run(['pdftotext','-layout',str(raw),str(txt)],capture_output=True,timeout=45)
                if run.returncode:fact['extraction_error']=run.stderr.decode(errors='replace')[-300:]
            if txt.exists():fact.update(text_path=str(txt),text_sha256=sha(txt))
        facts.append(fact);save(REPORT/'listing_documents.json',facts)
    print('Documents',len(facts),'unique',len(seen),flush=True)

def histories():
    decisions=json.loads((REPORT/'PRODUCT_REVIEW.json').read_bytes())['records']
    selected=[r['instrument_id'] for r in decisions if r['status']=='INCLUDED_PENDING_FORMATION']
    save(REPORT/'FORMATION_HISTORY_REQUESTS.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
         instruments=selected,start='2019-01-01',end='2019-12-31',fields=HISTORY_FIELDS,
         rationale='Only pre-2020 raw daily formation amounts and contemporaneous trading state; no return analysis'))
    with baostock_session(scope='rotation',label='formation_login',dates='2019-01-01~2019-12-31') as (bs,active):
        login=bs.login()
        if login.error_code!='0':raise RuntimeError(login.error_msg)
        try:
            for sid in selected:
                path=OUT/'decoded'/('formation_'+sid+'.json')
                if path.exists():continue
                active[0]='formation_'+sid
                query=Query(kind='history',code=sid,start='2019-01-01',end='2019-12-31')
                started=datetime.now(timezone.utc).isoformat()
                rs=bs.query_history_k_data_plus(sid,HISTORY_FIELDS,start_date=query.start,end_date=query.end,frequency='d',adjustflag='3')
                rows=[]
                while rs.error_code=='0' and rs.next():rows.append(rs.get_row_data())
                payload=dict(status='SUCCESS' if rs.error_code=='0' else 'FAILED',fields=rs.fields,rows=rows,
                    query=vars(query),error_code=rs.error_code,error_msg=rs.error_msg,source='BaoStock',
                    requested_at=started,ingested_at=datetime.now(timezone.utc).isoformat(),snapshot_format='Decoded SDK rows; source responses retained in shared ledger')
                save(path,payload)
                if payload['status']=='SUCCESS':validate_response(query,payload)
                print(sid,payload['status'],len(rows),flush=True)
        finally:active[0]='formation_logout';bs.logout()

def titles_one(sid,start,end,label_prefix):
    records=[];total=None;page=1;captures=[]
    while total is None or len(records)<total:
        if sid.startswith('sh.'):
            query=dict(isPagination='true',type='inParams',sqlId='COMMON_PL_JJXX_JJGG_NEW_L',TITLE='',SECURITY_CODE=sid[3:],START_DATE=start,END_DATE=end,BULLETIN_TYPE='',DATE_DESC=1)
            query.update({'pageHelp.pageSize':100,'pageHelp.pageNo':page,'pageHelp.beginPage':page,'pageHelp.cacheSize':1,'pageHelp.endPage':page})
            cap=issue(label_prefix+'_'+sid+'_'+str(page),'https://query.sse.com.cn/commonQuery.do?'+urlencode(query),dates=start+'~'+end,headers={'Referer':'https://www.sse.com.cn/'},route='historical_etf_announcements')
            captures.append(cap)
            if cap['status']!='FETCHED':break
            data=json.loads(Path(cap['raw_path']).read_bytes());n=int(data['pageHelp']['total'])
            rows=[dict(instrument_id=sid,title=r['TITLE'],publication_date=r['SSEDATE'],source_url='https://www.sse.com.cn'+r['URL'],source_record=r) for r in data['result']]
            if any(r['source_record']['SECURITY_CODE']!=sid[3:] for r in rows):raise ValueError('Wrong SSE code')
        else:
            body=json.dumps(dict(seDate=[start,end],channelCode=['fundinfoNotice_disc'],stock=[sid[3:]],pageSize=50,pageNum=page),separators=(',',':'))
            cap=issue(label_prefix+'_'+sid+'_'+str(page),'https://www.szse.cn/api/disc/announcement/annList',body,dates=start+'~'+end,headers={'Referer':'https://www.szse.cn/','Content-Type':'application/json'})
            captures.append(cap)
            if cap['status']!='FETCHED':break
            data=json.loads(Path(cap['raw_path']).read_bytes());n=int(data['announceCount'])
            rows=[dict(instrument_id=sid,title=r['title'],publication_date=r['publishTime'][:10],source_url='https://disc.static.szse.cn/download'+r['attachPath'],source_record=r) for r in data['data']]
            if any(sid[3:] not in r['source_record']['secCode'] for r in rows):raise ValueError('Wrong SZSE code')
        if total is None:total=n
        if total!=n:raise ValueError('Unstable title count')
        if any(not start<=r['publication_date']<=end for r in rows):raise ValueError('Title outside date range')
        records+=rows
        if not rows and len(records)<total:raise ValueError('Premature empty title page')
        page+=1
    if len({(r['source_url'],r['publication_date']) for r in records})!=len(records):raise ValueError('Duplicate titles')
    result=dict(instrument_id=sid,start=start,end=end,reported_count=total,returned_count=len(records),complete=len(records)==total,records=records,captures=captures)
    save(REPORT/'titles'/ (label_prefix+'_'+sid+'.json'),result)
    return result

def formation_titles():
    from decimal import Decimal
    from m7_data_audit import calendar
    sessions=calendar();end=sessions.index('2019-12-31');window=sessions[end-59:end+1]
    for r in json.loads((REPORT/'PRODUCT_REVIEW.json').read_bytes())['records']:
        if r['status']!='INCLUDED_PENDING_FORMATION':continue
        sid=r['instrument_id'];payload=json.loads((OUT/'decoded'/('formation_'+sid+'.json')).read_bytes())
        observations={x[0]:dict(zip(payload['fields'],x)) for x in payload['rows']}
        amounts=sorted(Decimal(observations[d]['amount']) for d in window if d in observations)
        if len(amounts)==60 and (amounts[29]+amounts[30])/2<20000000:continue
        if sid.startswith('sz.1599') and (ROOT/'reports/m7_cohort/titles'/(sid+'.json')).exists():
            source=ROOT/'reports/m7_cohort/titles'/(sid+'.json');old=json.loads(source.read_bytes())
            records=[x for x in old['records'] if x['publication_date']<='2019-12-31']
            save(REPORT/'titles'/('formation_'+sid+'.json'),dict(instrument_id=sid,complete=old['complete'],records=records,source_path=str(source),source_sha256=sha(source),reused_pre2020_subset_only=True))
        else:titles_one(sid,r['published_at'],'2019-12-31','formation')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['documents','histories','formation_titles']);args=parser.parse_args()
    {'documents':documents,'histories':histories,'formation_titles':formation_titles}[args.stage]()
