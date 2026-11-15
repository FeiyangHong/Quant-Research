"""Rebuild M4 documentary evidence and coverage from immutable local objects."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from m4_data_feasibility import ROOT, OUT, REPORT, SNAPSHOT_DATE, budget, now, save, date_only_clock

FIELDS=['net_profit_parent','operating_cash_flow','total_assets']

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def hashed(path):
    path=Path(path)
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'byte_count':path.stat().st_size}

def old_source(label):
    matches=[]
    for p in (ROOT/'data/raw_equity_admission/http_manifests').glob('*.json'):
        d=read(p)
        if d['id']==label:matches.append(d)
    if len(matches)!=1:raise ValueError((label,len(matches)))
    return matches[0]

def source(label):
    return read(OUT/'manifests'/f'{label}.json')

def calendar():
    days=[];evidence=[]
    for part in ['development','validation']:
        p=ROOT/f'data/admitted_r1/phase2_v1/{part}/calendar.json'
        days+=read(p);evidence.append(hashed(p))
    boundary=read(ROOT/'reports/real_data_phase3/availability_calendar_boundary.json')
    days+=['2025-01-02','2025-01-03']
    evidence.append(boundary|{'extension_purpose':'Clock-only Jan2/Jan3 regular sessions after official Jan1 closure; zero 2025 market observations'})
    save(REPORT/'calendar_evidence.json',{'sources':evidence,'date_only_rule':'strictly after publication, first trading day 21:00; next trading day execution','extension_does_not_open_holdout':True})
    return sorted(set(days))

def build_cases(days):
    queue=read(ROOT/'reports/m3_equity_admission/revision_candidate_queue.json')['cases']
    cases=[]
    old=read(ROOT/'reports/m3_equity_admission/financial_vintage_case.json')
    old.update(case_status='COMPLETE_DOCUMENTARY_PAIR',independent_human_reviews=0,counts_toward_human_admission_gate=False,queue_position=0,missing=['independent human signoff','verified intraday publication','vendor historical first seen','exhaustive later revision history beyond demonstrated pair'],source_unit='CNY yuan',normalized_unit='CNY yuan',revision_chain_scope='demonstrated original-to-2019 pair only; later 2020 revision not falsely declared absent')
    cases.append(old)
    specs=[
      (0,'2019-12-31','2020-04-30','original_002528_2019',None,['75093950.34','-830369320.86','6536209706.95'],['4952157.23','-830369320.86','6188979375.75'],[9],[2,3],[]),
      (1,'2023-12-31','2024-04-30','original_000908_2023','revised_000908_2023',['-215144077.22','35063943.44','1060346384.15'],['-236100444.70','35063943.44','1060346384.15'],[7,8],[1,2,3,8],[{'field':'net_profit_parent','statement_value':'-236100444.70','correction_value':'-236100444.69','difference_cny':'0.01','resolution':'UNRESOLVED; canonical revised field withheld'}]),
      (2,'2022-12-31','2023-04-28','original_600165_2022','revised_600165_2022',['-141484322.30','53144180.21','3278697835.50'],['-210984106.46','-33407119.79','3277789331.90'],[6],[6,17,76],[{'field':'operating_cash_flow','statement_value':'-33407119.79','narrative_cashflow_table_value':'53144180.21','statement_source_page':76,'conflict_source_page':17,'resolution':'UNRESOLVED internal revised-document conflict; canonical revised field withheld'}]),
      (3,'2023-09-30','2023-10-26','original_002857_2023q3',None,['-6354889.62','-9898689.75','726007340.73'],['-8587577.84','-9898689.75','736593802.62'],[2],[2,3,4],[]),
      (4,'2022-12-31','2023-04-22','original_300632_2022','revised_300632_2022',['52513080.53','61552281.48','2588079679.94'],['52513080.53','61552281.48','2588079679.94'],[9],[8],[]),
      (5,'2021-06-30','2021-08-18','original_300617_2021h1','revised_300617_2021h1',['120146569.32','-7586631.41','2934576362.90'],['122956775.89','-7586631.41','2936277134.72'],[8],[2,7,22],[{'field':'total_assets','statement_value':'2936277134.72','correction_asset_row_value':'2936277134.73','correction_liabilities_equity_row_value':'2936277134.72','difference_cny':'0.01','resolution':'UNRESOLVED; canonical revised field withheld'}]),
      (6,'2022-09-30','2022-10-31','original_002729_2022q3','revised_002729_2022q3',['21426386.57','5001212.67','605965380.44'],['21426386.57','5035278.32','579897054.72'],[2],[1],[]),
    ]
    for pos,period,pub,orig,revised,ov,rv,op,rp,conflicts in specs:
        q=queue[pos];ident=q['instrument_id']+'_'+period
        base={'case_id':ident,'instrument_id':q['instrument_id'],'period_end':period,'queue_position':pos+1,
          'case_status':'QUARANTINED_SOURCE_CONFLICT' if conflicts else 'COMPLETE_DOCUMENTARY_PAIR',
          'availability_mode':'historical_public_asof','publication_precision':'date_only','vendor_first_seen_at':None,
          'source_unit':'CNY yuan','normalized_unit':'CNY yuan','report_scope':'consolidated; net profit attributable to parent; flow amounts YTD; assets at period end',
          'independent_human_reviews':0,'counts_toward_human_admission_gate':False,
          'processed_at':now(),'agent_documentary_review':True,'conflicts':conflicts,
          'missing':['independent human signoff','verified intraday publication','vendor historical first seen','exhaustive all-version-chain search'],
          'revision_chain_scope':'explicit original and disclosed correction pair; no assertion that unobserved intermediate/later versions never existed'}
        original={'revision_id':ident+'_original','supersedes_id':None,'published_date':pub,**date_only_clock(pub,days),'document':source(orig),'pages':op,'values':dict(zip(FIELDS,ov))}
        revision={'revision_id':ident+'_revision_'+q['publication_date'],'supersedes_id':original['revision_id'],'published_date':q['publication_date'],**date_only_clock(q['publication_date'],days),'document':source(revised) if revised else q['source'],'pages':rp,'supporting_correction_document':q['source'],'as_reported_values':dict(zip(FIELDS,rv)),'values':dict(zip(FIELDS,rv))}
        for conflict in conflicts:revision['values'][conflict['field']]=None
        base.update(original=original,revision=revision)
        if pos==4:base['unchanged_fields_note']='R2 fields unchanged; revenue and cost both corrected by -31,568,345.38 CNY. Still one genuine original/revised report pair, not three field-cases.'
        cases.append(base)
    for case in cases:save(REPORT/'financial_cases'/f"{case['case_id']}.json",case)
    result={'case_order':'Existing Kangmei then fixed M3 queue positions 1..7; three failed/conflicted cards retained, continue until first five complete documentary pairs',
      'attempted_issuer_period_cases':len(cases),'complete_documentary_pairs':sum(c['case_status']=='COMPLETE_DOCUMENTARY_PAIR' for c in cases),
      'quarantined_cases':sum(c['case_status'].startswith('QUARANTINED') for c in cases),'independent_human_accepted_cases':0,
      'full_pool_vintage_gate':'BLOCKED','complete_is_not_admission':True,'cases':cases}
    save(REPORT/'financial_vintage_cases.json',result)
    return result

def official_industry(text):
    """Parse official two-digit industry groups without contemporary names.

    The table repeats group headers at page boundaries. Every six-digit code
    must have a preceding group; conflicting duplicate mappings fail closed.
    """
    mapping={};group=None
    for line in text.splitlines():
        match=re.search(r'(?<!\d)(\d{6})(?!\d)',line)
        if not match:continue
        heads=re.findall(r'(?<!\d)(\d{2})(?!\d)',line[:match.start()])
        if heads:group=heads[-1]
        if group is None:raise ValueError('Industry row missing group header')
        code=match.group(1)
        if code in mapping and mapping[code]!=group:raise ValueError('Conflicting official industry code')
        mapping[code]=group
    return mapping

def board(code):
    if code.startswith(('sh.600','sh.601','sh.603','sh.605','sz.000','sz.001','sz.002','sz.003')):return 'MAIN'
    if code.startswith(('sz.300','sz.301')):return 'CHINEXT'
    return 'OUTSIDE_FIXED_ACCOUNT_SCOPE'

def join_full_pool(universe,daily,industry,official):
    result=[]
    for u in universe:
        code=u['code']
        if board(code)=='OUTSIDE_FIXED_ACCOUNT_SCOPE':continue
        d=daily.get(code,{});ind=industry.get(code,{})
        row={'instrument_id':code,'snapshot_date':SNAPSHOT_DATE,'board_scope':board(code),'universe_membership_observed':True,
         'vendor_name_untrusted_historical':u.get('code_name'),'trade_status':u.get('tradeStatus'),
         'isST_vendor_history':d.get('isST') or None,'risk_state_complete':None,
         'raw_ohlcv':{f:d.get(f) or None for f in ['open','high','low','close','preclose','volume','amount','tradestatus','adjustflag']},
         'vendor_industry':ind.get('industry') or None,'vendor_industry_snapshot_date':ind.get('updateDate') or None,
         'official_industry_group':official.get(code.split('.')[1]),'official_industry_source_period':'2020Q2','official_industry_published_date':'2020-07-14',
         'historical_total_shares':None,'market_cap_same_share_scope':None,'listing_age_252_sessions':None,
         'median_amount_60_sessions':None,'corporate_actions_complete':None,'financial_vintage_complete':None,
         'r2_qualified':None,'r3_qualified':None,
         'missing_reason':'UNVERIFIED_HISTORY_NOT_NOT_PUBLISHED; no current survivor/name/share substitution'}
        result.append(row)
    return result

def build_snapshot(days):
    def rows(label):
        obj=read(OUT/'baostock'/f'{label}.json')
        if obj['error_code']!='0':raise ValueError('Incomplete provider response')
        result=[dict(zip(obj['fields'],r)) for r in obj['rows']]
        if len({r['code'] for r in result})!=len(result):raise ValueError('Duplicate code in snapshot')
        return result
    uni=rows('full_universe_20200731');daily=rows('full_daily_20200731');ind=rows('full_industry_20200731')
    if any(r['date']!=SNAPSHOT_DATE or r['adjustflag']!='3' for r in daily):raise ValueError('Snapshot date/raw-price mismatch')
    if any(r['updateDate']>SNAPSHOT_DATE for r in ind):raise ValueError('Future industry snapshot')
    official_text=ROOT/'work/m4_data/csrc_industry_2020q2.txt'
    official_text.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['pdftotext','-layout',old_source('csrc_industry_2020q2')['raw_path'],str(official_text)],check=True,capture_output=True)
    official=official_industry(official_text.read_text(encoding='utf-8'))
    pool=join_full_pool(uni,{r['code']:r for r in daily},{r['code']:r for r in ind},official)
    save(REPORT/'full_pool_2020-07-31.json',{'role':'ONE_DEVELOPMENT_MONTH_END_COVERAGE_AUDIT_NO_RETURNS','snapshot_date':SNAPSHOT_DATE,'denominator':'all historical main-board plus ChiNext members before ST/liquidity/financial/share filters','rows':pool})
    fields={
      'historical_membership':lambda r:True,'trading_status':lambda r:r['trade_status'] in ['0','1'],
      'raw_close':lambda r:r['raw_ohlcv']['close'] is not None,'raw_volume':lambda r:r['raw_ohlcv']['volume'] is not None,
      'raw_amount':lambda r:r['raw_ohlcv']['amount'] is not None,'vendor_daily_isST':lambda r:r['isST_vendor_history'] is not None,
      'complete_risk_state':lambda r:r['risk_state_complete'] is not None,'historical_vendor_industry':lambda r:r['vendor_industry'] is not None,
      'official_2020Q2_industry_public_by_snapshot':lambda r:r['official_industry_group'] is not None,
      'historical_total_shares':lambda r:r['historical_total_shares'] is not None,'market_cap':lambda r:r['market_cap_same_share_scope'] is not None,
      'listing_age_252_sessions':lambda r:r['listing_age_252_sessions'] is not None,'median_amount_60_sessions':lambda r:r['median_amount_60_sessions'] is not None,
      'corporate_actions_complete':lambda r:r['corporate_actions_complete'] is not None,'financial_vintage_complete':lambda r:r['financial_vintage_complete'] is not None,
      'r2_qualification_known':lambda r:r['r2_qualified'] is not None,'r3_qualification_known':lambda r:r['r3_qualified'] is not None}
    cov={k:{'observed':sum(bool(f(r)) for r in pool),'denominator':len(pool)} for k,f in fields.items()}
    for value in cov.values():value['percent']=round(100*value['observed']/value['denominator'],4)
    discrep=[]
    for r in pool:
        if r['vendor_industry'] and r['official_industry_group'] and r['vendor_industry'][1:3]!=r['official_industry_group']:discrep.append(r['instrument_id'])
    summary={'snapshot_date':SNAPSHOT_DATE,'all_security_response_rows':len(uni),'all_A_daily_rows':len(daily),'main_chinext_denominator':len(pool),'official_table_total_codes':len(official),'industry_source':old_source('csrc_industry_2020q2'),
      'official_industry_publication_source':old_source('csrc_industry_2020q2_page'),'official_industry_available_at':date_only_clock('2020-07-14',days)['available_at'],
      'coverage':cov,'boards':dict(Counter(r['board_scope'] for r in pool)),'vendor_st_counts':dict(Counter(str(r['isST_vendor_history']) for r in pool)),
      'trade_status_counts':dict(Counter(r['trade_status'] for r in pool)),'vendor_official_raw_industry_code_differences':discrep,
      'classification_code_difference_note':'121 raw code differences include taxonomy-version shifts (official R86 versus vendor R87, official S90 versus vendor S91). No unverified crosswalk or error attribution. Both source codes retained.',
      'nonST_size_percentile_denominator':None,'why_size_denominator_unknown':'Historical total shares and complete risk-status/event histories absent; do not shrink to financially complete or currently surviving rows',
      'r2_status':'BLOCKED','r3_status':'BLOCKED','historical_pool_completeness_against_independent_exchange_roster':'UNVERIFIED; actual provider full-date response, not a claim vendor omissions are impossible',
      'name_warning':'query_all_stock code_name can be retrospective; never used to reconstruct historical ST, board, delisting or industry',
      'price_availability':'Date of price formation observed; exact original vendor delivery/21:00 timeliness unknown',
      'industry_limitation':'Official quarter snapshot public clock verified, intervening issuer changes not comprehensively audited; weekly vendor updateDate is not public/effective date'}
    save(REPORT/'coverage_summary.json',summary)
    return summary

def build_events(days):
    events=[]
    for i,event in enumerate(read(ROOT/'reports/m3_equity_admission/corporate_action_cases.json')['events']):
        events.append(event|{'event_id':event['action_id'],'event_type':'CASH_DIVIDEND_ORDINARY' if i==0 else 'CASH_DIVIDEND_SPECIAL','unit':'CNY per share','currency':'CNY','published_at':event['published_date'],'publication_precision':'date_only',**date_only_clock(event['published_date'],days),'availability_mode':'historical_public_asof','vendor_first_seen_at':None,'processed_at':now(),'quality_status':'provisional','account_credited_at':None,'missing':['actual account credit intraday timestamp','holder lot tax history','all-pool events'],'sdk_incompleteness_is_not_missing_public_event':bool(i)})
    templates=[
      ('KM_OTHER_RISK_20190521','sh.600518','OTHER_RISK_WARNING','2019-05-18','2019-05-21',source('kangmei_st_primary_20190518'),{'risk_label':'ST','suspension_date':'2019-05-20','price_limit_pct':'5','effective_to':None}),
      ('LESHI_TERMINATION_DECISION','sz.300104','TERMINATION_DECISION','2020-05-14','2020-05-14',old_source('leshi_delisting_20200514'),{'liquidation_trading_start':'2020-06-05','actual_delisting_date':None,'cash_recovery':None}),
      ('LESHI_REGISTRATION_END','sz.300104','EXCHANGE_REGISTRATION_END','2020-07-27','2020-07-24',old_source('leshi_registration_end_20200724'),{'document_signed_date':'2020-07-24','already_delisted':True,'actual_delisting_date':None,'cash_recovery':None}),
      ('SHIJIA_INDUSTRY_CHANGE','sz.002796','INDUSTRY_CHANGE','2020-07-17',None,old_source('shijia_industry_change_20200717'),{'old_classification':'C33','new_classification':'C39','classification':'CSRC2012','earlier_official_published_date':'2020-07-14','economic_classification_snapshot':'2020Q2','exact_effective_from':None}),
    ]
    for ident,instr,kind,pub,eff,src,extra in templates:
        events.append({'event_id':ident,'instrument_id':instr,'event_type':kind,'published_at':pub,'publication_precision':'date_only','effective_from':eff,'source':src,'document_hash':src['sha256'],'raw_object_hash':src['sha256'],'availability_mode':'historical_public_asof','vendor_first_seen_at':None,'processed_at':now(),'quality_status':'provisional',**date_only_clock(pub,days),**extra})
    for event in events:
        event.update(ingested_at=event['source']['ingested_at'],document_hash=event['source']['sha256'],raw_object_hash=event['source']['sha256'],revision_id=event['event_id']+'_PUBLIC_ORIGINAL',supersedes_id=None)
    save(REPORT/'normalized_events.json',{'events':events,'full_universe_event_completeness':False,'not_runner_admitted':True,'human_reviews':0,'source_failure_preserved':old_source('kangmei_st_notice_20190518'),'source_failure_reason':'M3 SSE PDF URL returned HTML; not accepted as document. Replaced by verified CNInfo original, old body retained.'})
    return events

def main():
    start=time.perf_counter();days=calendar();cases=build_cases(days);coverage=build_snapshot(days);events=build_events(days)
    b=budget()
    for r in b['attempts']:save(OUT/'manifests'/f"{r['label']}_{r['id']:04d}.json",r)
    save(REPORT/'cost_and_work_units.json',{
      'budget_registered_at':b['registered_at'],'measured_at':now(),'limits':b['limits'],'used':b['used'],
      'download_body_mib':round(b['used']['new_body_bytes']/1048576,4),'new_network_elapsed_seconds':round(sum(r.get('elapsed_seconds',0) for r in b['attempts']),6),
      'audit_elapsed_since_registration_seconds':round((__import__('datetime').datetime.fromisoformat(now())-__import__('datetime').datetime.fromisoformat(b['registered_at'])).total_seconds(),3),
      'offline_build_seconds':round(time.perf_counter()-start,6),'human_review_count':0,'human_review_minutes':0,'purchases_cny':0,'commercial_price':None,
      'agent_work_units':{'attempted_issuer_period_pairs':8,'new_original_reports':7,'new_full_revised_reports':5,'new_ST_notice':1,'existing_correction_documents_reconciled':7,'R2_field_pairs_reconciled':24,'source_conflicts_quarantined':3,'new_PDF_pages_visually_inspected':18,'human_independent_acceptances':0},
      'agent_work_time_note':'Wall-clock since budget registration includes extraction, reading and tool latency; not a measured human labor rate or continuous CPU time',
      'stages':[{'stage':'full-date universe/daily/industry','wire_attempts':8,'rows':[4810,3923,4030],'failed_local_optional_step':'query_st_stocks absent from top-level SDK export after three successful datasets; no extra network request or session retry'},
        {'stage':'fixed correction queue original pairing','attempted_cases':8,'complete_pairs':5,'conflicted':3},
        {'stage':'events and official industry','normalized_events':len(events),'official_table_codes':coverage['official_table_total_codes']}],
      'minimum_cost_route':['Reuse official 2020Q2 table + original source archive and local calendars first (zero new bytes).','Three BaoStock full-date APIs obtained complete response sets in 8 wire attempts including login/pagination; per-security day requests would consume thousands.','Official original/correction pairing now yields five complete pairs with seven new issuer attempts; do not replace originals with latest financial API.','Next bottlenecks: historical share-class events, full risk/lifecycle/IPO roster and 60-session amount histories; retain full 2020-07-31 denominator while filling.','Continue fixed correction queue to 20 documentary cases and independent human acceptance; do not buy unless a quantified unresolved gap remains.'],
      'extrapolation':'One date is measured, not a claim the full historical pool is affordable within this envelope. No strategy returns or 2025+ market data acquired.'})
    sources={}
    def collect(value):
        if isinstance(value,dict):
            if value.get('raw_path') and value.get('sha256'):
                p=Path(value['raw_path'])
                actual=hashlib.sha256(p.read_bytes()).hexdigest()
                if actual!=value['sha256']:raise ValueError(f'Source hash mismatch: {p}')
                sources[p.as_posix()]=hashed(p)|{'source_url':value.get('url'),'expected_sha256':value['sha256']}
            for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    collect(cases);collect(coverage);collect(events);collect(b)
    for p in (OUT/'baostock').glob('*.json'):sources[p.as_posix()]=hashed(p)
    save(REPORT/'source_manifest.json',{'schema_version':'m4-source-manifest-1','created_at':now(),'raw_objects':list(sources.values()),'verified_hash_count':len(sources),'source_hash_status':'ALL_MATCH','budget':b['used'],'scope':'Local research raw evidence; no public redistribution licence implied','rebuild_requires':'Original M3 raw archive, new M4 raw archive, admitted R1 calendars and existing 2024-published 2025 calendar notice; only calendar values reused from R1, no performance','code':[hashed(ROOT/'scripts/m4_data_feasibility.py'),hashed(ROOT/'scripts/m4_data_build.py')]})
    print(json.dumps({'cases':cases['complete_documentary_pairs'],'conflicts':cases['quarantined_cases'],'pool':coverage['main_chinext_denominator'],'coverage':coverage['coverage'],'used':b['used']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
