"""Only frozen selected products: source collection for full holding dependencies."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from m8_data_collect import ROOT, OUT, REPORT, save, sha, issue, titles_one, document, known_sources, baostock_session, HISTORY_FIELDS, Query, validate_response

def selection():
    path=REPORT/'COHORT_SELECTION.json';data=json.loads(path.read_bytes())
    if data['status']!='FORMED' or len(data['selected_instruments']) not in range(6,11):raise ValueError('Frozen selected cohort required')
    return data

def histories():
    selected=selection()['selected_instruments']
    save(REPORT/'HOLDING_HISTORY_REQUESTS.json',dict(selected_instruments=selected,start='2019-01-01',end='2024-12-31',adjustment='RAW',formation_sha256=sha(REPORT/'COHORT_SELECTION.json'),registered_at=datetime.now(timezone.utc).isoformat()))
    with baostock_session(scope='rotation',label='holding_login',dates='2019-01-01~2024-12-31') as (bs,active):
        login=bs.login()
        if login.error_code!='0':raise RuntimeError(login.error_msg)
        try:
            for sid in selected:
                path=OUT/'decoded'/('holding_'+sid+'.json')
                if path.exists():continue
                prior=ROOT/'data/raw_m7/decoded'/('history_'+sid+'.json')
                if prior.exists():
                    old=json.loads(prior.read_bytes())
                    payload=dict(old,rows=[r for r in old['rows'] if '2019-01-01'<=r[0]<='2024-12-31'],
                        reused_source_path=str(prior),reused_source_sha256=sha(prior),slice_only='2019-01-01~2024-12-31')
                else:
                    active[0]='holding_'+sid;query=Query(kind='history',code=sid,start='2019-01-01',end='2024-12-31')
                    started=datetime.now(timezone.utc).isoformat()
                    rs=bs.query_history_k_data_plus(sid,HISTORY_FIELDS,start_date=query.start,end_date=query.end,frequency='d',adjustflag='3')
                    rows=[]
                    while rs.error_code=='0' and rs.next():rows.append(rs.get_row_data())
                    payload=dict(status='SUCCESS' if rs.error_code=='0' else 'FAILED',fields=rs.fields,rows=rows,query=vars(query),
                        error_code=rs.error_code,error_msg=rs.error_msg,source='BaoStock',requested_at=started,ingested_at=datetime.now(timezone.utc).isoformat())
                    if payload['status']=='SUCCESS':validate_response(query,payload)
                save(path,payload);print(sid,payload['status'],len(payload['rows']),flush=True)
        finally:active[0]='holding_logout';bs.logout()

def titles():
    for sid in selection()['selected_instruments']:
        old=ROOT/'reports/m7_cohort/titles'/(sid+'.json')
        if old.exists():
            data=json.loads(old.read_bytes());data=dict(data,records=[r for r in data['records'] if '2019-01-01'<=r['publication_date']<='2024-12-31'],reused_source_path=str(old),reused_source_sha256=sha(old))
            save(REPORT/'titles'/('holding_'+sid+'.json'),data)
        else:titles_one(sid,'2019-01-01','2024-12-31','holding')

def annual2024_titles():
    allrows=[]
    for sid in selection()['selected_instruments']:
        start,end='2025-01-01','2025-04-30'
        if sid.startswith('sh.'):
            title_key='二0二四年年度报告' if sid=='sh.512710' else '2024年年度报告'
            query=dict(isPagination='true',type='inParams',sqlId='COMMON_PL_JJXX_JJGG_NEW_L',TITLE=title_key,SECURITY_CODE=sid[3:],START_DATE=start,END_DATE=end,BULLETIN_TYPE='',DATE_DESC=1)
            query.update({'pageHelp.pageSize':100,'pageHelp.pageNo':1,'pageHelp.beginPage':1,'pageHelp.cacheSize':1,'pageHelp.endPage':1})
            label='annual2024_titles_'+sid+('_chinese_year' if sid=='sh.512710' else '')
            cap=issue(label,'https://query.sse.com.cn/commonQuery.do?'+urlencode(query),dates=start+'~'+end,route='retrospective_2024_annual',headers={'Referer':'https://www.sse.com.cn/'})
            if cap['status']!='FETCHED':continue
            payload=json.loads(Path(cap['raw_path']).read_bytes())
            if int(payload['pageHelp']['total'])!=len(payload['result']):raise ValueError('Annual metadata requires additional exact page')
            rows=[dict(instrument_id=sid,title=r['TITLE'],publication_date=r['SSEDATE'],source_url='https://www.sse.com.cn'+r['URL']) for r in payload['result']]
        else:
            body=json.dumps(dict(seDate=[start,end],channelCode=['fundinfoNotice_disc'],stock=[sid[3:]],searchKey=['2024年年度报告'],pageSize=50,pageNum=1),separators=(',',':'))
            cap=issue('annual2024_titles_'+sid+'_after_local_begin_failure','https://www.szse.cn/api/disc/announcement/annList',body,dates=start+'~'+end,route='retrospective_2024_annual',headers={'Referer':'https://www.szse.cn/','Content-Type':'application/json'})
            if cap['status']!='FETCHED':continue
            payload=json.loads(Path(cap['raw_path']).read_bytes())
            if int(payload['announceCount'])!=len(payload['data']):raise ValueError('Annual metadata requires additional exact page')
            rows=[dict(instrument_id=sid,title=r['title'],publication_date=r['publishTime'][:10],source_url='https://disc.static.szse.cn/download'+r['attachPath']) for r in payload['data']]
        for row in rows:
            if not any(y in row['title'] for y in ['2024','二0二四']) or '年度报告' not in row['title']:raise ValueError('Nonannual or wrong year title returned')
            row.update(documentary_only=True,historical_fact_end='2024-12-31',not_signal_input=True,metadata_receipt=cap)
        allrows+=rows;save(REPORT/'ANNUAL_2024_DOCUMENT_REQUESTS.json',allrows)

def documents():
    requests=[]
    for sid in selection()['selected_instruments']:
        data=json.loads((REPORT/'titles'/('holding_'+sid+'.json')).read_bytes())
        for r in data['records']:
            title=r['title'];normalized_title=title
            for a,b in [('二0二0','2020'),('二0二一','2021'),('二0二二','2022'),('二0二三','2023'),('二0二四','2024')]:normalized_title=normalized_title.replace(a,b)
            year=re.search(r'(20\d{2})年?年度报告',normalized_title)
            annual=year and 2019<=int(year[1])<=2023 and '摘要' not in title and '提示' not in title
            event=bool(re.search(r'分红|收益分配|拆分|份额折算|终止上市|清算|标的指数.*变更|变更.*标的指数|转型|(?:修改|修订).*合同|更名',title)) and not any(word in title for word in ['联接','风险提示','流动性服务商'])
            if annual or event:
                requests.append(dict(r,kind='ANNUAL' if annual else 'EVENT_OR_LIFECYCLE',report_year=int(year[1]) if annual else None))
    for r in json.loads((REPORT/'ANNUAL_2024_DOCUMENT_REQUESTS.json').read_bytes()):
        if '摘要' not in r['title'] and '提示' not in r['title']:requests.append(dict(r,kind='ANNUAL',report_year=2024))
    save(REPORT/'HOLDING_DOCUMENT_REQUESTS.json',requests)
    result=[]
    for i,row in enumerate(requests):
        label='holding_doc_'+row['instrument_id']+'_'+row['publication_date']+'_'+str(i)
        if row.get('report_year')==2024:
            cap=issue(label,row['source_url'],dates='2025-01-01~2025-04-30',route='retrospective_2024_annual')
            fact=dict(row,receipt=cap)
            if cap['status']=='FETCHED':
                import subprocess
                text=OUT/'text'/(cap['sha256']+'.txt');text.parent.mkdir(parents=True,exist_ok=True)
                if not text.exists():subprocess.run(['pdftotext','-layout',str(cap['raw_path']),str(text)],check=True,capture_output=True)
                fact.update(text_path=str(text),text_sha256=sha(text))
        else:
            # All documentary responses are bounded by the selected historical period.
            prior=known_sources().get(row['source_url'])
            cap=prior or issue(label,row['source_url'],dates='2019-01-01~2024-12-31')
            import subprocess
            fact=dict(row,receipt=cap)
            if cap['status'] in ('FETCHED','SUCCESS'):
                text=OUT/'text'/(cap['sha256']+'.txt');text.parent.mkdir(parents=True,exist_ok=True)
                if not text.exists():subprocess.run(['pdftotext','-layout',str(cap['raw_path']),str(text)],check=True,capture_output=True)
                fact.update(text_path=str(text),text_sha256=sha(text))
        result.append(fact);save(REPORT/'holding_documents.json',result)

def secondary():
    from collect_eastmoney_check import parse_payload
    result=[]
    for sid in selection()['selected_instruments']:
        args=dict(secid=('1.' if sid.startswith('sh.') else '0.')+sid[3:],beg='20190101',end='20241231',klt=101,fqt=0,lmt=10000,
                  fields1='f1,f2,f3,f4,f5,f6',fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61')
        cap=issue('secondary_'+sid,'https://push2his.eastmoney.com/api/qt/stock/kline/get?'+urlencode(args),dates='2019-01-01~2024-12-31',route='selected_raw_prices')
        row=dict(instrument_id=sid,receipt=cap)
        if cap['status']=='FETCHED':
            records=parse_payload(Path(cap['raw_path']).read_bytes(),sid,'2019-01-01','2024-12-31')
            path=OUT/'decoded'/('secondary_'+sid+'.json');save(path,records)
            row.update(status='SUCCESS' if records else 'EMPTY_RESPONSE',record_count=len(records),normalized_path=str(path),normalized_sha256=sha(path))
        result.append(row);save(REPORT/'SECONDARY_SOURCES.json',result)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['histories','titles','annual2024_titles','documents','secondary']);args=parser.parse_args()
    globals()[args.stage]()
