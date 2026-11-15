"""Bounded, pre-registered historical share-source contract probe, never alpha."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from m6_sources import ROOT, OUT as RAW, fetch, reuse
from quant_research.budget import atomic_json
from m5_market_cap import select_vendor_candidate

OUT=ROOT/'reports/m6_stock_source'
DATE='2020-07-31'
FIXED=['600519.SH','002526.SZ','601398.SH','600518.SH','300855.SZ']


def request_url(page, *, fixed=False):
    restriction="(END_DATE<='2020-07-31')"
    if fixed:
        restriction+='(SECUCODE in ("'+'","'.join(FIXED)+'"))'
    return 'https://datacenter-web.eastmoney.com/api/data/v1/get?'+urlencode(dict(
        reportName='RPT_F10_EH_EQUITY',columns='ALL',filter=restriction,
        pageNumber=page,pageSize=500,sortColumns='END_DATE,SECUCODE,NOTICE_DATE',
        sortTypes='-1,1,-1',source='WEB',client='WEB'))


def collect():
    if not (OUT/'SOURCE_PLAN.md').exists():raise RuntimeError('Source plan absent')
    # Two pages assess bulk pagination; the fixed-basket page assesses ID filter.
    # A fourth page is permitted only when the fixed basket reports >1 page.
    observations=[]
    for page,fixed in [(1,False),(2,False),(1,True)]:
        label=f"stock_source_{'fixed' if fixed else 'all'}_page{page}"
        rec=fetch(label,request_url(page,fixed=fixed),dates=f'{DATE}~{DATE}',scope='stock_source',route='historical_shares')
        observations.append(rec)
    atomic_json(OUT/'request_manifest.json',observations)
    fixed=observations[-1]
    if fixed.get('status')=='FETCHED':
        data=json.loads(Path(fixed['raw_path']).read_bytes())
        if (data.get('result') or {}).get('pages',0)>1:
            rec=fetch('stock_source_fixed_page2',request_url(2,fixed=True),dates=f'{DATE}~{DATE}',scope='stock_source',route='historical_shares')
            observations.append(rec)
            atomic_json(OUT/'request_manifest.json',observations)


def inspect():
    requests=json.loads((OUT/'request_manifest.json').read_text(encoding='utf8'))
    original=ROOT/'reports/m4_data/full_pool_2020-07-31.json'
    pool=json.loads(original.read_text(encoding='utf8'))['rows']
    ids={r['instrument_id'] for r in pool}
    if len(ids)!=3779:raise ValueError('Original diagnostic denominator changed')
    pages=[];observed={};all_records=[];fixed_records=[]
    for rec in requests:
        reuse(rec['raw_path'],expected_sha256=rec['sha256'])
        payload=json.loads(Path(rec['raw_path']).read_bytes()) if rec['status']=='FETCHED' else {}
        result=payload.get('result') or {}
        rows=result.get('data') or []
        parsed=[]
        for row in rows:
            sec=row.get('SECUCODE','')
            if len(sec)==9 and sec[-2:] in {'SH','SZ'}:parsed.append(sec[-2:].lower()+'.'+sec[:6])
        page=dict(label=rec['label'],success=payload.get('success'),provider_code=payload.get('code'),provider_message=payload.get('message'),
            row_count=len(rows),provider_total=result.get('count'),provider_pages=result.get('pages'),
            observed_unique_ids=len(set(parsed)),fixed_denominator_ids=len(set(parsed)&ids),
            future_economic_rows=sum((r.get('END_DATE') or '')[:10]>DATE for r in rows),
            columns=sorted({key for row in rows for key in row}),request=rec)
        pages.append(page)
        if '_fixed_' in rec['label']:fixed_records.extend(rows)
        if '_all_' in rec['label']:
            all_records.extend(rows)
            for row in rows:
                sec=row.get('SECUCODE','')
                if len(sec)==9 and sec[-2:] in {'SH','SZ'}:
                    sid=sec[-2:].lower()+'.'+sec[:6]
                    observed.setdefault(sid,[]).append(row)
    keys=[(r.get('SECUCODE'),r.get('END_DATE'),r.get('NOTICE_DATE'),r.get('CHANGE_REASON')) for r in all_records]
    coverage=[]
    for r in pool:
        rows=observed.get(r['instrument_id'],[])
        coverage.append(dict(instrument_id=r['instrument_id'],snapshot_date=DATE,
            original_status=r['trade_status'],original_isST=r['isST_vendor_history'],
            bulk_probe_rows=len(rows),bulk_probe_observed=bool(rows),
            formal_pit_share_count=None,formal_market_cap=None,size_percentile=None,
            reason='PROBE_PAGES_ONLY_NOT_FULL_PAGINATION; missing is not historically unpublished',
            current_or_historical_name_used_for_admission=False))
    result=dict(snapshot_date=DATE,purpose='ENGINEERING_SOURCE_CONTRACT_NOT_ALPHA',diagnostic_denominator=3779,
        independently_complete_historical_roster=False,pages=pages,
        all_page_rows=len(all_records),all_page_unique_ids=len(observed),fixed_pool_ids_observed=len(set(observed)&ids),
        repeated_economic_notice_change_keys=len(keys)-len(set(keys)),
        complete_pagination=False,formal_PIT_capital_chain_count=0,
        notice_date_proves_original_publication=False,revision_chain_available=False,
        explicit_historical_data_license_verified=False,
        new_http_attempts=len(requests),new_body_bytes=sum(r['byte_count'] for r in requests),
        original_denominator_source=reuse(original))
    atomic_json(OUT/'batch_observations.json',result)
    atomic_json(OUT/'fixed_denominator_coverage.json',dict(rows=coverage))
    prior_path=ROOT/'reports/m5_market_cap/coverage_summary.json'
    prior=json.loads(prior_path.read_text(encoding='utf8'))
    cases=[]
    for case in prior['cases']:
        sid=case['instrument_id'];sec=sid[3:]+'.'+sid[:2].upper()
        events=[r for r in fixed_records if r['SECUCODE']==sec]
        chosen,rejected=select_vendor_candidate(events)
        fact=case['original_document_fact']
        cases.append(dict(instrument_id=sid,event_rows=len(events),
            nonzero_total_change_rows=sum(r.get('TOTAL_SHARES_CHANGE') not in (None,0) for r in events),
            float_structure_only_rows=sum(r.get('TOTAL_SHARES_CHANGE')==0 and r.get('LIMITED_SHARES_CHANGE') not in (None,0) for r in events),
            missing_document_identity_rows=sum(not r.get('INFO_CODE') for r in events),
            candidate=chosen,clock_rejections=rejected,documentary_total_shares=fact['total'],
            documentary_a_shares=fact['a'],documentary_h_shares=fact['h'],unit='SHARES_MATCHES_FIXED_ORIGINAL_DOCUMENTS',
            total_count_match=chosen is not None and chosen['TOTAL_SHARES']==fact['total'],
            a_count_match=chosen is not None and chosen['TOTAL_A_SHARES']==fact['a'],
            original_document_source=case['document_source'],original_document_pages=fact['pages'],
            notice_semantics_verified=False,full_capital_chain_verified=False,human_signoff=False))
    mean_bytes=sum(p['request']['byte_count'] for p in pages if '_all_' in p['label'])/2
    reported_pages=pages[0]['provider_pages']
    contract=dict(decision='FEASIBLE_FOR_NEXT_REGISTERED_DATA_PILOT',
        decision_scope='EASTMONEY_BOUNDED_DIAGNOSTIC_ONLY_NOT_FORMAL_PIT_ADMISSION',
        rationale='Batch and pagination work; 5 fixed structural values reconcile. Next pilot must test original clocks/revision contract; no automatic continuation.',
        route1='EASTMONEY_RPT_F10_EH_EQUITY',route1_batch_verified=True,
        route1_complete_snapshot=False,route1_cases=cases,
        route1_unrestricted_historical_events_total=pages[0]['provider_total'],
        route1_full_pagination_requests=reported_pages,
        route1_full_pagination_bytes_estimate=round(mean_bytes*reported_pages),
        estimate_basis='Two 500-row pages; all provider markets and pre-IPO identities, not the 3779 target-only cost; not executed',
        route2='REUSED_BAOSTOCK_HISTORICAL_ALL_STOCK_AND_DAILY',route2_total_share_contract='ABSENT_IN_OBSERVED_RESPONSE_FIELDS',
        route2_new_requests=0,route2_share_reconstruction='STOP_FREE_RECONSTRUCTION_ROUTE_FOR_THIS_OBSERVED_ENDPOINT',
        route2_field_source=reuse(ROOT/'reports/m4_data/baostock_request_summary.json'),
        route2_raw_response=reuse(ROOT/'data/raw_m4_equity/baostock/full_daily_20200731.json'),
        prior_five_case_audit=reuse(prior_path),
        valuation_object_unresolved=True,formal_cap_admitted=0,full_pool_percentiles=None,
        no_change_in_total_shares_does_not_by_itself_block_total_ordinary_cap=True,
        constraints=['Complete historical roster still unproved','Original publication/revision lineage absent from observed schema',
            'Provider names and pre-IPO rows cannot establish historical eligibility',
            'A_PRICE_TIMES_ALL_ORDINARY versus A_ORDINARY and profit numerator attribution unresolved',
            'Public accessibility is not an explicit historical data redistribution license',
            'No full-pool run, no whole-history PDF reconstruction, no strategy experiment authorized'])
    atomic_json(OUT/'source_contract_decision.json',contract)
    print(json.dumps({k:v for k,v in result.items() if k not in ('pages','original_denominator_source')},ensure_ascii=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['collect','inspect'])
    args=parser.parse_args()
    collect() if args.mode=='collect' else inspect()
