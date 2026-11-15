"""Explicit finite documentary pilot, with requests registered before sending.

No market SDK, prices or strategy metrics are requested by this program.
The shared M6 collector owns the global ledger and official-domain allowlist.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from m6_sources import ROOT, fetch

OUT = ROOT / 'reports/m6_r1i'
DATES = '2010-01-01~2024-12-31'


def issue(label, url, *, body=None, headers=None, route='official_documents'):
    plan_path = OUT / 'pilot_request_log.json'
    requests = json.loads(plan_path.read_bytes()) if plan_path.exists() else []
    matches = [r for r in requests if r['label'] == label]
    if matches:
        if matches[-1].get('receipt'):
            return matches[-1]['receipt']
        raise RuntimeError('Unresolved preregistered pilot request; do not blindly retry')
    if (OUT/'source_evidence.json').exists():
        raise RuntimeError('This finite source pilot is closed; no automatic extension')
    book_path=ROOT/'data/raw_m6/budget.json'
    actual_requests=json.loads(book_path.read_bytes())['attempts'] if book_path.exists() else []
    if sum(r['scope']=='r1i' for r in actual_requests) >= 48:
        raise RuntimeError('Finite 48-request pilot exhausted')
    registered = dict(label=label, url=url, body=body, headers=headers, dates=DATES, route=route,
                      scope='r1i', registered_at=datetime.now(timezone.utc).isoformat())
    requests.append(registered)
    plan_path.write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    kwargs = dict(dates=DATES, scope='r1i', route=route)
    if headers:
        kwargs['headers'] = headers
    receipt = fetch(label, url, body, **kwargs)
    registered['receipt'] = receipt
    plan_path.write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt.get(k) for k in ['id','label','status','byte_count','sha256','raw_path']},ensure_ascii=False))
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['known','sse_batch','szse_batch'])
    parser.add_argument('--page',type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.page<=30:
        raise ValueError('Pilot page bound')
    if args.stage == 'known':
        issue('r1i_csi_method_2023','https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H30199_Index_Methodology_cn.pdf')
        issue('r1i_financial_realestate_2015','https://static.cninfo.com.cn/finalpage/2015-04-14/1200828055.PDF')
    elif args.stage == 'sse_batch':
        page=args.page
        query={'isPagination':'true','pageHelp.pageSize':100,'pageHelp.pageNo':page,
               'pageHelp.beginPage':page,'pageHelp.cacheSize':1,'pageHelp.endPage':page,
               'type':'inParams','sqlId':'COMMON_PL_JJXX_JJGG_NEW_L','TITLE':'上市交易公告书',
               'SECURITY_CODE':'','START_DATE':'2010-01-01','END_DATE':'2024-12-31',
               'BULLETIN_TYPE':'','DATE_DESC':1}
        issue('r1i_sse_listing_page_'+str(page),'https://query.sse.com.cn/commonQuery.do?'+urlencode(query),headers={'Referer':'https://www.sse.com.cn/'},route='historical_etf_listing')
    else:
        body=json.dumps({'seDate':['2010-01-01','2024-12-31'],'channelCode':['fundinfoNotice_disc'],
                         'searchKey':['上市交易公告书'],'pageSize':50,'pageNum':args.page},ensure_ascii=False,separators=(',',':'))
        issue('r1i_szse_listing_page_'+str(args.page),'https://www.szse.cn/api/disc/announcement/annList',body=body,
              headers={'Content-Type':'application/json','Referer':'https://www.szse.cn/'})


if __name__ == '__main__':
    main()
