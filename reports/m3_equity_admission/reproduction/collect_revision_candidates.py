"""Acquire a bounded 20-event documentary queue; NOT 20 passed PIT cases."""
import sys,json,time,subprocess,hashlib
from pathlib import Path
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.equity_audit import fetch_http
from quant_research.providers.baostock import write_immutable
OUT=ROOT/'data/raw_equity_admission'
body=urlencode(dict(pageNum=1,pageSize=100,column='szse',tabName='fulltext',stock='',searchkey='前期会计差错更正',secid='',plate='',category='',trade='',seDate='2016-01-01~2024-12-31',sortName='time',sortType='desc',isHLtitle='false'))
listing=fetch_http(OUT,'cninfo_revision_candidates_100','https://www.cninfo.com.cn/new/hisAnnouncement/query','POST',body)
data=json.loads(Path(listing['raw_path']).read_bytes())
chosen=[];seen=set()
for row in data.get('announcements',[]):
    code=row['secCode'];day=row['adjunctUrl'].split('/')[1]
    if day>'2024-12-31':raise ValueError('Unexpected sealed document')
    if not code.startswith(('000','001','002','003','300','301','600','601','603','605')):continue
    if '公告' not in row['announcementTitle'] or '差错更正' not in row['announcementTitle']:continue
    key=(code,day)
    if key in seen:continue
    seen.add(key);chosen.append(row)
    if len(chosen)==20:break
def one(row):
    doc=fetch_http(OUT,'revision_candidate_'+row['secCode']+'_'+row['announcementId'],'https://static.cninfo.com.cn/'+row['adjunctUrl'])
    rec=dict(instrument_id=('sh.' if row['secCode'].startswith('6') else 'sz.')+row['secCode'],
             announcement_id=row['announcementId'],title=row['announcementTitle'],
             publication_date=row['adjunctUrl'].split('/')[1],publication_precision='date_only',
             source_timestamp_raw=row.get('announcementTime'),timestamp_semantics='UNVERIFIED_NOT_INTRADAY',
             role='RETROSPECTIVE_AUDIT_SAMPLING_NOT_UNIVERSE_SELECTION',source=doc,
             case_status='ORIGINAL_VINTAGE_NOT_YET_PAIRED',counts_toward_20_case_gate=False)
    if doc.get('content_type','').startswith('application/pdf'):
        target=ROOT/'work/equity_data_audit/text'/('candidate_'+row['announcementId']+'.txt')
        subprocess.run(['pdftotext','-layout',doc['raw_path'],str(target)],check=True)
    print(row['secCode'],row['announcementTitle'],doc['status'],flush=True)
    return rec
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,chosen))
write_immutable(OUT/'revision_candidate_queue.json',dict(selection='First 20 distinct main-board/ChiNext issuer-publication-date correction announcements in descending publication order, bounded first 100 query results; diagnostic sampling, no returns used',listing=listing,cases=results,passed_case_count=0))
