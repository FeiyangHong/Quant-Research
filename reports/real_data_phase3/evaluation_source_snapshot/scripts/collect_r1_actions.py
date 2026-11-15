"""Collect public official action evidence; does not run or admit a backtest."""
from __future__ import annotations
import argparse
import concurrent.futures
from datetime import date,datetime, timedelta,timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.official import (OfficialArchive,query_announcements,
    classify_document,collect_document,parse_dividend,annual_evidence,parse_split_notice,reconcile_coverage,listing_evidence,
    query_announcement_titles,build_master_records,delisting_revisions)
from quant_research.providers.baostock import write_immutable


def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temp.replace(path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='data/raw_r1_actions/r1_2015_2024')
    p.add_argument('--report',default='reports/real_data_phase3/event_manifest.json')
    p.add_argument('--candidates')
    p.add_argument('--codes',nargs='*')
    p.add_argument('--calendar',help='Raw BaoStock calendar response, fields+rows')
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--index-only',action='store_true')
    p.add_argument('--metadata-only',action='store_true',help='Collect2024annual reports for candidate identity audit; no historical eligibility inference')
    p.add_argument('--listing-only',action='store_true',help='Collect original listing notices around documented/current-master discovery dates')
    p.add_argument('--original-index-documents',action='store_true',help='With listing-only, search180days beforelisting and collect one original prospectus')
    p.add_argument('--conversion-documents',help='Previously archived, hash-bound conversion document records for datedmaster')
    p.add_argument('--delisting-documents',help='Previously archived delisting document records for datedmaster')
    p.add_argument('--global-index-changes',action='store_true',help='Bounded2010–2024SSE/SZSE titleaudit forindex/conversion keywords')
    p.add_argument('--identify-dead',action='store_true',help='Discover historical names from bounded official title queries and latest historical annual report')
    args=p.parse_args(argv)
    if not 1<=args.workers<=6:raise ValueError('workers must be1..6')
    out=ROOT/args.output
    out.mkdir(parents=True,exist_ok=True)
    if args.global_index_changes:
        archive=OfficialArchive(out);batches=[]
        for exchange in ('sh','sz'):
            for term in ('标的指数','转型','业绩比较基准'):
                batch=query_announcement_titles(archive,exchange,term)
                write_immutable(out/(exchange+'_'+term+'_2010_2024_query.json'),batch)
                batches.append(batch)
        save_json(ROOT/args.report,dict(status='BOUNDED_TITLE_AUDIT_NOT_EXHAUSTIVE_UNIVERSE_PROOF',queries=batches))
        print(json.dumps({'queries':len(batches),'records':sum(b['returned_count'] for b in batches)}))
        return
    candidates=json.loads((ROOT/args.candidates).read_text(encoding='utf-8')) if args.candidates else []
    if isinstance(candidates,dict):candidates=candidates.get('candidates',[])
    if args.identify_dead:candidates=[c for c in candidates if not c.get('names')]
    if args.codes:candidates=[dict(code=c) for c in args.codes]
    if not candidates:candidates=[dict(code=c) for c in ['sh.510300','sh.510330','sh.510500','sh.512100','sz.159915','sh.588000','sh.512320']]
    if not args.listing_only and not any(c['code']=='sh.512320' for c in candidates):candidates.append(dict(code='sh.512320',classification_status='LIFECYCLE_CASE_OUTSIDE_R1B'))
    sessions=[];calendar_info=None
    if args.calendar:
        path=ROOT/args.calendar;raw=path.read_bytes();cal=json.loads(raw)
        if set(cal.get('fields',[]))!={'calendar_date','is_trading_day'}:raise ValueError('Calendar fields invalid')
        rows=[dict(zip(cal['fields'],r)) for r in cal['rows']]
        sessions=sorted(r['calendar_date'] for r in rows if r['is_trading_day']=='1')
        calendar_info=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),first=sessions[0],last=sessions[-1])
    windows=[('2015-01-01','2017-12-31'),('2018-01-01','2020-12-31'),('2021-01-01','2023-12-31'),('2024-01-01','2024-12-31'),('2025-01-01','2025-04-30')]
    if args.metadata_only:windows=[('2025-01-01','2025-04-30')]
    def one_candidate(candidate):
        code=candidate['code'];archive=OfficialArchive(out)
        batches,docs,events,coverage,errors=[],[],[],[],[]
        records={}
        use_windows=windows
        if args.listing_only:
            discovered=candidate.get('documented_listing_dates') or [candidate.get('listing_date_from_current_master')]
            discovered=[d for d in discovered if d]
            if discovered:
                listed=date.fromisoformat(min(discovered))
                use_windows=[((listed-timedelta(days=180 if args.original_index_documents else 45)).isoformat(),(listed+timedelta(days=5)).isoformat())]
            else:
                errors.append(dict(instrument_id=code,phase='LISTING_DISCOVERY',error='No listing discovery date'))
                use_windows=[]
        if args.identify_dead:
            lastyear=int(candidate.get('last_snapshot_seen','2024-12-31')[:4])
            use_windows=[(str(max(2010,lastyear-1))+'-01-01',str(min(2024,lastyear+1))+'-12-31')]
        identity=None
        for start,end in use_windows:
            try:
                batch=query_announcements(archive,code,start,end)
                query_path=Path('queries')/(code+'_'+start+'_'+end+'.json')
                write_immutable(out/query_path,batch)
                batches.append(dict(instrument_id=code,start=start,end=end,reported_count=batch['reported_count'],
                                    returned_count=batch['returned_count'],pagination_complete=True,
                                    path=query_path.as_posix(),sha256=hashlib.sha256((out/query_path).read_bytes()).hexdigest()))
                for r in batch['records']:
                    kind=classify_document(r)
                    if kind and (kind[0]!='PROSPECTUS' or args.original_index_documents):records[(r['source_url'],r['publication_date'])]=r
                if args.identify_dead:
                    choices=[r for r in batch['records'] if re.search(r'20\d{2}年?年度报告|清算报告|上市交易公告书|招募说明书',r['title']) and '联接' not in r['title'] and '提示' not in r['title']]
                    if choices:
                        choice=max(choices,key=lambda r:(bool(re.search(r'年度报告',r['title'])),r['publication_date']))
                        name=re.sub(r'20\d{2}年?.*|上市交易公告书.*|清算报告.*|(?:更新的)?招募说明书.*','',choice['title']).strip()
                        identity=dict(code=code,name=name,benchmark=None,source_url=choice['source_url'],
                                      publication_date=choice['publication_date'],query_sha256=batches[-1]['sha256'],
                                      basis='OFFICIAL_HISTORICAL_ANNOUNCEMENT_TITLE',historical_window=[start,end])
            except Exception as exc:
                errors.append(dict(instrument_id=code,phase='QUERY',start=start,end=end,error=str(exc)))
        # Full annual report takes precedence; older summaries may contain sufficient evidence.
        full_years={classify_document(r)[1] for r in records.values() if classify_document(r)[0]=='ANNUAL_REPORT'}
        records={k:r for k,r in records.items() if not (classify_document(r)[0]=='ANNUAL_REPORT_SUMMARY' and classify_document(r)[1] in full_years)}
        if args.identify_dead:
            annuals=[r for r in records.values() if classify_document(r)[0].startswith('ANNUAL_REPORT')]
            records={('identity',code):max(annuals,key=lambda r:r['publication_date'])} if annuals else {}
        if args.listing_only:
            originals=[r for r in records.values() if classify_document(r)[0]=='PROSPECTUS']
            records={k:r for k,r in records.items() if classify_document(r)[0]=='LISTING_NOTICE'}
            if originals:
                original=min(originals,key=lambda r:('更新' in r['title'],r['publication_date']))
                records[(original['source_url'],original['publication_date'])]=original
        for record in sorted(records.values(),key=lambda r:(r['publication_date'],r['source_url'])):
            if args.index_only:
                docs.append(dict(record,document_kind=classify_document(record)[0],status='INDEXED_NOT_DOWNLOADED'))
                continue
            try:
                doc=collect_document(archive,record)
                docs.append(doc)
                if doc['status']!='SUCCESS':continue
                text=(out/doc['text_path']).read_text(encoding='utf-8')
                if doc['document_kind']=='DIVIDEND_NOTICE':events.append(parse_dividend(doc,text,sessions))
                elif doc['document_kind']=='SPLIT_NOTICE':
                    events.append(parse_split_notice(doc,text,sessions))
                    if '本次分红方案' in text:events.append(parse_dividend(doc,text,sessions))
                elif doc['document_kind'].startswith('ANNUAL_REPORT'):coverage.append(annual_evidence(doc,text))
            except Exception as exc:
                errors.append(dict(instrument_id=code,phase='DOCUMENT',source_url=record['source_url'],error=str(exc)))
        # Earlier original listing notice is necessary before the first research date.
        listing_dates=sorted({c['listed_on_evidence'] for c in coverage if c['listed_on_evidence']})
        if not args.metadata_only and not args.identify_dead and listing_dates and not any(d['document_kind']=='LISTING_NOTICE' for d in docs):
            listed=date.fromisoformat(listing_dates[0])
            try:
                batch=query_announcements(archive,code,(listed-timedelta(days=45)).isoformat(),(listed+timedelta(days=5)).isoformat())
                path=Path('queries')/(code+'_original_listing.json');write_immutable(out/path,batch)
                batches.append(dict(instrument_id=code,purpose='ORIGINAL_LISTING_DISCOVERY',path=path.as_posix(),
                                    sha256=hashlib.sha256((out/path).read_bytes()).hexdigest(),pagination_complete=True,
                                    start=batch['start'],end=batch['end'],reported_count=batch['reported_count'],returned_count=batch['returned_count']))
                for r in batch['records']:
                    if classify_document(r) and classify_document(r)[0]=='LISTING_NOTICE':docs.append(collect_document(archive,r))
            except Exception as exc:errors.append(dict(instrument_id=code,phase='ORIGINAL_LISTING',error=str(exc)))
        if identity and coverage:
            identity.update(benchmark=coverage[-1]['benchmark_text'],annual_source_sha256=coverage[-1]['source_sha256'],
                            annual_source_url=coverage[-1]['report_source_url'],listed_on_evidence=coverage[-1]['listed_on_evidence'])
        result=dict(candidate=candidate,query_batches=batches,documents=docs,events=events,annual_evidence=coverage,errors=errors,identity_evidence=identity)
        save_json(out/'by_instrument'/(code+'.json'),result)
        print(json.dumps({'code':code,'batches':len(batches),'documents':len(docs),'dividend_candidates':len(events),
                          'parsed_dividends':sum(e['type']=='DIVIDEND' and e['parse_status']=='PARSED_LABELED_TABLE' for e in events),
                          'annual_reports':len(coverage),'errors':len(errors)},ensure_ascii=False),flush=True)
        return result
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(one_candidate,c):c['code'] for c in candidates}
        for future in concurrent.futures.as_completed(futures):
            try:results.append(future.result())
            except Exception as exc:results.append(dict(candidate={'code':futures[future]},query_batches=[],documents=[],events=[],annual_evidence=[],errors=[{'error':str(exc)}]))
    events=[e for r in results for e in r['events']]
    if args.identify_dead:save_json(out/'dead_name_evidence.json',[r['identity_evidence'] for r in results if r.get('identity_evidence')])
    result=dict(schema_version='official-actions-1.0',generated_at=datetime.now(timezone.utc).isoformat(),
                status='OFFICIAL_EVIDENCE_STAGING_NOT_DATASET_GATE',requested_window=['2015-01-01','2024-12-31'],
                retrospective_report_discovery_window=['2025-01-01','2025-04-30'],
                calendar=calendar_info,source_root=out.relative_to(ROOT).as_posix(),candidates=candidates,
                query_batches=[b for r in results for b in r['query_batches']],
                documents=[d for r in results for d in r['documents']],events=events,
                annual_evidence=[c for r in results for c in r['annual_evidence']],
                errors=[e for r in results for e in r['errors']],
                policy={'economic_dates_never_shifted':True,'date_only_availability':'NEXT_TRADING_SESSION_2100_ASIA_SHANGHAI',
                        'actual_cash_receipt_observed':False,'2025_annuals':'RETROSPECTIVE_AUDIT_ONLY',
                        'unparsed_or_missing_evidence_never_means_zero':True})
    result['canonical_actions'],result['coverage']=reconcile_coverage(result['events'],result['annual_evidence'],result['documents'],sessions)
    result['instrument_records']=[listing_evidence(d,(out/d['text_path']).read_text(encoding='utf-8'),sessions)
                                  for d in result['documents'] if d.get('status')=='SUCCESS' and d['document_kind']=='LISTING_NOTICE']
    result['index_records']=[listing_evidence(d,(out/d['text_path']).read_text(encoding='utf-8'),sessions)
                            for d in result['documents'] if d.get('status')=='SUCCESS' and d['document_kind']=='PROSPECTUS']
    if args.listing_only and sessions:
        conversions=json.loads((ROOT/args.conversion_documents).read_text(encoding='utf-8')) if args.conversion_documents else []
        master=build_master_records(result['instrument_records']+result['index_records'],candidates,conversions,sessions)
        for row in master:row.setdefault('source_root',out.relative_to(ROOT).as_posix())
        if args.delisting_documents:
            path=ROOT/args.delisting_documents
            revisions,evidence=delisting_revisions(master,json.loads(path.read_text(encoding='utf-8')),path.parent,sessions)
            master+=revisions;result['delisting_evidence']=evidence
        save_json(out/'master_records.json',sorted(master,key=lambda r:(r['instrument_id'],r['available_at'])))
        result['master_records_path']=(out/'master_records.json').relative_to(ROOT).as_posix()
    save_json(ROOT/args.report,result)
    save_json(out/'collection.json',result)
    print(json.dumps({'complete':True,'candidate_count':len(candidates),'documents':len(result['documents']),
                      'events':len(events),'errors':len(result['errors']),'report':args.report}),flush=True)


if __name__=='__main__':main()
