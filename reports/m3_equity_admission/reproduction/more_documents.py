import sys,json,subprocess
from pathlib import Path
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.equity_audit import fetch_http
from quant_research.providers.baostock import write_immutable
OUT=ROOT/'data/raw_equity_admission'
jobs=[('kangmei_2018_first','https://static.cninfo.com.cn/finalpage/2019-04-30/1206168292.PDF','GET',None),
      ('maotai_special_20231214','https://www.moutai.com.cn/mtgf/attachDir/2023/12/2023122716424647784.pdf','GET',None),
      ('cninfo_revision_discovery_2016_2024','https://www.cninfo.com.cn/new/hisAnnouncement/query','POST',urlencode(dict(pageNum=1,pageSize=20,column='szse',tabName='fulltext',stock='',searchkey='前期会计差错更正',secid='',plate='',category='',trade='',seDate='2016-01-01~2024-12-31',sortName='time',sortType='desc',isHLtitle='false')))]
def one(job):
    label,url,method,body=job
    return fetch_http(OUT,label,url,method,body)
with ThreadPoolExecutor(max_workers=3) as p:results=list(p.map(one,jobs))
for r in results:
    if r.get('content_type','').startswith('application/pdf'):
        subprocess.run(['pdftotext','-layout',r['raw_path'],str(ROOT/'work/equity_data_audit/text'/(r['id']+'.txt'))],check=True)
write_immutable(OUT/'http_more_manifest.json',results)
print(json.dumps(results,ensure_ascii=False))
