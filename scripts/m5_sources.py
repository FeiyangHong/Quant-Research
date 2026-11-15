"""M5 shared collector. Every caller must register its fixed requests first."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import time
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.budget import BudgetLedger, atomic_json, exclusive_lock

OUT = ROOT / 'data/raw_m5_equity'
LIMITS = dict(http_attempts=160, baostock_wire_attempts=20, new_body_bytes=120*1024*1024)
SCOPES = {
    'financial':dict(http_attempts=70, baostock_wire_attempts=0, new_body_bytes=40*1024*1024),
    'execution':dict(http_attempts=30, baostock_wire_attempts=8, new_body_bytes=20*1024*1024),
    'market_cap':dict(http_attempts=60, baostock_wire_attempts=12, new_body_bytes=60*1024*1024),
}
OFFICIAL = {'www.cninfo.com.cn','static.cninfo.com.cn','www.csrc.gov.cn','www.sse.com.cn',
            'www.szse.cn','investor.szse.cn','disc.static.szse.cn','www.chinaclear.cn',
            'www.chinatax.gov.cn','www.gov.cn','fgk.chinatax.gov.cn'}


def ledger():
    if not (ROOT/'docs/M5_PLAN.md').exists():
        raise RuntimeError('M5 plan must be registered before collection')
    return BudgetLedger(OUT, LIMITS, scope_limits=SCOPES)


def validate_dates(dates):
    bounds=dates.split('~')
    if len(bounds)!=2 or not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in bounds) or not ('1990-01-01'<=bounds[0]<=bounds[1]<='2024-12-31'):
        raise ValueError('Explicit bounded pre-2025 documentary/market dates required')
    return bounds


def validate_url(url, *, dates, route='official_documents', body=None):
    bounds=validate_dates(dates)
    parsed=urlparse(url)
    hosts=OFFICIAL if route=='official_documents' else {'datacenter-web.eastmoney.com'} if route=='historical_shares' else {'cn.bing.com','www.bing.com','www.google.com','www.google.com.hk','www.baidu.com'} if route=='historical_rule_discovery' else set()
    if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError('Registered HTTPS source host required')
    decoded=unquote(url + ' ' + (body or ''))
    if any(d>'2024-12-31' for d in re.findall(r'20\d{2}-\d{2}-\d{2}',decoded)):
        raise ValueError('Post-2024 source request rejected')
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
    if route=='historical_rule_discovery':
        query=parse_qs(parsed.query)
        key='wd' if parsed.hostname=='www.baidu.com' else 'q'
        search_path='/s' if parsed.hostname=='www.baidu.com' else '/search'
        if parsed.path!=search_path or not query.get(key) or body is not None:
            raise ValueError('Only bounded historical rule search queries allowed')
        if not any(word in query[key][0].lower() for word in ('交易规则','过户费','印花税','chinaclear','交易费用')):
            raise ValueError('Historical-rule discovery only')


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused; validate and register destination separately: ' + newurl)


def fetch(label, url, body=None, *, dates, scope, route='official_documents'):
    validate_url(url,dates=dates,route=route,body=body)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):
        raise ValueError('Safe manifest label required')
    with exclusive_lock(OUT/'network.lock'):
        book=ledger()
        idx=book.begin('http_attempts',label,scope=scope,url=url,request_body=body,dates=dates,route=route,method='POST' if body is not None else 'GET')
        started=time.perf_counter();payload=b''
        try:
            request=Request(url,data=body.encode() if body is not None else None,
                            headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/',
                                     'Content-Type':'application/x-www-form-urlencoded'})
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


def query_cninfo(label, code, key, dates, *, scope, org_id=None, page=1):
    validate_dates(dates)
    verified={}
    paths=list((ROOT/'data/raw_equity_admission/http').glob('cninfo_revision_candidates*.bin'))+list((ROOT/'data/raw_m4_equity/objects').glob('*.bin'))+list((OUT/'objects').glob('*.bin'))
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
