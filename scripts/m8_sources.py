"""M8 historical-liquidity collector. Every caller must register its fixed requests first."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.budget import BudgetLedger, atomic_json, exclusive_lock

OUT = ROOT / 'data/raw_m8'
LIMITS = dict(http_attempts=512, baostock_wire_attempts=256, new_body_bytes=512*1024*1024)
SCOPES = {'rotation':dict(LIMITS)}
OFFICIAL = {'www.cninfo.com.cn','static.cninfo.com.cn','www.csrc.gov.cn','www.sse.com.cn',
            'www.szse.cn','investor.szse.cn','disc.static.szse.cn','www.chinaclear.cn',
            'www.chinatax.gov.cn','www.gov.cn','fgk.chinatax.gov.cn',
            'www.mof.gov.cn','tianjin.chinatax.gov.cn','guangdong.chinatax.gov.cn',
            'www.csindex.com.cn','oss-ch.csindex.com.cn','m.chinaclear.cn',
            'jrj.wuhan.gov.cn','jrj.sh.gov.cn','www.gffunds.com.cn','epaper.cs.com.cn','big5.sse.com.cn'}


def ledger():
    if not (ROOT/'docs/M8_PLAN.md').exists():
        raise RuntimeError('M8 plan must be registered before collection')
    return BudgetLedger(OUT, LIMITS, scope_limits=SCOPES)


def validate_dates(dates):
    bounds=dates.split('~')
    if len(bounds)!=2 or not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in bounds) or not ('1990-01-01'<=bounds[0]<=bounds[1]<='2024-12-31'):
        raise ValueError('Explicit bounded pre-2025 documentary/market dates required')
    return bounds


def validate_url(url, *, dates, route='official_documents', body=None):
    retrospective=route=='retrospective_2024_annual'
    if retrospective:
        bounds=dates.split('~')
        if bounds!=['2025-01-01','2025-04-30']:
            raise ValueError('2024 annual retrospective exception has exact publication window')
        selection=json.loads((ROOT/'reports/m8_rotation/COHORT_SELECTION.json').read_bytes())
        if selection.get('status')!='FORMED':raise ValueError('Annual audit requires frozen formed cohort')
        selected={sid.split('.')[1] for sid in selection['selected_instruments']}
        if not (ROOT/'reports/m8_rotation/SOURCE_POLICY_ADDENDUM.md').exists():raise ValueError('Annual source exception not registered')
    else:bounds=validate_dates(dates)
    parsed=urlparse(url)
    hosts=OFFICIAL|{'query.sse.com.cn'} if retrospective else OFFICIAL if route=='official_documents' else {'query.sse.com.cn'} if route in {'historical_etf_listing','historical_etf_announcements'} else {'web.ifzq.gtimg.cn'} if route=='selected_raw_price_crosscheck' else {'push2his.eastmoney.com'} if route=='selected_raw_prices' else {'datacenter-web.eastmoney.com'} if route=='historical_shares' else {'cn.bing.com','www.bing.com','www.google.com','www.google.com.hk','www.baidu.com'} if route in {'historical_rule_discovery','historical_industry_discovery'} else set()
    if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError('Registered HTTPS source host required')
    decoded=unquote(url + ' ' + (body or ''))
    if not retrospective and any(d>'2024-12-31' for d in re.findall(r'20\d{2}-\d{2}-\d{2}',decoded)):
        raise ValueError('Post-2024 source request rejected')
    if retrospective:
        if parsed.hostname=='query.sse.com.cn':
            query=parse_qs(parsed.query,keep_blank_values=True)
            if (parsed.path!='/commonQuery.do' or query.get('SECURITY_CODE',[''])[0] not in selected
                or query.get('TITLE',[''])[0] not in {'2024年年度报告','二0二四年年度报告'} or query.get('START_DATE')!=[bounds[0]] or query.get('END_DATE')!=[bounds[1]]):
                raise ValueError('Only selected 2024 annual title metadata allowed')
        elif parsed.hostname=='www.szse.cn' and parsed.path=='/api/disc/announcement/annList':
            request=json.loads(body or '{}')
            if request.get('seDate')!=bounds or request.get('searchKey')!=['2024年年度报告'] or len(request.get('stock',[]))!=1 or request['stock'][0] not in selected:
                raise ValueError('Only selected 2024 annual title metadata allowed')
        else:
            registry=ROOT/'reports/m8_rotation/ANNUAL_2024_DOCUMENT_REQUESTS.json'
            documents=json.loads(registry.read_bytes()) if registry.exists() else []
            if not any(r['source_url']==url and r['instrument_id'].split('.')[1] in selected and ('2024' in r['title'] or '二0二四' in r['title']) and '年度报告' in r['title'] for r in documents):
                raise ValueError('Exact selected 2024 annual PDF must be preregistered')
    if route=='selected_raw_prices':
        selection=json.loads((ROOT/'reports/m8_rotation/COHORT_SELECTION.json').read_bytes())
        selected={(('1.' if sid.startswith('sh.') else '0.')+sid[3:]) for sid in selection['selected_instruments']}
        query=parse_qs(parsed.query)
        if (selection.get('status')!='FORMED' or parsed.path!='/api/qt/stock/kline/get'
            or query.get('secid',[''])[0] not in selected or query.get('fqt')!=['0']
            or query.get('beg')!=[bounds[0].replace('-','')] or query.get('end')!=[bounds[1].replace('-','')]):
            raise ValueError('Only selected bounded unadjusted ETF price comparison allowed')
    if route=='selected_raw_price_crosscheck':
        selection=json.loads((ROOT/'reports/m8_rotation/COHORT_SELECTION.json').read_bytes())
        parts=parse_qs(parsed.query,keep_blank_values=True).get('param',[''])[0].split(',')
        if (selection.get('status')!='FORMED' or parsed.path!='/appstock/app/fqkline/get' or len(parts)!=6
            or parts[0] not in {sid.replace('.','') for sid in selection['selected_instruments']}
            or parts[1]!='day' or parts[2:4]!=bounds or parts[4:]!=['640','']):
            raise ValueError('Only selected bounded raw day crosscheck allowed')
    if parsed.hostname=='www.cninfo.com.cn' and parsed.path=='/new/hisAnnouncement/query':
        actual=parse_qs(body or '').get('seDate',[])
        if actual != [dates]:
            raise ValueError('CNInfo body must contain exact registered date bounds')
    if route=='historical_shares':
        query=parse_qs(parsed.query)
        if parsed.path!='/api/data/v1/get' or query.get('reportName')!=['RPT_F10_EH_EQUITY'] or bounds!=['2020-07-31','2020-07-31']:
            raise ValueError('Only registered historical-share route/date allowed')
        if 'END_DATE<=\'2020-07-31\'' not in query.get('filter',[''])[0]:
            raise ValueError('Historical-share server-side cutoff required')
    if route=='historical_etf_listing':
        query=parse_qs(parsed.query,keep_blank_values=True)
        if (parsed.path!='/commonQuery.do' or body is not None
            or query.get('sqlId')!=['COMMON_PL_JJXX_JJGG_NEW_L']
            or query.get('START_DATE')!=[bounds[0]] or query.get('END_DATE')!=[bounds[1]]
            or query.get('TITLE')!=['上市交易公告书']):
            raise ValueError('Only fixed historical ETF listing-title query allowed')
    if route=='historical_etf_announcements':
        query=parse_qs(parsed.query,keep_blank_values=True)
        if (parsed.path!='/commonQuery.do' or body is not None
            or query.get('sqlId')!=['COMMON_PL_JJXX_JJGG_NEW_L']
            or query.get('START_DATE')!=[bounds[0]] or query.get('END_DATE')!=[bounds[1]]
            or not re.fullmatch(r'\d{6}',query.get('SECURITY_CODE',[''])[0])):
            raise ValueError('Only fixed code and date bounded ETF announcements allowed')
    if route in {'historical_rule_discovery','historical_industry_discovery'}:
        query=parse_qs(parsed.query)
        key='wd' if parsed.hostname=='www.baidu.com' else 'q'
        search_path='/s' if parsed.hostname=='www.baidu.com' else '/search'
        if parsed.path!=search_path or not query.get(key) or body is not None:
            raise ValueError('Only bounded historical rule search queries allowed')
        terms=('交易规则','过户费','印花税','chinaclear','交易费用') if route=='historical_rule_discovery' else ('中证','csindex','行业分类','指数编制')
        if not any(word in query[key][0].lower() for word in terms):
            raise ValueError('Registered historical discovery purpose required')


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused; validate and register destination separately: ' + newurl)


def fetch(label, url, body=None, *, dates, scope, route='official_documents', headers=None):
    validate_url(url,dates=dates,route=route,body=body)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):
        raise ValueError('Safe manifest label required')
    with exclusive_lock(OUT/'network.lock'):
        book=ledger()
        idx=book.begin('http_attempts',label,scope=scope,url=url,request_body=body,dates=dates,route=route,method='POST' if body is not None else 'GET')
        started=time.perf_counter();payload=b''
        try:
            request_headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/',
                             'Content-Type':'application/x-www-form-urlencoded'}
            if headers:
                if set(headers)-{'Referer','Content-Type','Accept'}:
                    raise ValueError('Only documentary request headers may be overridden')
                request_headers.update(headers)
            request=Request(url,data=body.encode() if body is not None else None,headers=request_headers)
            with build_opener(NoRedirects()).open(request,timeout=30) as response:
                remaining=book.remaining(scope)
                while len(payload)<remaining:
                    chunk=response.read(min(65536,remaining-len(payload)))
                    if not chunk:break
                    payload+=chunk
                terminal=dict(status='FETCHED' if len(payload)<remaining else 'TRUNCATED_BUDGET',
                              http_status=response.status,content_type=response.headers.get('Content-Type'))
        except Exception as exc:
            terminal=dict(status='FAILED',error=type(exc).__name__+': '+str(exc))
        rec=book.finish(idx,payload,started,**terminal)
        atomic_json(OUT/'manifests'/f'{idx:04d}_{label}.json',rec)
        return rec


def begin_external(label, *, scope, query, dates):
    """Reserve a tool-visible request while holding the shared network lease.

    The caller must finish even a failed tool call. A lost token/abandoned lease
    fails closed, never ages out automatically or resets consumed budget.
    """
    validate_dates(dates)
    OUT.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    lock=OUT/'network.lock'
    deadline=time.monotonic()+50
    while True:
        try:
            descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic()>=deadline:
                raise RuntimeError('Network lease unavailable; no request reserved')
            time.sleep(.05)
    try:
        os.write(descriptor,token.encode());os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        idx=ledger().begin('http_attempts',label,scope=scope,route='external_metadata_tool',query=query,dates=dates)
    except BaseException:
        lock.unlink()
        raise
    return dict(id=idx,lease_token=token,started_at=datetime.now(timezone.utc).isoformat())


def finish_external(ticket, payload, *, failed=False, **metadata):
    lock=OUT/'network.lock'
    if not lock.exists() or lock.read_text()!=ticket['lease_token']:
        raise RuntimeError('External response requires its own active network lease')
    elapsed=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(ticket['started_at'])).total_seconds())
    try:
        rec=ledger().finish(ticket['id'],payload,time.perf_counter()-elapsed,
            status='FAILED' if failed else 'FETCHED',
            byte_observation='VISIBLE_TOOL_RESPONSE_UTF8_ONLY_BACKGROUND_TRANSPORT_UNKNOWN',**metadata)
        atomic_json(OUT/'manifests'/f"{rec['id']:04d}_{rec['label']}.json",rec)
        return rec
    finally:
        lock.unlink()


def query_cninfo(label, code, key, dates, *, scope, org_id=None, page=1):
    validate_dates(dates)
    verified={}
    paths=list((ROOT/'data/raw_equity_admission/http').glob('cninfo_revision_candidates*.bin'))+list((ROOT/'data/raw_m4_equity/objects').glob('*.bin'))+list((ROOT/'data/raw_m5_equity/objects').glob('*.bin'))+list((OUT/'objects').glob('*.bin'))
    for path in paths:
        try: data=json.loads(path.read_bytes())
        except (ValueError,UnicodeError):continue
        if isinstance(data,dict):
            for row in data.get('announcements') or []:
                if row.get('secCode') and row.get('orgId'):verified[row['secCode']]=row['orgId']
    verified.setdefault('600518','gssh0600518')  # M4 verified issuer identity
    org_id=org_id or verified.get(code)
    if code and not org_id:
        raise ValueError('Verified organization ID required for issuer filter')
    body=urlencode(dict(pageNum=page,pageSize=100,column='szse',tabName='fulltext',stock=f'{code},{org_id}' if code else '',searchkey=key,secid='',plate='',category='',trade='',seDate=dates,sortName='time',sortType='asc',isHLtitle='false'))
    return fetch(label,'https://www.cninfo.com.cn/new/hisAnnouncement/query',body,dates=dates,scope=scope)


def reuse(path, *, expected_sha256=None):
    path=Path(path);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and expected_sha256!=digest:raise ValueError('Reused source hash mismatch')
    return dict(raw_path=str(path.resolve()),sha256=digest,byte_count=path.stat().st_size,
                provenance_origin='REUSED_EXISTING_LOCAL_SOURCE',new_network_bytes=0,new_attempts=0)


@contextmanager
def baostock_session(*, scope, label, dates):
    """Yields SDK and mutable [request_label]. Caller explicitly logs in/out.

    SDK buffers an entire response before returning: an overshoot is recorded
    durably and stops later requests, but cannot guarantee zero wire overrun.
    """
    validate_dates(dates)
    with exclusive_lock(OUT/'baostock.session.lock'):
        sys.path.insert(0,str(ROOT/'work/data_probe/baostock_sdk'))
        import baostock as bs
        import baostock.util.socketutil as sock
        original=sock.send_msg;active=[label];old_timeout=socket.getdefaulttimeout()
        def send(msg):
            message=msg.decode(errors='replace') if isinstance(msg,bytes) else str(msg)
            if any(day>'2024-12-31' for day in re.findall(r'20\d{2}-\d{2}-\d{2}',message)):
                raise ValueError('Post-2024 SDK request rejected before send')
            with exclusive_lock(OUT/'network.lock'):
                book=ledger();idx=book.begin('baostock_wire_attempts',active[0],scope=scope,dates=dates)
                started=time.perf_counter()
                try: result=original(msg)
                except Exception as exc:
                    book.finish(idx,b'',started,status='FAILED',error=type(exc).__name__+': '+str(exc))
                    raise
                book.finish(idx,(result or '').encode(),started,status='RETURNED' if result else 'FAILED')
                return result
        sock.send_msg=send;socket.setdefaulttimeout(25)
        try:yield bs,active
        finally:sock.send_msg=original;socket.setdefaulttimeout(old_timeout)
