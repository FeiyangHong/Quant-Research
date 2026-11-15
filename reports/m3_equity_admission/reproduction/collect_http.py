import sys,json
from pathlib import Path
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.equity_audit import fetch_http
from quant_research.providers.baostock import write_immutable
OUT=ROOT/'data/raw_equity_admission'
jobs=[]
for name in ['home','stockIndustry','dividInfo','factorInfo','seasonProfit','seasonBalance','seasonCashFlow','stockKData','StockBasicInfoAPI','dataExplain']:
    jobs.append((f'baostock_doc_{name}',f'https://baostock.com/helpdocs/api/markdown/{name}.md','POST','', 'CURRENT_PROVIDER_DOCUMENTATION_NOT_STRATEGY_DATA'))
docs={
'kangmei_original_2017':'https://static.cninfo.com.cn/finalpage/2018-04-26/1204793690.PDF',
'kangmei_revision_2019':'https://static.cninfo.com.cn/finalpage/2019-04-30/1206168283.PDF',
'kangmei_revision_2020':'https://static.cninfo.com.cn/finalpage/2020-06-18/1207936082.PDF',
'csrc_industry_2020q2_page':'https://www.csrc.gov.cn/csrc/c100103/c1451994/content.shtml',
'csrc_industry_2020q2':'https://www.csrc.gov.cn/csrc/c100103/c1451994/1451994/files/1616066674038_28028.pdf',
'shijia_industry_change_20200717':'https://static.cninfo.com.cn/finalpage/2020-07-17/1208039030.PDF',
'kangmei_st_notice_20190518':'https://static.sse.com.cn/disclosure/listedinfo/announcement/c/2019-05-18/600518_20190518_1.pdf',
'leshi_delisting_20200514':'https://disc.static.szse.cn/download/disc/disk02/finalpage/2020-05-14/b8e4ea78-2685-46cc-9b93-43aab6c8bd29.PDF',
'leshi_registration_end_20200724':'https://www.szse.cn/disclosure/notice/t20200727_580003.html',
}
for label,url in docs.items():jobs.append((label,url,'GET',None,'HISTORICAL_DOCUMENT_AUDIT_PUBLIC_ASOF_CANDIDATE'))
for code,secid,beg,end in [('maotai','1.600519','20230620','20230707'),('zhonghong','0.000979','20180903','20181231')]:
    url='https://push2his.eastmoney.com/api/qt/stock/kline/get?'+urlencode(dict(secid=secid,klt=101,fqt=0,beg=beg,end=end,fields1='f1,f2,f3,f4,f5,f6',fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'))
    jobs.append(('eastmoney_'+code,url,'GET',None,'HISTORICAL_PRICE_CROSSCHECK_NOT_PIT'))
def one(job):
    label,url,method,body,role=job
    result=fetch_http(OUT,label,url,method,body,role)
    print(json.dumps({k:v for k,v in result.items() if k not in ['request_body','raw_path']},ensure_ascii=False),flush=True)
    return result
with ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(one,jobs))
write_immutable(OUT/'http_probe_manifest.json',results)
