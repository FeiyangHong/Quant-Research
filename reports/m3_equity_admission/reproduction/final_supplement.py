import sys,json,subprocess
from pathlib import Path
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.equity_audit import fetch_http
from quant_research.providers.baostock import write_immutable
OUT=ROOT/'data/raw_equity_admission'
jobs=[('zhonghong_delisting_20181228','https://disc.static.szse.cn/download/disc/disk01/finalpage/2018-12-28/c0f86b35-1ad0-4f00-af09-3e491ccd1164.PDF'),('maotai_special_original_20231214','https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-12-14/600519_20231214_WR1C.pdf')]
results=[fetch_http(OUT,label,url) for label,url in jobs]
for r in results:
    if r.get('content_type','').startswith('application/pdf'):
        subprocess.run(['pdftotext','-layout',r['raw_path'],str(ROOT/'work/equity_data_audit/text'/(r['id']+'.txt'))],check=True)
prior=json.loads((OUT/'revision_candidate_queue_v2.json').read_bytes())
body=urlencode(dict(pageNum=1,pageSize=100,column='szse',tabName='fulltext',stock='',searchkey='前期会计差错更正',secid='',plate='',category='',trade='',seDate='2016-01-01~2024-10-30',sortName='time',sortType='desc',isHLtitle='false'))
listing=fetch_http(OUT,'cninfo_revision_candidates_older_partition','https://www.cninfo.com.cn/new/hisAnnouncement/query','POST',body)
results.append(listing)
rows=json.loads(Path(listing['raw_path']).read_bytes()).get('announcements',[])
seen={(r['instrument_id'][3:],r['publication_date']) for r in prior['cases']};chosen=[]
for row in rows:
    code=row['secCode'];day=row['adjunctUrl'].split('/')[1]
    if day>'2024-10-30':raise ValueError('Bad date boundary')
    if not code.startswith(('000','001','002','003','300','301','600','601','603','605')):continue
    if '公告' not in row['announcementTitle'] or '差错更正' not in row['announcementTitle']:continue
    if (code,day) in seen:continue
    seen.add((code,day));chosen.append(row)
    if len(chosen)+len(prior['cases'])==20:break
def one(row):
    doc=fetch_http(OUT,'revision_candidate_'+row['secCode']+'_'+row['announcementId'],'https://static.cninfo.com.cn/'+row['adjunctUrl'])
    if doc.get('content_type','').startswith('application/pdf'):
        subprocess.run(['pdftotext','-layout',doc['raw_path'],str(ROOT/'work/equity_data_audit/text'/('candidate_'+row['announcementId']+'.txt'))],check=True)
    return dict(instrument_id=('sh.' if row['secCode'].startswith('6') else 'sz.')+row['secCode'],announcement_id=row['announcementId'],title=row['announcementTitle'],publication_date=row['adjunctUrl'].split('/')[1],publication_precision='date_only',source_timestamp_raw=row.get('announcementTime'),timestamp_semantics='UNVERIFIED_NOT_INTRADAY',role='RETROSPECTIVE_AUDIT_SAMPLING_NOT_UNIVERSE_SELECTION',source=doc,case_status='ORIGINAL_VINTAGE_NOT_YET_PAIRED',counts_toward_20_case_gate=False)
with ThreadPoolExecutor(max_workers=3) as pool:extra=list(pool.map(one,chosen))
write_immutable(OUT/'http_final_manifest.json',results)
write_immutable(OUT/'revision_candidate_queue_v3.json',dict(selection='20 main-board/ChiNext distinct issuer-publication-date events in descending dates; explicit older date partition after repeated page; audit sampling only',listings=prior['listings']+[listing],cases=prior['cases']+extra,passed_case_count=0))
print('Candidates',len(prior['cases'])+len(extra))
