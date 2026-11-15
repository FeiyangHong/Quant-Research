"""M7 seven-product historical source collection; no strategy returns."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from m7_sources import ROOT, OUT, fetch, reuse, baostock_session
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.providers.baostock import HISTORY_FIELDS, Query, validate_response

REPORT = ROOT / 'reports/m7_cohort'
COHORT = ['sz.' + x for x in ['159936','159938','159939','159940','159944','159945','159946']]

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def issue(label, url, body=None, dates='2010-01-01~2024-12-31', headers=None):
    path=REPORT/'request_log.json'
    rows=json.loads(path.read_bytes()) if path.exists() else []
    old=[r for r in rows if r['label']==label]
    if old:
        if old[-1]['url']!=url or old[-1].get('body')!=body:
            raise RuntimeError('Request label collision with a different source '+label)
        if old[-1].get('receipt'): return old[-1]['receipt']
        raise RuntimeError('Unresolved registered request '+label)
    rec=dict(label=label,url=url,body=body,dates=dates,headers=headers,registered_at=datetime.now(timezone.utc).isoformat())
    rows.append(rec);save(path,rows)
    rec['receipt']=fetch(label,url,body,dates=dates,scope='cohort',headers=headers)
    save(path,rows)
    print(label,rec['receipt']['status'],rec['receipt'].get('byte_count'),flush=True)
    return rec['receipt']

def plan():
    inventory=json.loads((ROOT/'reports/m6_r1i/official_listing_inventory.json').read_bytes())
    listings=[r['original_listing_title_evidence'][0] for r in inventory['records'] if r['instrument_id'] in COHORT]
    save(REPORT/'SOURCE_PLAN.json',dict(scope='R1I_FIXED_COHORT_V1',registered_at=datetime.now(timezone.utc).isoformat(),
        cohort=COHORT,sequence=['raw_amounts_identity_state','monthly_eligibility','necessary_TR_actions_exit_rights','independent_source_review','real_accounts'],
        http_estimate=dict(initial_listing_cohort_exit=8,historical_all_titles=50,necessary_annual_action_documents=100,total=158,reserve=98),
        sdk_estimate=dict(login_logout=2,seven_histories=7,estimated_extra_pages=14,total=23,reserve=105),
        bytes_estimate=100*1024*1024,total_limits=dict(http=256,sdk=128,bytes=256*1024*1024),
        listings=listings,market_end='2024-12-31',dead_member_history_end='2018-12-27',
        reuse=['HS300TR2010_2024','exchange_calendar2010_2024','sz159940_original_listing','sz159946_2017_annual_and_titles'],
        limits_are_global_not_pilot=True,returns_inspected=False))

def initial_documents():
    p=json.loads((REPORT/'SOURCE_PLAN.json').read_bytes())
    issue('cohort_20160104','https://www.gffunds.com.cn/jjgg/zdsj/201601/t20160104_49348.shtml')
    issue('exit_159946_20181226','https://epaper.cs.com.cn/zgzqb/html/2018-12/26/nw.D110000zgzqb_20181226_5-B004.htm')
    for row in p['listings']:
        if row['instrument_id']=='sz.159940':continue
        issue('listing_'+row['instrument_id'],row['source_url'])

def histories():
    with baostock_session(scope='cohort',label='m7_login',dates='2014-01-01~2024-12-31') as (bs, active):
        login=bs.login()
        if login.error_code!='0':raise RuntimeError('SDK login failed '+login.error_msg)
        try:
            for sid in COHORT:
                path=OUT/'decoded'/('history_'+sid+'.json')
                if path.exists():continue
                active[0]='history_'+sid
                end='2018-12-27' if sid=='sz.159946' else '2024-12-31'
                query=Query(kind='history',code=sid,start='2014-01-01',end=end)
                started=datetime.now(timezone.utc).isoformat()
                rs=bs.query_history_k_data_plus(sid,HISTORY_FIELDS,start_date=query.start,end_date=end,frequency='d',adjustflag='3')
                rows=[]
                while rs.error_code=='0' and rs.next():rows.append(rs.get_row_data())
                payload=dict(status='SUCCESS' if rs.error_code=='0' else 'FAILED',fields=rs.fields,rows=rows,
                    query=vars(query),error_code=rs.error_code,error_msg=rs.error_msg,source='BaoStock',
                    requested_at=started,ingested_at=datetime.now(timezone.utc).isoformat(),snapshot_format='Decoded SDK records; original response text archived in shared ledger')
                if payload['status']=='SUCCESS':validate_response(query,payload)
                save(path,payload)
                print(sid,payload['status'],len(rows),flush=True)
        finally:
            active[0]='m7_logout';bs.logout()

def titles():
    for sid in COHORT:
        records=[];total=None;page=1
        end='2018-12-31' if sid=='sz.159946' else '2024-12-31'
        while total is None or len(records)<total:
            body=json.dumps(dict(seDate=['2014-01-01',end],channelCode=['fundinfoNotice_disc'],stock=[sid[3:]],pageSize=50,pageNum=page),separators=(',',':'))
            cap=issue('titles_'+sid+'_'+str(page),'https://www.szse.cn/api/disc/announcement/annList',body,
                dates='2014-01-01~'+end,headers={'Content-Type':'application/json','Referer':'https://www.szse.cn/'})
            if cap['status']!='FETCHED':break
            data=json.loads(Path(cap['raw_path']).read_bytes());n=int(data['announceCount'])
            if total is None:total=n
            if total!=n:raise RuntimeError('Unstable title count')
            for r in data['data']:
                if sid[3:] not in r['secCode'] or not '2014-01-01'<=r['publishTime'][:10]<=end:raise RuntimeError('Miskeyed title')
                records.append(dict(instrument_id=sid,title=r['title'],publication_date=r['publishTime'][:10],source_url='https://disc.static.szse.cn/download'+r['attachPath'],source_record=r))
            if not data['data']:raise RuntimeError('Premature empty title page')
            page+=1
        save(REPORT/'titles'/ (sid+'.json'),dict(instrument_id=sid,reported_count=total,returned_count=len(records),complete=len(records)==total,records=records))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['plan','initial','histories','titles']);args=parser.parse_args()
    {'plan':plan,'initial':initial_documents,'histories':histories,'titles':titles}[args.stage]()
