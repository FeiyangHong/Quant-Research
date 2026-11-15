"""Build the real, dependency-scoped M7 dataset from hash-checked archives."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

from m7_data_collect import ROOT, OUT, REPORT, COHORT, save
from m7_data_audit import calendar, sha
from quant_research.data import Dataset, REQUIRED, PROVENANCE_COLUMNS, audit_dataset, save_dataset, load_dataset
from quant_research.cohort import cohort_dependencies, COHORT_SCOPE

STAGE=ROOT/'data/m7_fixed_cohort/stage_v1'

def main():
    if (STAGE/'manifest.json').exists():
        dataset=load_dataset(STAGE,allow_unverified=True)
        for path,digest in dataset.manifest['source_snapshot_hashes'].items():
            if sha(ROOT/path)!=digest:raise ValueError('Source changed '+path)
        print('Existing immutable stage reverified');return
    now=datetime.now(timezone.utc).isoformat();sessions=calendar()
    identities=json.loads((REPORT/'identity_evidence.json').read_bytes())
    state=json.loads((REPORT/'state_documents.json').read_bytes())
    logs=json.loads((REPORT/'request_log.json').read_bytes())
    snapshots={}
    def bind(path,digest=None):
        path=Path(path);path=path if path.is_absolute() else ROOT/path
        actual=sha(path)
        if digest is not None and actual!=digest:raise ValueError('Source changed '+str(path))
        snapshots[path.relative_to(ROOT).as_posix()]=actual
        return actual
    for r in logs:
        cap=r['receipt'];bind(cap['raw_path'],cap['sha256'])
    for p in [REPORT/'SOURCE_PLAN.json',REPORT/'identity_evidence.json',REPORT/'RAW_ELIGIBILITY.json',REPORT/'state_documents.json']:
        bind(p)
    for p in (REPORT/'titles').glob('*.json'):bind(p)
    book=json.loads((OUT/'budget.json').read_bytes())
    for r in book['attempts']:
        if r.get('raw_path'):bind(r['raw_path'],r['sha256'])
    license_id='PRIVATE_LOCAL_NONCOMMERCIAL_RESEARCH_ONLY'
    def provenance(source,url,digest,ingested,record,published,available,precision='date_only'):
        return dict(source=source,endpoint=url,raw_object_hash=digest,source_record_id=record,
            published_at=published,available_at=available,publication_precision=precision,
            vendor_first_seen_at=None,ingested_at=ingested,processed_at=now,availability_mode='historical_public_asof',
            license_profile_id=license_id,quality_status='provisional')
    master=[]
    for r in identities:
        sid=r['instrument_id'];bind(r['raw_path'],r['raw_object_hash'])
        master.append(dict(provenance('Official original ETF listing',r['source_url'],r['raw_object_hash'],r['ingested_at'],sid+':listing',r['published_at'],r['available_at']),
            instrument_id=sid,asset_type='ETF',board='ETF',listed_on=r['listed_on'],delisted_on=None,
            effective_from=r['listed_on'],effective_to=None,revision_id=sid+'_listing',supersedes_id=None,revision_kind=None,
            benchmark_id=r['exact_index_id'],industry='FIXED_ECONOMIC_PRODUCT:'+r['exact_index_id'],
            status='NORMAL',strategy_universe=COHORT_SCOPE,account_verified=True,
            account_permission_basis='HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT',actual_broker_permission_observed=False,
            lot_size=100,tick_size=.001,t_plus=1,legal_fund_name=r['legal_fund_name'],historical_metadata_verified=True,
            source_url=r['source_url'],trading_attribute_basis='ORIGINAL_LISTED_DOMESTIC_EQUITY_ETF_AND_REGISTERED_ACCOUNT_MODEL'))
    initial=next(r for r in master if r['instrument_id']=='sz.159946')
    last=initial
    for public,effective,status,delist in [('2018-12-19','2018-12-21','SUSPENDED',None),('2018-12-25','2018-12-28','RETIRED','2018-12-28')]:
        r=next(r for r in state if r['instrument_id']=='sz.159946' and r['publication_date']==public);cap=r['receipt']
        from quant_research.data import date_only_available_at
        row=dict(initial,**provenance('Issuer lifecycle announcement',r['source_url'],cap['sha256'],cap['ingested_at'],'sz.159946:'+public,public,date_only_available_at(public,sessions)))
        row.update(status=status,effective_from=effective,revision_id='sz.159946_'+status,supersedes_id=last['revision_id'],revision_kind='TRANSITION',delisted_on=delist,source_url=r['source_url'])
        master.append(row);last=row
    market_policy=json.loads((ROOT/'configs/r1_build_policy.json').read_bytes())
    bind('configs/r1_build_policy.json')
    bars=[]
    for sid in COHORT:
        path=OUT/'decoded'/('history_'+sid+'.json');digest=bind(path);payload=json.loads(path.read_bytes())
        for values in payload['rows']:
            r=dict(zip(payload['fields'],values));day=r['date']
            if r['tradestatus'] not in ('0','1'):raise ValueError('Unknown raw trading state')
            row=provenance('BaoStock','query_history_k_data_plus adjustflag=3',digest,payload['ingested_at'],sid+':'+day,None,day+'T21:00:00+08:00','reconstructed_market_close')
            row.update(date=day,instrument_id=sid,**{k:float(r[k]) for k in ['open','high','low','close','preclose','amount']},volume=int(r['volume']),
                upper_limit=None,lower_limit=None,suspended=r['tradestatus']=='0',source_trade_status=r['tradestatus'],
                revision_id=digest[:16]+':'+day,supersedes_id=None,total_return_index=None,total_return_available_at=None,
                usage_scope='COHORT_ELIGIBILITY_ONLY',market_event_at=day+'T15:00:00+08:00',
                availability_reconstruction=market_policy['market_availability']['reconstruction_basis'],
                availability_evidence_url=market_policy['market_availability']['source_url'])
            bars.append(row)
    prior=ROOT/'data/admitted_r1/phase2_v1/validation'
    prior_manifest=json.loads((prior/'manifest.json').read_bytes())
    bind(prior/'benchmark.json',prior_manifest['file_sha256']['benchmark.json'])
    bench=json.loads((prior/'benchmark.json').read_bytes())
    benchmark=pd.DataFrame(bench['records'],columns=bench['columns'])
    benchmark['quality_status']='provisional'
    b_root=ROOT/'data/normalized_csi/h00300_2010_2024_v1'
    b_manifest=json.loads((b_root/'manifest.json').read_bytes());bind(b_root/'manifest.json')
    for p,digest in b_manifest['files'].items():bind(b_root/p,digest)
    cal_evidence=prior_manifest['availability_calendar_evidence'];bind(cal_evidence['raw_path'],cal_evidence['sha256'])
    manifest=dict(schema_version='r1-offline-1.2',dataset_id='real-m7-fixed-cohort',dataset_version='stage-v1',
        research_scope=COHORT_SCOPE,data_origin='REAL',synthetic=False,timezone='Asia/Shanghai',
        units=dict(volume='shares_or_fund_units',amount='CNY',price='CNY'),calendar_kind='VERIFIED_EXCHANGE_CALENDAR',
        availability_calendar=prior_manifest['availability_calendar'],availability_calendar_evidence=cal_evidence,
        account_start='2016-01-01',signal_release_delay=1,coverage_start=sessions[0],coverage_end=sessions[-1],
        build_blockers=[],strategy_runs_permitted=False,status='STAGED_PENDING_INDEPENDENT_REVIEW',
        availability_mode='historical_public_asof',license_profile_id=license_id,source_snapshot_hashes=snapshots,
        evidence_gates={},performance_evidence=False,required_full_history_instruments=[],
        action_coverage_scope='NO_RANKING_ORDER_OR_HOLDING_DEPENDENCY_PROVEN_FROM_ALL_SEVEN_COMPLETE_AMOUNT_HISTORIES',
        action_table_empty_is_not_no_events_claim=True,actual_broker_permissions_observed=False,
        scope_limitations=['Historical public-asof reconstruction, not vendor vintage','Single manager fixed products, not current CSI level1 industry coverage',
            'Empty action table and null TR are justified only because all complete decisions have N<3 and account starts flat',
            'Ordinary domestic ETF hypothetical account permissions, no claim of observed personal broker eligibility'])
    dataset=Dataset(sessions,pd.DataFrame(master),pd.DataFrame(bars),pd.DataFrame(columns=REQUIRED['actions']+PROVENANCE_COLUMNS),benchmark,manifest)
    dependency=cohort_dependencies(dataset)
    if dependency['required_full_history_instruments']:raise RuntimeError('Actual ranking/holding dependency exists; build TR/actions before admission')
    manifest['cohort_dependencies']=dependency
    report=audit_dataset(dataset)
    save(REPORT/'stage_audit.json',report)
    if report['errors']:raise RuntimeError(str(report['errors']))
    save_dataset(dataset,STAGE)
    save(REPORT/'DEPENDENCY_MATRIX.json',dict(dependency,source_hashes=snapshots,
        decision='ALL_COMPLETE_MONTHS_N_LT_3',TR_required=False,account_actions_required=False,
        dead_member=dict(instrument_id='sz.159946',retained=True,never_eligible=True,ever_held=False,
            settlement_required=False,reason='Complete live-history 847 rows; zero eligible decision months; no ranks/orders/holdings possible'),
        excluded_endpoint=dict(anchor='2024-12-31',status='NO_EXECUTION_WITHIN_FROZEN_PERIOD',market_after_2024_read=False)))
    print(json.dumps(dict(stage=str(STAGE),bars=len(bars),master_rows=len(master),dependency_months=len(dependency['schedule']),errors=report['errors'],pending_blockers=report['blockers'])))

if __name__=='__main__':main()
