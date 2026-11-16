"""Decimal formation arithmetic with all missing/retired identities preserved."""
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
from m8_data_candidates import ROOT, REPORT, FRAME_SHA, save, sha
from m8_data_collect import OUT
from m7_data_audit import calendar
from quant_research.providers.official import label_date

def main(freeze=False):
    sessions=calendar();end=sessions.index('2019-12-31');window=sessions[end-59:end+1]
    documents=json.loads((REPORT/'formation_documents.json').read_bytes());exits={}
    for doc in documents:
        if '终止上市' not in doc['title']:continue
        text=Path(doc['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        day=label_date(compact,r'终止上市(?:日期|日)')
        if day:exits[doc['instrument_id']]=dict(date=day,document=doc)
    products=json.loads((REPORT/'PRODUCT_REVIEW.json').read_bytes())['records'];rows=[];groups=defaultdict(list);blockers=[]
    for product in products:
        sid=product['instrument_id'];row=dict(instrument_id=sid,product_evidence=product,exact_index_id=product.get('exact_index_id'),
            listed_on=product.get('listed_on'),listed_sessions=product.get('listed_sessions_at_formation'),
            median_amount60=None,status=product['status'])
        if sid in exits:
            row.update(status='EXCLUDED_EXITED_BEFORE_FORMATION',exit_evidence=exits[sid]);rows.append(row);continue
        if product['status']=='EXCLUDED_LISTED_LESS_THAN_60':rows.append(row);continue
        path=OUT/'decoded'/('formation_'+sid+'.json')
        if not path.exists():
            row.update(status='UNKNOWN_MISSING_HISTORY');blockers.append(sid+':MISSING_HISTORY');rows.append(row);continue
        payload=json.loads(path.read_bytes());allrows=[dict(zip(payload['fields'],r)) for r in payload['rows']]
        bydate={r['date']:r for r in allrows}
        if len(bydate)!=len(allrows):raise ValueError('Duplicate dates')
        missing=[d for d in window if d not in bydate]
        row.update(raw_path=str(path),raw_sha256=sha(path),missing_dates=missing,
                   window_observations=[dict(date=d,amount=bydate[d]['amount'],tradestatus=bydate[d]['tradestatus']) for d in window if d in bydate])
        if missing:
            row.update(status='UNKNOWN_INCOMPLETE_60_SESSION_WINDOW');blockers.append(sid+':MISSING_AMOUNTS');rows.append(row);continue
        amounts=sorted(Decimal(bydate[d]['amount']) for d in window)
        if any(x<0 for x in amounts):raise ValueError('Negative amount')
        median=(amounts[29]+amounts[30])/2;row['median_amount60']=str(median)
        if median<20000000:
            row['status']='EXCLUDED_MEDIAN_LT_20M';row['dependency_scope']='No additional state/index evidence can reverse numeric threshold failure'
        else:
            titlepath=REPORT/'titles'/('formation_'+sid+'.json')
            title=json.loads(titlepath.read_bytes()) if titlepath.exists() else {}
            if not title.get('complete') or not row['exact_index_id'] or bydate['2019-12-31']['tradestatus']!='1':
                row['status']='UNKNOWN_IDENTITY_OR_FORMATION_STATE';blockers.append(sid+':IDENTITY_STATE')
            else:
                row.update(status='QUALIFIED_INDEX_CANDIDATE',state_at_D0='NORMAL',
                    lifecycle_titles_path=str(titlepath),lifecycle_titles_sha256=sha(titlepath),
                    lifecycle_basis='Complete pre2020 official title history, reviewed contract amendments, no preformation termination or index transition, original exact index and D0 raw active state',
                    contract_amendments=[d for d in documents if d['instrument_id']==sid])
                groups[row['exact_index_id']].append(row)
        rows.append(row)
    representatives=[];dedup=[]
    for index,members in groups.items():
        ranked=sorted(members,key=lambda r:(-Decimal(r['median_amount60']),r['instrument_id']))
        representatives.append(ranked[0]);dedup.append(dict(exact_index_id=index,representative=ranked[0]['instrument_id'],
            members=[dict(instrument_id=r['instrument_id'],median_amount60=r['median_amount60'],original_name=r['product_evidence']['legal_fund_name'],original_sha256=r['product_evidence']['raw_object_hash']) for r in ranked],
            basis='Same exact named historical tracking index disclosed by each original; no correlation-based merging'))
    representatives.sort(key=lambda r:(-Decimal(r['median_amount60']),r['exact_index_id'],r['instrument_id']))
    for rank,r in enumerate(representatives,1):r['representative_rank']=rank
    # Author separately reads the source bytes; independent review table is not an admission authority.
    non_etf=[]
    for record in json.loads((REPORT/'listing_documents.json').read_bytes()):
        sid=record['instrument_id']
        if sid.startswith(('sh.51','sz.159')):continue
        text=Path(record['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        match=re.search(r'分级|LOF|上市开放式|开放式指数增强|股票型|混合型',compact[:600],re.I)
        if sid=='sz.161029' and '场外申购' in compact and '跨系统转托管' in compact:
            reason='Listed open-end index fund with off-exchange subscription/redemption and cross-system transfer; not exchange-traded creation/redemption ETF'
        elif match:reason='Original opening legal name explicitly discloses non-ETF product: '+match[0]
        else:reason=None;blockers.append(sid+':NON_ETF_NATURE_UNKNOWN')
        non_etf.append(dict(instrument_id=sid,status='EXCLUDED_ORIGINAL_NON_ETF' if reason else 'UNKNOWN',reason=reason,
                           source_url=record['listing']['source_url'],publication_date=record['listing']['publication_date'],
                           raw_path=record['receipt']['raw_path'],raw_sha256=record['receipt']['sha256'],opening_source_text=compact[:600],
                           identity_mapping_basis='Hash-bound official pre2020 title archive code/source association'))
    status='DATA_BLOCKED_SELECTION' if blockers else 'FORMED' if len(representatives)>=6 else 'COHORT_NOT_FORMED'
    available=sessions[end+1]+'T21:00:00+08:00'
    first_anchor=next(day for i,day in enumerate(sessions[:-2]) if day>sessions[end+1] and day[:7]!=sessions[i+1][:7])
    first_execution=sessions[sessions.index(first_anchor)+2]
    result=dict(scope='R1I_HISTORICAL_LIQUID_V1',status=status,formation_date='2019-12-31',cohort_available_at=available,
        sampling_frame_sha256=FRAME_SHA,candidate_review_sha256=sha(REPORT/'CANDIDATE_REVIEW.json'),
        formation_window=window,amount_unit='CNY',threshold='20000000',formation_age_sessions=60,
        trade_age_sessions=252,selection_max=10,selection_min=6,selected_instruments=[r['instrument_id'] for r in representatives[:10]] if status=='FORMED' else [],
        first_legal_signal_anchor=first_anchor,first_base_execution=first_execution,
        ETF_candidate_rows=rows,non_ETF_original_reviews=non_etf,exact_index_dedup=dedup,
        representative_ranking=[dict(rank=i+1,instrument_id=r['instrument_id'],exact_index_id=r['exact_index_id'],median_amount60=r['median_amount60'],selected=i<10) for i,r in enumerate(representatives)],
        blockers=blockers,counts=dict(Counter(r['status'] for r in rows)),frozen_at=datetime.now(timezone.utc).isoformat(),
        post2019_market_data_used=False,future_survival_used=False,strategy_returns_inspected=False,
        state_evidence_limitation='Public historical archive reconstruction, not vendor vintage or a current national-sector universe')
    path=REPORT/('COHORT_SELECTION.json' if freeze else 'FORMATION_REVIEW_DRAFT.json')
    if freeze and path.exists():raise ValueError('Selection already frozen')
    save(path,result)
    print(status,result['counts'],'blockers',blockers)
    for r in result['representative_ranking']:print(r)

if __name__=='__main__':
    import sys
    main('--freeze' in sys.argv)
