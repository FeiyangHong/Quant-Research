"""Public exchange announcements with immutable, bounded collection.

Parsing produces evidence candidates, never a silently admitted trading ledger.
Dates in notices remain economic facts; availability is a separate model field.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import uuid

from .baostock import canonical, write_immutable
from ..data import date_only_available_at

HISTORY_END = '2024-12-31'
HOSTS = ('sse.com.cn', 'szse.cn', 'cninfo.com.cn', 'chinaclear.cn', 'csrc.gov.cn',
         'eastmoney.com', 'efunds.com.cn', 'southernfund.com', 'nffund.com',
         'huatai-pb.com', 'icbccs.com.cn', 'chinaamc.com')


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only anonymous HTTPS public-source URLs are supported')
    if not any(parsed.hostname == host or (parsed.hostname or '').endswith('.'+host) for host in HOSTS):
        raise ValueError('Unapproved source host')


def _http_worker(config):
    """Child process; parent enforces a wall-clock deadline, including reads."""
    validate_url(config['url'])
    headers = {'User-Agent':'Mozilla/5.0', **config.get('headers', {})}
    data = config.get('body')
    req = Request(config['url'], data=data.encode('utf-8') if data is not None else None,
                  headers=headers, method=config.get('method','GET'))
    with urlopen(req, timeout=min(config['timeout'],12)) as response:
        validate_url(response.url)
        body = response.read(config['max_bytes']+1)
        if len(body)>config['max_bytes']:
            raise ValueError('Response exceeded explicit byte limit')
        Path(config['output']).write_bytes(body)
        return dict(http_status=response.status,content_type=response.headers.get('Content-Type'),
                    final_url=response.url,bytes=len(body))


class OfficialArchive:
    def __init__(self, root, timeout=25, max_retries=1, min_interval=0.25, transport=None):
        if not 0<timeout<=60 or max_retries not in (0,1,2) or not 0<=min_interval<=10:
            raise ValueError('Invalid bounded request settings')
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.timeout,self.max_retries,self.min_interval=timeout,max_retries,min_interval
        self.transport=transport
        self._last=0.0
        self._cache={}
        for path in sorted((self.root/'captures').glob('*.json')):
            r=json.loads(path.read_text(encoding='utf-8'))
            if r['status']=='SUCCESS': self._cache[r['request_id']]=r

    def fetch(self,url,method='GET',body=None,headers=None,max_bytes=30_000_000):
        validate_url(url)
        request=dict(url=url,method=method,body=body,headers=headers or {},max_bytes=max_bytes)
        key=hashlib.sha256(canonical(request)).hexdigest()
        if key in self._cache:
            result=self._cache[key]
            data=(self.root/result['raw_path']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=result['sha256']:
                raise ValueError('Cached raw hash mismatch')
            return result
        for attempt in range(self.max_retries+1):
            time.sleep(max(0,self.min_interval-(time.monotonic()-self._last)))
            self._last=time.monotonic()
            started=datetime.now(timezone.utc).isoformat()
            token=uuid.uuid4().hex
            tmp=self.root/(token+'.partial')
            result=dict(request_id=key,request=request,requested_at=started,attempt=attempt+1,
                        source_class='CROSSCHECK_ONLY' if 'eastmoney.com' in urlparse(url).hostname else 'OFFICIAL')
            try:
                config=dict(request,timeout=self.timeout,output=str(tmp))
                if self.transport:
                    info,data=self.transport(config)
                    tmp.write_bytes(data)
                else:
                    options=dict(input=canonical(config),capture_output=True,timeout=self.timeout,check=False)
                    if sys.platform=='win32': options['creationflags']=subprocess.CREATE_NO_WINDOW
                    process=subprocess.run([sys.executable,'-m',__name__,'--http-worker'],**options)
                    if process.returncode:
                        raise RuntimeError(process.stderr.decode('utf-8',errors='replace')[-2000:])
                    info=json.loads(process.stdout)
                data=tmp.read_bytes()
                if len(data)>max_bytes: raise ValueError('Response exceeded explicit byte limit')
                sha=hashlib.sha256(data).hexdigest()
                raw=Path('raw')/(sha+'.bin')
                target=self.root/raw
                target.parent.mkdir(exist_ok=True)
                if not target.exists():
                    with target.open('xb') as stream:stream.write(data)
                elif target.read_bytes()!=data:raise ValueError('Raw hash collision')
                result.update(info,status='SUCCESS',raw_path=raw.as_posix(),sha256=sha,
                              fetched_at=datetime.now(timezone.utc).isoformat())
            except Exception as exc:
                result.update(status='ERROR',error_type=type(exc).__name__,error=str(exc),
                              fetched_at=datetime.now(timezone.utc).isoformat())
            finally:
                if tmp.exists():tmp.unlink()
            capture=Path('captures')/(key[:16]+'_'+token+'.json')
            result['capture_path']=capture.as_posix()
            write_immutable(self.root/capture,result)
            if result['status']=='SUCCESS':
                self._cache[key]=result
                return result
        return result

    def read(self,capture):
        if capture['status']!='SUCCESS':raise ValueError(capture.get('error','Failed request'))
        data=(self.root/capture['raw_path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=capture['sha256']:raise ValueError('Raw hash mismatch')
        return data


def query_announcements(archive,code,start,end,max_pages=100):
    if not re.fullmatch(r'(sh|sz)\.\d{6}',code):raise ValueError('Exchange-prefixed ETF code required')
    date.fromisoformat(start);date.fromisoformat(end)
    if start>end or end>'2025-04-30':raise ValueError('Announcement window is invalid')
    # 2025 metadata is solely for retrospective 2024 annual reports; not market data.
    symbol=code.split('.')[1]
    records,captures,seen=[],[],set()
    expected=None
    for page in range(1,max_pages+1):
        if code.startswith('sh.'):
            args={'isPagination':'true','pageHelp.pageSize':100,'pageHelp.pageNo':page,
                  'pageHelp.beginPage':page,'pageHelp.cacheSize':1,'pageHelp.endPage':page,
                  'type':'inParams','sqlId':'COMMON_PL_JJXX_JJGG_NEW_L','TITLE':'',
                  'SECURITY_CODE':symbol,'START_DATE':start,'END_DATE':end,'BULLETIN_TYPE':'','DATE_DESC':1}
            cap=archive.fetch('https://query.sse.com.cn/commonQuery.do?'+urlencode(args),
                              headers={'Referer':'https://www.sse.com.cn/'})
            captures.append(cap)
            data=json.loads(archive.read(cap))
            total=int(data['pageHelp']['total']);rawrows=data['result']
            rows=[dict(instrument_id=code,title=r['TITLE'],publication_date=r['SSEDATE'],
                       source_url='https://www.sse.com.cn'+r['URL'],source_record=r) for r in rawrows]
        else:
            args={'seDate':[start,end],'channelCode':['fundinfoNotice_disc'],'stock':[symbol],
                  'pageSize':50,'pageNum':page}
            cap=archive.fetch('https://www.szse.cn/api/disc/announcement/annList',method='POST',
                              body=json.dumps(args,separators=(',',':')),
                              headers={'Content-Type':'application/json','Referer':'https://www.szse.cn/'})
            captures.append(cap)
            data=json.loads(archive.read(cap))
            total=int(data['announceCount']);rawrows=data['data']
            rows=[dict(instrument_id=code,title=r['title'],publication_date=r['publishTime'][:10],
                       source_url='https://disc.static.szse.cn/download'+r['attachPath'],
                       source_record=r) for r in rawrows]
        if expected is None:expected=total
        elif expected!=total:raise ValueError('Announcement total changed during pagination')
        for r in rows:
            if not start<=r['publication_date']<=end:raise ValueError('Announcement outside requested dates')
            if code.startswith('sh.') and r['source_record']['SECURITY_CODE']!=symbol:
                raise ValueError('Mis-keyed SSE announcement')
            if code.startswith('sz.') and symbol not in r['source_record']['secCode']:
                raise ValueError('Mis-keyed SZSE announcement')
            key=(r['source_url'],r['publication_date'])
            if key in seen:raise ValueError('Repeated announcement page or duplicate record')
            seen.add(key);records.append(r)
        if len(records)==expected:
            return dict(instrument_id=code,start=start,end=end,reported_count=expected,
                        returned_count=len(records),pagination_complete=True,records=records,captures=captures)
        if not rows or len(records)>expected:raise ValueError('Incomplete or inconsistent announcement pagination')
    raise ValueError('Announcement page bound exhausted before completeness')


def query_announcement_titles(archive,exchange,term,start='2010-01-01',end=HISTORY_END,max_pages=50):
    """Bounded exchange-wide title discovery; does not equate search with proof of absence."""
    if exchange not in ('sh','sz') or not term or start>end or end>HISTORY_END:
        raise ValueError('Invalid historical global title query')
    records=[];captures=[];seen=set();expected=None
    for page in range(1,max_pages+1):
        if exchange=='sh':
            args={'isPagination':'true','pageHelp.pageSize':100,'pageHelp.pageNo':page,
                  'pageHelp.beginPage':page,'pageHelp.cacheSize':1,'pageHelp.endPage':page,
                  'type':'inParams','sqlId':'COMMON_PL_JJXX_JJGG_NEW_L','TITLE':term,
                  'SECURITY_CODE':'','START_DATE':start,'END_DATE':end,'BULLETIN_TYPE':'','DATE_DESC':1}
            cap=archive.fetch('https://query.sse.com.cn/commonQuery.do?'+urlencode(args),headers={'Referer':'https://www.sse.com.cn/'})
            payload=json.loads(archive.read(cap));total=int(payload['pageHelp']['total'])
            rows=[dict(title=r['TITLE'],publication_date=r['SSEDATE'],instrument_ids=['sh.'+r['SECURITY_CODE']],
                       source_url='https://www.sse.com.cn'+r['URL'],source_record=r) for r in payload['result']]
        else:
            args={'seDate':[start,end],'channelCode':['fundinfoNotice_disc'],'searchKey':[term],'pageSize':50,'pageNum':page}
            cap=archive.fetch('https://www.szse.cn/api/disc/announcement/annList',method='POST',
                              body=json.dumps(args,separators=(',',':')),headers={'Content-Type':'application/json','Referer':'https://www.szse.cn/'})
            payload=json.loads(archive.read(cap));total=int(payload['announceCount'])
            rows=[dict(title=r['title'],publication_date=r['publishTime'][:10],instrument_ids=['sz.'+c for c in r['secCode']],
                       source_url='https://disc.static.szse.cn/download'+r['attachPath'],source_record=r) for r in payload['data']]
        captures.append(cap)
        if expected is None:expected=total
        elif expected!=total:raise ValueError('Global announcement count changed during pagination')
        for row in rows:
            if not start<=row['publication_date']<=end or term not in row['title']:
                raise ValueError('Global title/date filter was ignored by provider')
            key=(row['source_url'],row['publication_date'],tuple(row['instrument_ids']))
            if key in seen:raise ValueError('Duplicate global announcement page')
            seen.add(key);records.append(row)
        if len(records)==expected:
            return dict(exchange=exchange,term=term,start=start,end=end,reported_count=total,returned_count=len(records),
                        pagination_complete=True,records=records,captures=captures,
                        limitation='Title keyword coverage only; cannot rule out differently titled index changes.')
        if not rows or len(records)>expected:raise ValueError('Inconsistent global pagination')
    raise ValueError('Global title query exceeded page bound')


def classify_document(record):
    title=unicodedata.normalize('NFKC',record['title'])
    title=re.sub(r'\s+','',title)
    title=title.translate(str.maketrans('〇零一二三四五六七八九','00123456789'))
    if '联接' in title:return None
    annual=re.search(r'(20\d{2})(?:年|年度)?年度报告',title)
    if annual and not any(x in title for x in ('提示','推迟','延期')):
        year=int(annual.group(1))
        if 2015<=year<=2024:return ('ANNUAL_REPORT_SUMMARY' if '摘要' in title else 'ANNUAL_REPORT',year)
    if record['publication_date']>HISTORY_END:return None
    if '转型' in title or re.search(r'(?:变更|更换).{0,20}(?:标的指数|跟踪指数|业绩比较基准)',title):return ('INDEX_CHANGE_NOTICE',None)
    if '招募说明书' in title and not any(x in title for x in ('提示','摘要','更正')):return ('PROSPECTUS',None)
    if any(x in title for x in ('分红公告','收益分配公告','利润分配公告')):return ('DIVIDEND_NOTICE',None)
    if any(x in title for x in ('折算','拆分','合并')):return ('SPLIT_NOTICE',None)
    if '上市交易公告书' in title and '提示' not in title:return ('LISTING_NOTICE',None)
    if any(x in title for x in ('终止上市','清算','停牌','复牌','持有人大会')):return ('LIFECYCLE_NOTICE',None)
    return None


def dividend_settlement_evidence(text):
    """Event-specific issuer terms, without asserting any personal receipt."""
    found=[]
    for page,body in enumerate(normalized_text(text).split('\f'),1):
        compact=re.sub(r'\s+','',body)
        for match in re.finditer(r'投资者可在现金红利发放日(?:领取|获得)现金红利',compact):
            found.append(dict(pdf_page=page,statement=compact[max(0,match.start()-100):match.end()+20],
                              account_type='DESIGNATED_BROKER_ORDINARY_ETF_HOLDER'))
    return found


def collect_document(archive,record):
    classification=classify_document(record)
    if classification is None:raise ValueError('Document is outside explicit event/report scope')
    kind,year=classification
    cap=next((c for c in archive._cache.values() if c['request']['url']==record['source_url'] and c['request']['method']=='GET'),None)
    if cap is None:cap=archive.fetch(record['source_url'])
    if cap['status']!='SUCCESS' and 'byte limit' in cap.get('error',''):
        cap=archive.fetch(record['source_url'],max_bytes=100_000_000)
    result=dict(record,document_kind=kind,report_year=year,capture=cap,status=cap['status'])
    if cap['status']!='SUCCESS':return result
    payload=archive.read(cap)
    if not payload.startswith(b'%PDF'):
        result.update(status='REJECTED_NOT_PDF');return result
    raw=archive.root/cap['raw_path']
    txt=Path('text')/(cap['sha256']+'.txt')
    target=archive.root/txt
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        try:
            run=subprocess.run(['pdftotext','-layout',str(raw),str(target)],capture_output=True,timeout=30,check=False)
            if run.returncode:raise ValueError(run.stderr.decode('utf-8',errors='replace')[-1000:])
        except Exception as exc:
            result.update(status='TEXT_EXTRACTION_FAILED',error=str(exc));return result
    content=target.read_bytes()
    result.update(pdf_sha256=cap['sha256'],pdf_path=cap['raw_path'],text_path=txt.as_posix(),
                  text_sha256=hashlib.sha256(content).hexdigest(),
                  evidence_role='RETROSPECTIVE_AUDIT_ONLY' if record['publication_date']>HISTORY_END else 'HISTORICAL_PUBLIC_NOTICE')
    return result


def normalized_text(text):
    return unicodedata.normalize('NFKC',text).replace('\u3000',' ')


def listing_evidence(document,text,sessions=()):
    from .universe import classify_name,documented_benchmarks
    text=normalized_text(text);compact=re.sub(r'\s+','',text)
    listed=label_date(text,r'(?:上市日期|上市交易日期|上市交易日|上市交易的时间)')
    first_page=re.sub(r'\s+','',text.split('\f')[0]).replace('上市交易公告书','')
    name_match=re.search(r'([\u4e00-\u9fffA-Za-z0-9]+?交易型开放式指数证券投资基金)',first_page)
    if name_match is None:name_match=re.search(r'(?:基金名称|基金全称)[:：]([\u4e00-\u9fffA-Za-z0-9]{4,120}?证券投资基金)',compact)
    legal_name=name_match.group(1) if name_match else None
    evidence=[]
    for page,body in enumerate(text.split('\f'),1):
        body=re.sub(r'\s+','',body)
        for m in re.finditer(r'(?:业绩比较基准|标的指数(?:[为:：]|简称|代码)|(?:三|四|五)\)标的指数).{0,180}',body):
            evidence.append(dict(pdf_page=page,statement=m.group(0)))
    title_index_basis=re.sub(r'上市交易公告书.*','',document['title'])
    disclosed=documented_benchmarks(' '.join(x['statement'] for x in evidence))
    name_classification=classify_name(legal_name or title_index_basis)
    benchmark=None;basis='UNRESOLVED'
    if len(disclosed)==1:
        benchmark=disclosed[0];basis='ORIGINAL_DOCUMENT_EXPLICIT_INDEX_STATEMENT'
    elif name_classification['classification_status']=='NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK':
        benchmark=name_classification['category'];basis='ORIGINAL_LEGAL_FUND_NAME_REQUIRES_EXACT_INDEX_CORROBORATION'
    published=document['publication_date']
    available=date_only_available_at(published,sessions) if sessions and published<max(sessions) else None
    return dict(instrument_id=document['instrument_id'],listed_on=listed,
                announcement_date=published,published_at=published,publication_precision='DATE_ONLY',
                available_at=available,source_url=document['source_url'],raw_object_hash=document['pdf_sha256'],
                source_sha256=document['pdf_sha256'],revision_id=document['pdf_sha256'],source_path=document['pdf_path'],
                text_path=document['text_path'],benchmark_statements=evidence,
                original_notice_title=title_index_basis,legal_fund_name=legal_name,
                benchmark_id=benchmark,benchmark_basis=basis,original_statement_index_ids=disclosed,
                benchmark_status='ORIGINAL_INDEX_STATEMENT' if basis=='ORIGINAL_DOCUMENT_EXPLICIT_INDEX_STATEMENT' else 'ORIGINAL_NAME_CANDIDATE',
                is_final_version='终稿' in document['title'],is_correction=any(x in document['title'] for x in ('更正','补充说明')),
                role='ORIGINAL_PUBLIC_PROSPECTUS' if document['document_kind']=='PROSPECTUS' else 'ORIGINAL_PUBLIC_LISTING_NOTICE')


def build_master_records(original_records,candidates,conversion_documents=(),sessions=()):
    """Build dated source metadata, preserving a documented historical index change."""
    result=[]
    for candidate in candidates:
        code=candidate['code'];records=[dict(r) for r in original_records if r['instrument_id']==code]
        listings=[r for r in records if r['role']=='ORIGINAL_PUBLIC_LISTING_NOTICE' and not r.get('is_correction')]
        for r in listings:
            if r['source_sha256']=='53b61c650c7b799e8bb07c2afb11b5b636efe20c4f83fb6b69b4eef642711973':
                r.update(listed_on='2013-04-11',legal_fund_name='南方开元沪深300交易型开放式指数证券投资基金',
                         benchmark_id='CSI300',manual_visual_source_pages=[1,3],
                         parse_basis='PDF_PAGE_VISUALLY_READ_HASH_BOUND')
        if not listings:raise ValueError('Missing original listing notice: '+code)
        listing=max(listings,key=lambda r:(r.get('is_final_version',False),r['announcement_date']))
        if not listing.get('listed_on'):raise ValueError('Unresolved original listing date: '+code)
        benchmark=listing.get('benchmark_id')
        if code=='sz.159908':
            if listing['source_sha256']!='75777d1377e0e3a97ebaee30ec10086f366241e59f8a356de24a5e10d66aafaf':
                raise ValueError('159908 original-index override requires the reviewed immutable source')
            benchmark='SZ_FUNDAMENTAL200'
        elif benchmark is None:
            ids={r['benchmark_id'] for r in records if r.get('benchmark_id')}
            if len(ids)!=1:raise ValueError('Unresolved original benchmark: '+code)
            benchmark=next(iter(ids))
        compatible=[r for r in records if benchmark in r.get('original_statement_index_ids',[]) and r.get('benchmark_id')==benchmark]
        index_source=min(compatible,key=lambda r:r['announcement_date']) if compatible else listing
        if benchmark!='SZ_FUNDAMENTAL200' and benchmark!=candidate['category']:
            raise ValueError('Original/current classification conflict requiring chronology: '+code)
        available=max(v for v in [listing['available_at'],index_source['available_at']] if v)
        revision=code+'_'+listing['source_sha256'][:24]
        result.append(dict(instrument_id=code,listed_on=listing['listed_on'],delisted_on=None,
            benchmark_id=benchmark,strategy_universe='OUTSIDE' if code=='sz.159908' else 'R1B',
            effective_from=listing['listed_on'],effective_to=None,available_at=available,
            published_at=max(listing['announcement_date'],index_source['announcement_date']),publication_precision='date_only',
            revision_id=revision,supersedes_id=None,source_url=listing['source_url'],raw_object_hash=listing['source_sha256'],
            source_path=listing['source_path'],legal_fund_name=listing.get('legal_fund_name'),
            benchmark_source_url=index_source['source_url'],benchmark_source_hash=index_source['source_sha256'],
            benchmark_source_path=index_source['source_path'],benchmark_source_available_at=index_source['available_at'],
            benchmark_basis='ORIGINAL_EXPLICIT_INDEX_STATEMENT' if compatible else 'ORIGINAL_LEGAL_FUND_NAME',
            original_prospectus_present=any(r['role']=='ORIGINAL_PUBLIC_PROSPECTUS' for r in records),
            source_hashes=sorted({listing['source_sha256'],index_source['source_sha256']}),
            account_verified=False,source_role='HISTORICAL_PUBLIC_NOTICE_NOT_ORIGINAL_DATA_VINTAGE'))
    conversions={d.get('pdf_sha256'):d for d in conversion_documents}
    known='f45e0013666c49bed93ad891e58f9fa59389faac65a60f1e8acc5c50b2a7ac10'
    if known in conversions and any(r['instrument_id']=='sz.159908' for r in result):
        old=next(r for r in result if r['instrument_id']=='sz.159908');d=conversions[known]
        changed=dict(old)
        changed.update(benchmark_id='CHINEXT',strategy_universe='R1B',effective_from='2018-12-10',
            available_at=date_only_available_at(d['publication_date'],sessions),published_at=d['publication_date'],
            revision_id='sz.159908_'+known[:24],supersedes_id=old['revision_id'],
            source_url=d['source_url'],raw_object_hash=known,source_path=d['pdf_path'],
            benchmark_source_url=d['source_url'],benchmark_source_hash=known,benchmark_source_path=d['pdf_path'],
            benchmark_source_available_at=date_only_available_at(d['publication_date'],sessions),
            benchmark_basis='OFFICIAL_EXPLICIT_INDEX_CONVERSION_NOTICE',source_hashes=[known],
            source_root='data/raw_r1_actions/index_changes',legal_fund_name='博时创业板交易型开放式指数证券投资基金',
            transition_period_end='2018-12-12',secondary_trading_suspended_for_conversion=False)
        result.append(changed)
    return sorted(result,key=lambda r:(r['instrument_id'],r['available_at'],r['effective_from']))


def delisting_revisions(master_records,documents,source_root,sessions):
    revisions=[];evidence=[]
    codes=sorted({d['instrument_id'] for d in documents})
    for code in codes:
        choices=[d for d in documents if d['instrument_id']==code and d.get('status')=='SUCCESS' and '提示' not in d['title']]
        if not choices:continue
        doc=min(choices,key=lambda d:d['publication_date'])
        body=normalized_text((Path(source_root)/doc['text_path']).read_text(encoding='utf-8'))
        day=label_date(body,r'终止上市日')
        if not day:raise ValueError('Unresolved official delisting date: '+code)
        old=max((r for r in master_records if r['instrument_id']==code),key=lambda r:r['available_at'])
        row=dict(old);row.update(delisted_on=day,available_at=date_only_available_at(doc['publication_date'],sessions),
            published_at=doc['publication_date'],revision_id=code+'_'+doc['pdf_sha256'][:24],supersedes_id=old['revision_id'],
            source_url=doc['source_url'],raw_object_hash=doc['pdf_sha256'],source_path=doc['pdf_path'],
            source_root=Path(source_root).as_posix(),source_hashes=sorted(set(old['source_hashes']+[doc['pdf_sha256']])),
            revision_reason='OFFICIAL_DELISTING_ANNOUNCEMENT')
        revisions.append(row)
        evidence.append(dict(instrument_id=code,delisted_on=day,announcement_date=doc['publication_date'],
            available_at=row['available_at'],last_trade_date=None,last_trade_date_status='NOT_INFERRED_FROM_MISSING_BARS_OR_SNAPSHOTS',
            source_url=doc['source_url'],source_sha256=doc['pdf_sha256'],source_path=doc['pdf_path'],
            source_root=Path(source_root).as_posix(),cash_settlement_status='NOT_RECONCILED_NONREPRESENTATIVE_DEPENDENCY_CHECK_REQUIRED'))
    return revisions,evidence


DATE_PATTERN=r'(?P<y>20\d{2})\s*(?:年|[-/.])\s*(?P<m>\d{1,2})\s*(?:月|[-/.])\s*(?P<d>\d{1,2})\s*日?'


def label_date(text,label):
    found=re.search(label+r'\s*(?:\((?!20\d{2})[^)]{0,45}\))?\s*[:：]?\s*\(?\s*'+DATE_PATTERN,text)
    if not found:return None
    return date(int(found['y']),int(found['m']),int(found['d'])).isoformat()


def parse_dividend(document,text,sessions=()):
    """Strict labeled-table extraction; unsupported layouts remain unresolved."""
    text=normalized_text(text)
    record=label_date(text,r'权益登记日')
    ex=label_date(text,r'除息日')
    pay=label_date(text,r'现金红利发放日')
    segment=re.search(r'本次分红方案(.{0,180}?)(?:有关年度|注[:：]|\n\s*注|2[.、])',text,re.S)
    amount=None
    if segment:
        chunk=re.sub(r'\s+','',segment.group(1))
        numbers=re.findall(r'(?<![\d.])(\d+\.\d+)(?![\d.])',segment.group(1))
        if len(numbers)==1 and re.search(r'元\s*[/／]\s*10(?:\s|份)',segment.group(1)):
            amount=str(Decimal(numbers[0])/Decimal(10))
    unresolved=[name for name,value in [('record_date',record),('ex_date',ex),('scheduled_pay_date',pay),('cash_per_share',amount)] if value is None]
    if not unresolved and not (record<ex<=pay):unresolved.append('date_order')
    if amount is not None and Decimal(amount)<=0:unresolved.append('nonpositive_cash')
    if ex is not None and ex>HISTORY_END:unresolved.append('outside_economic_window')
    published=document['publication_date']
    available=None
    if sessions and published<max(sessions):available=date_only_available_at(published,sessions)
    event=dict(action_id=document['instrument_id']+'_DIV_'+(ex or document['pdf_sha256'][:12]),
               instrument_id=document['instrument_id'],type='DIVIDEND',announcement_date=published,
               available_at=available,record_date=record,ex_date=ex,scheduled_pay_date=pay,
               actual_pay_date=None,cash_per_share=amount,source_url=document['source_url'],
               source_sha256=document['pdf_sha256'],source_text_sha256=document['text_sha256'],
               source_path=document['pdf_path'],publication_precision='DATE_ONLY',
               parse_status='PARSED_LABELED_TABLE' if not unresolved else 'NEEDS_REVIEW',
               unresolved=unresolved,settlement_basis='PUBLIC_NOTICE_SCHEDULE_NOT_PERSONAL_RECEIPT',
               settlement_notice_evidence=dividend_settlement_evidence(text),engine_ready=False)
    compact=re.sub(r'\s+','',text)
    post_split=re.search(r'本次分红方案对应的基金份额为.{0,35}拆分业务后的基金份额',compact)
    event['entitlement_unit_basis']='POST_SPLIT_REGISTERED_UNITS' if post_split else 'RECORD_DATE_REGISTERED_UNITS'
    if post_split:event['entitlement_basis_statement']=post_split.group(0)
    transfer=re.search(r'本次派发的现金红利将于.{0,30}自本基金托管账户划出.{0,100}',compact)
    event['cash_schedule_meaning']='CUSTODIAN_TRANSFER_DATE' if transfer else 'DECLARED_CASH_DIVIDEND_DATE'
    if transfer:event['cash_schedule_statement']=transfer.group(0)
    return event


def annual_evidence(document,text):
    """Return locatable statements; a missing marker never means no event."""
    normalized=normalized_text(text)
    pages=normalized.split('\f')
    split,distribution=[],[]
    for p,page in enumerate(pages,1):
        lines=page.splitlines()
        for i,line in enumerate(lines):
            if re.search(r'基金拆分变动份额|基金拆分/份额折算变动份额|基金份额折算变动份额',line):
                snippet='\n'.join(lines[i:i+5])
                # Separate table value must be a dash; negative numeric values are events.
                if re.search(r'(?m)^\s*[-—－]\s*$|份额[^\n]*?\s+[-—－](?:\s+[-—－])*\s*(?:\n|$)',snippet):
                    split.append(dict(pdf_page=p,status='EXPLICIT_NONE',snippet=snippet))
                else:split.append(dict(pdf_page=p,status='VALUE_REQUIRES_REVIEW',snippet=snippet))
            if re.search(r'本基金(?:过去三年|本报告期(?:内)?|报告期内).*?(?:未进行|未发生|未实施|没有).*?(?:利润|收益)分配',line):
                distribution.append(dict(pdf_page=p,statement=line.strip(),
                                         covered_years=list(range(document['report_year']-2,document['report_year']+1)) if '过去三年' in line else [document['report_year']]))
            elif re.search(r'本报告期内[,，]?\s*本基金未实施利润分配|本基金本报告期内无利润分配|本报告期本基金未有分配事项',line):
                distribution.append(dict(pdf_page=p,statement=line.strip(),covered_years=[document['report_year']]))
        none_section=re.search(r'过去三年基金的利润分配情况\s*\n\s*无[。.]',page)
        if none_section:
            distribution.append(dict(pdf_page=p,statement=none_section.group(0),covered_years=list(range(document['report_year']-2,document['report_year']+1))))
        since_inception=re.search(r'本基金自基金合同生效以来(?:无|未实施|未进行)利润分配(?:事项)?',page)
        if since_inception:
            distribution.append(dict(pdf_page=p,statement=since_inception.group(0),covered_years=list(range(2015,document['report_year']+1))))
        dated_none=re.search(r'本基金于(20\d{2}).{0,90}至(20\d{2}).{0,20}未进行利润分配',re.sub(r'\s+','',page))
        if dated_none:
            distribution.append(dict(pdf_page=p,statement=dated_none.group(0),covered_years=list(range(int(dated_none[1]),int(dated_none[2])+1))))
        reverse_none=re.search(r'过去三年本基金(?:未实施|未进行|没有)利润分配',page)
        if reverse_none:
            distribution.append(dict(pdf_page=p,statement=reverse_none.group(0),covered_years=list(range(document['report_year']-2,document['report_year']+1))))
    for match in re.finditer(r'基金合同生效日起至报告期期末基金\s+[-—](?=\s)[\s\S]{0,190}?拆分变动份额',normalized):
        split.append(dict(pdf_page=normalized[:match.start()].count('\f')+1,status='EXPLICIT_NONE',snippet=match.group(0),
                          layout_note='Wrapped label; explicit dash appears before final label line.'))
    listed=label_date(normalized,r'(?:上市日期|上市交易日期)')
    compact=re.sub(r'\s+','',normalized)
    benchmark=re.search(r'业绩比较基准(.{0,240}?)(?:风险收益特征|风险收益|2[.、]3基金管理)',compact)
    totals=[]
    for p,page in enumerate(pages,1):
        if '过去三年基金的利润分配情况' in page and not re.search(r'利润分配情况\s*\.{5,}',page):
            section=page.split('过去三年基金的利润分配情况',1)[1]
            if '每10份' in re.sub(r'\s+','',section):
                for row in re.finditer(r'(?m)^\s*(20\d{2})\s*年?\s+(\d+\.\d+|[-—])(?:\s|$)',section):
                    value='0' if row.group(2) in ('-','—') else str(Decimal(row.group(2))/Decimal(10))
                    totals.append(dict(year=int(row.group(1)),cash_per_share=value,pdf_page=p))
    return dict(instrument_id=document['instrument_id'],year=document['report_year'],
                report_source_url=document['source_url'],source_sha256=document['pdf_sha256'],
                report_publication_date=document['publication_date'],role='RETROSPECTIVE_COMPLETENESS_AUDIT',
                splits_status='EXPLICIT_NONE' if split and all(s['status']=='EXPLICIT_NONE' for s in split) else 'NEEDS_REVIEW',
                split_evidence=split,dividend_none_evidence=distribution,dividend_totals=totals,
                listed_on_evidence=listed,benchmark_text=benchmark.group(1) if benchmark else None)


def reviewed_share_actions(documents,sessions=()):
    """Human-read source facts keyed to immutable PDF bytes, not guessed layouts.

    These remain staging records: their phase and knowledge fields must be honored
    by any consumer. In particular the 2015 ratio was not known on its ex-date.
    """
    specifications=[
        ('sh.510500','2015-04-14','2015-04-13','0.28032483','FLOOR','SUSPENDED_SESSION',
         '4a9b57d816bf76901bdf683c8fef41cbad22e953264b85c7440274fc343a119d',
         '06310b956450a62386b0ecf4b69eba21777ccf37eae8f3a98d0e3a9a53f2f2b5',True),
        ('sh.510500','2022-08-26','2022-08-26','1.14539','CEIL','END_OF_DAY',
         '2c933c4c0fddf34b5e90ab711990d34be0644d66275a7d8ea9a40467ebdb586c',
         '28a13a3885ce2da1769f45cc7da8a361243e18b4022020780106b9200d8cad19',False),
        ('sh.512100','2022-09-02','2022-09-01','0.36555','CEIL','SUSPENDED_SESSION',
         '8b5ec083d20fbb50899472ea86d2839c5fc75d764d2b5d42484566be940444eb',
         '372ef67c3976934266b5c390bb3e068895541f9d3c825318213fbdcd787c9316',False),
        ('sh.588000','2020-11-09',None,'0.69448528','FLOOR','PRE_LISTING',
         'be3a5ff996c4470af2c2c8e3de371ee538ea9bfe440e185b62d2cd4dc5fca34e',
         'be3a5ff996c4470af2c2c8e3de371ee538ea9bfe440e185b62d2cd4dc5fca34e',True),
        ('sz.159814','2021-02-09','2021-02-09','2.059034965','FLOOR','END_OF_DAY',
         '3b91118504ae890a0d65d78c0391cb86c151b49a48745dc197bbdddfd5ac5f7f',
         '7ca58e6f21a11e2c30d5d7a676bbf7605462f3d1a5970a86b30fdfdf20086862',False),
        ('sz.159845','2021-03-22','2021-03-22','1.573946543','FLOOR','PRE_LISTING',
         '84ee660fddb91030b584b45148aa41a29a756d5a365f605e5a8d6e6461b097fc',
         '9419e011ecdb01b57e96ec1f76f097661bb657eaf967cf3519a10026dc1fada8',True),
        ('sz.159845','2022-08-01','2022-08-01','0.352275906','FLOOR','END_OF_DAY',
         '5170578426bad56c2ef3a699da4f66bc1bbf468e7b1ab423f50382b04e193111',
         'a5aaa39bc273d9cba64fc27ec9f98f197c31a01ea443a336a5c422e91ffe5ca7',False),
        ('sz.159845','2023-02-28','2023-02-28','0.747644145','FLOOR','END_OF_DAY',
         '0c56bba4ac727b4c5ed975b1c90965ee979f68ed85bc5766259d77892c94c924',
         'abb952d42c622772a1e946085e2842faa8a3b3016f721a09c66a4e20171bc80f',False),
        ('sz.159991','2021-01-26','2021-01-26','2.839985106','FLOOR','END_OF_DAY',
         '4518da8aca54ca91eedf4395492f2df6092caae7c1d784b28fe0376d97ffe8f3',
         '04c65012b421a2770f96f4e482841975565ec0885dc7fe1acbb78c37018a3fcb',False),
        ('sz.159922','2022-02-17','2022-02-17','1.117385865','FLOOR','END_OF_DAY',
         '27df8c08d41ceea63110e3e180954d545625488a0eadec224534815afe378df6',
         'f00b96e1e08aadbe15913065c6e6cdd070305a2838c0761ffb8bb4adf6f69485',False),
        ('sz.159922','2024-11-29','2024-11-29','2.5','CEIL','END_OF_DAY',
         '7e986b6ba89f02b984f3bdbdc4a3b934294a447c480042172e4f78c864fdd35a',
         '5351fae40d198592fec9d979e6fdf0ce8793332b0772b6fa65696297cc9bd6bf',False),
    ]
    docs={d.get('pdf_sha256'):d for d in documents if d.get('status')=='SUCCESS'}
    def availability(doc):
        return date_only_available_at(doc['publication_date'],sessions) if sessions and doc['publication_date']<max(sessions) else None
    out=[]
    for code,day,record,ratio,rounding,phase,schedule_hash,result_hash,late in specifications:
        if schedule_hash not in docs or result_hash not in docs:continue
        schedule,result=docs[schedule_hash],docs[result_hash]
        terms=result if late else schedule
        out.append(dict(action_id=code+'_SPLIT_'+day,instrument_id=code,type='SPLIT',
                        announcement_date=schedule['publication_date'],available_at=availability(terms),
                        schedule_available_at=availability(schedule),ratio_available_at=availability(terms),
                        ex_date=day,effective_date=day,registration_date=day,record_date=record,split_ratio=ratio,effective_phase=phase,
                        fractional_share_rounding=rounding,rounding_basis='PER_HOLDER_REGISTERED_BALANCE',
                        status='EXECUTED_CONFIRMED',source_sha256=terms['pdf_sha256'],
                        source_url=terms['source_url'],source_path=terms['pdf_path'],
                        source_text_sha256=terms['text_sha256'],schedule_source_sha256=schedule_hash,
                        confirmation_source_sha256=result_hash,source_hashes=list(dict.fromkeys([schedule_hash,result_hash])),
                        exact_ratio_published_after_effective_date=late,engine_ready=False,
                        knowledge_policy='DO_NOT_BACKFILL_EARLIER_NAV_OR_SIGNALS',
                        source_effective_date=day,parse_status='HUMAN_RECONCILED_HASH_BOUND'))
    for e in out:
        if e['instrument_id']=='sh.510500' and e['ex_date']=='2015-04-14':
            e.update(formula='(X / Y) / (I / 1000), rounded HALF_UP to 8 decimals',
                     formula_inputs='2015-04-13 fund total NAV X, units Y, CSI500 close I; prior public availability of all inputs not verified',
                     suspension_start='2015-04-13',suspension_end='2015-04-14',resume_date='2015-04-15',
                     fractional_remainder_treatment='REMAINDER_TO_FUND_ASSETS')
        elif e['instrument_id']=='sh.512100':
            e.update(suspension_start='2022-09-02',suspension_end='2022-09-02',resume_date='2022-09-05',
                     fractional_remainder_treatment='MANAGER_FUNDS_CEILING_DIFFERENCE')
        elif e['instrument_id']=='sh.510500' and e['effective_phase']=='END_OF_DAY':
            e.update(first_adjusted_quote_session='2022-08-29',
                     fractional_remainder_treatment='MANAGER_FUNDS_CEILING_DIFFERENCE',
                     note='Notice pauses agreed-repurchase business only; no ETF trading suspension. Aug26 close is old-unit quote.')
        if e['instrument_id'].startswith('sz.') and e['effective_phase']=='END_OF_DAY':
            official_ex={('sz.159814','2021-02-09'):'2021-02-10',('sz.159845','2022-08-01'):'2022-08-02',
                         ('sz.159845','2023-02-28'):'2023-03-01',('sz.159991','2021-01-26'):'2021-01-27',
                         ('sz.159922','2022-02-17'):'2022-02-18',('sz.159922','2024-11-29'):'2024-12-02'}[(e['instrument_id'],e['effective_date'])]
            e.update(ex_date=official_ex,official_ex_date=official_ex,first_adjusted_quote_session=official_ex,
                     fractional_remainder_treatment='REMAINDER_TO_FUND_ASSETS' if e['fractional_share_rounding']=='FLOOR' else 'MANAGER_FUNDS_CEILING_DIFFERENCE',
                     note='Source separately specifies EOD registration and the following market ex-date. Preserve both.')
    return out


def reconcile_coverage(events,annuals,documents,sessions=()):
    """Reconcile positive dividends and explicit annual zeroes without silence-as-zero."""
    shares=reviewed_share_actions(documents,sessions)
    grouped={}
    for event in events:
        if event['type']=='DIVIDEND':grouped.setdefault(event['action_id'],[]).append(event)
    canonical=[]
    for key,rows in sorted(grouped.items()):
        signatures={(r.get('record_date'),r.get('ex_date'),r.get('scheduled_pay_date'),r.get('cash_per_share')) for r in rows}
        if len(signatures)==1 and all(r['parse_status']=='PARSED_LABELED_TABLE' for r in rows):
            row=dict(min(rows,key=lambda r:r['announcement_date']))
            row['source_hashes']=sorted({r['source_sha256'] for r in rows})
            row['revision_id']=row['source_sha256'];canonical.append(row)
    canonical+=shares
    coverage=[]
    codes=sorted({d['instrument_id'] for d in documents})
    for code in codes:
        reports=[a for a in annuals if a['instrument_id']==code]
        listings=[a['listed_on_evidence'] for a in reports if a.get('listed_on_evidence')]
        listing=min(listings) if listings else None
        for year in range(2015,2025):
            if listing and year<int(listing[:4]):continue
            direct=[a for a in reports if a['year']==year]
            totals=set();proof=[]
            for a in reports:
                for value in a['dividend_totals']:
                    if value['year']==year:totals.add(Decimal(value['cash_per_share']));proof.append(a['source_sha256'])
                if any(year in statement['covered_years'] for statement in a['dividend_none_evidence']):
                    totals.add(Decimal(0));proof.append(a['source_sha256'])
            dividends=[e for e in canonical if e['type']=='DIVIDEND' and e['instrument_id']==code and int(e['ex_date'][:4])==year]
            notice_total=sum((Decimal(e['cash_per_share']) for e in dividends),Decimal(0))
            unresolved=[]
            if not totals:div_status='MISSING_ANNUAL_RECONCILIATION';unresolved.append('dividend_annual_evidence')
            elif len(totals)>1:div_status='CONFLICTING_ANNUAL_EVIDENCE';unresolved.append('dividend_annual_conflict')
            elif next(iter(totals))!=notice_total:div_status='NOTICE_ANNUAL_MISMATCH';unresolved.append('missing_or_conflicting_dividend_notice')
            else:div_status='RECONCILED_POSITIVE' if notice_total else 'EXPLICIT_ZERO_RECONCILED'
            actual=[s for s in shares if s['instrument_id']==code and int(s['ex_date'][:4])==year]
            if actual:split_status='EXECUTED_CHANGE_DOCUMENTED'
            elif direct and all(a['splits_status']=='EXPLICIT_NONE' for a in direct):split_status='EXPLICIT_NONE'
            else:split_status='MISSING_OR_UNPARSED';unresolved.append('share_change_annual_evidence')
            coverage.append(dict(instrument_id=code,year=year,dividend_status=div_status,
                notice_total_per_share=str(notice_total),annual_total_per_share=str(next(iter(totals))) if len(totals)==1 else None,
                dividend_source_hashes=[h for e in dividends for h in e['source_hashes']],
                dividend_annual_source_hashes=sorted(set(proof)),split_status=split_status,
                split_source_hashes=sorted({h for e in actual for h in e['source_hashes']}),
                report_hashes=sorted({a['source_sha256'] for a in direct}),unresolved=unresolved,
                status='COMPLETE' if not unresolved else 'INCOMPLETE',
                role='RETROSPECTIVE_COMPLETENESS_AUDIT_NOT_SIGNAL_INPUT'))
    return canonical,coverage


def parse_split_notice(document,text,sessions=()):
    """Keep proposals, cancellations and confirmations as separate source revisions."""
    text=normalized_text(text)
    compact=re.sub(r'\s+','',text)
    cancelled='取消' in document['title']
    day=label_date(text,r'份额(?:拆分|合并|折算)日')
    record=label_date(text,r'权益登记日')
    if day is None:
        reverse=re.search(DATE_PATTERN+r'\s*(?:为(?:基金)?份额(?:折算|拆分|合并)日|\(份额折算日)',text)
        if reverse:day=date(int(reverse['y']),int(reverse['m']),int(reverse['d'])).isoformat()
    ratios=re.findall(r'(?:份额)?(?:折算|拆分|合并)比例为([0-9]+\.[0-9]+)',compact)
    ratios=sorted(set(ratios))
    ratio=ratios[0] if len(ratios)==1 else None
    phase='END_OF_DAY' if '拆分日日终' in compact or '份额拆分日(' in compact and '日终' in compact else 'UNRESOLVED'
    if record is None and '拆分对象:份额拆分日登记在册' in compact:
        record=day
    if '上进位' in compact or '均进位为1份' in compact:rounding='CEIL'
    elif '小数部分舍去' in compact or '截位法保留至整数位' in compact:rounding='FLOOR'
    else:rounding=None
    status='CANCELLED' if cancelled else 'RESULT_CONFIRMED' if '结果' in document['title'] else 'ANNOUNCED'
    available=date_only_available_at(document['publication_date'],sessions) if sessions and document['publication_date']<max(sessions) else None
    return dict(action_id=document['instrument_id']+'_SHARE_CHANGE_'+(day or document['pdf_sha256'][:12]),
                revision_id=document['pdf_sha256'],instrument_id=document['instrument_id'],type='SPLIT',
                announcement_date=document['publication_date'],available_at=available,
                source_effective_date=day,ex_date=day,record_date=record,split_ratio=ratio,
                status=status,effective_phase=phase,fractional_share_rounding=rounding,
                source_url=document['source_url'],source_sha256=document['pdf_sha256'],
                source_text_sha256=document['text_sha256'],source_path=document['pdf_path'],
                parse_status='SOURCE_REVISION_REQUIRES_RECONCILIATION',engine_ready=False,
                apply_to_ledger=False if cancelled else None,
                note='Announcements and reminders are not additional share transformations. Cancelled events must never be applied. Source day is not shifted to fit engine ordering.')


if __name__=='__main__' and '--http-worker' in sys.argv:
    try:
        print(json.dumps(_http_worker(json.loads(sys.stdin.buffer.read())),ensure_ascii=False))
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)
