"""Build M8 full holding stage from frozen cohort and source-verified actions."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import pandas as pd
from m8_data_collect import ROOT, OUT, REPORT, save, sha
from m7_data_audit import calendar
from quant_research.data import Dataset, REQUIRED, PROVENANCE_COLUMNS, EVIDENCE_GATES, audit_dataset, save_dataset, load_dataset, date_only_available_at
from quant_research.providers.real_builder import historical_limits, reconstruct_total_return, normalize_actions, _coverage_complete
from quant_research.liquid_cohort import LIQUID_SCOPE, liquid_dependencies

STAGE=ROOT/'data/m8_rotation/stage_v1'

def main():
    if (STAGE/'manifest.json').exists():
        raise ValueError('Immutable stage already exists; review before a new version')
    now=datetime.now(timezone.utc).isoformat();sessions=calendar();snapshots={}
    def bind(path,digest=None):
        path=Path(path);path=path if path.is_absolute() else ROOT/path;actual=sha(path)
        if digest and digest!=actual:raise ValueError('Source hash mismatch '+str(path))
        snapshots[path.relative_to(ROOT).as_posix()]=actual
        return actual
    selection_path=REPORT/'COHORT_SELECTION.json';selected=json.loads(selection_path.read_bytes());selection_sha=bind(selection_path)
    events=json.loads((REPORT/'EVENT_MANIFEST.json').read_bytes());policy=json.loads((REPORT/'HOLDING_RULE_POLICY.json').read_bytes())
    base_policy=json.loads((ROOT/'configs/r1_build_policy.json').read_bytes())
    for path in [REPORT/'EVENT_MANIFEST.json',REPORT/'HOLDING_RULE_POLICY.json',REPORT/'PRICE_RECONCILIATION.json',REPORT/'SOURCE_POLICY_ADDENDUM.md',REPORT/'HOLDING_HISTORY_REQUESTS.json',ROOT/'configs/r1_build_policy.json']:
        bind(path)
    for path,digest in policy['source_evidence_files'].items():bind(path,digest)
    # Source bodies are immutable; the still-open accounting ledger is not an input snapshot.
    book=json.loads((OUT/'budget.json').read_bytes())
    for record in book['attempts']:
        if record.get('raw_path') and record.get('sha256'):bind(record['raw_path'],record['sha256'])
    for doc in events['documents']:
        bind(doc['receipt']['raw_path'],doc['receipt']['sha256'])
    license_id='PRIVATE_LOCAL_NONCOMMERCIAL_RESEARCH_ONLY'
    def provenance(source,url,digest,ingested,record,published,available,precision='date_only'):
        return dict(source=source,endpoint=url,raw_object_hash=digest,ingested_at=ingested,processed_at=now,
            source_record_id=record,published_at=published,available_at=available,publication_precision=precision,
            vendor_first_seen_at=None,availability_mode='historical_public_asof',license_profile_id=license_id,quality_status='provisional')
    products={r['instrument_id']:r['product_evidence'] for r in selected['ETF_candidate_rows']}
    master=[]
    for sid in selected['selected_instruments']:
        product=products[sid];original=product['original'];bind(product['source_path'],product['source_sha256'])
        available=max(product['available_at'],product.get('index_contract_available_at',product['available_at']))
        master.append(dict(provenance('Original listing and dated index contract',product['source_url'],product['source_sha256'],original['receipt']['ingested_at'],sid+':M8_identity',product['published_at'],available),
            instrument_id=sid,asset_type='ETF',board='ETF',listed_on=product['listed_on'],delisted_on=None,
            effective_from=product['listed_on'],effective_to=None,revision_id=sid+'_M8_original',supersedes_id=None,revision_kind=None,
            benchmark_id=product['exact_index_id'],benchmark_source_available_at=available,
            industry='HISTORICAL_SECTOR_PRODUCT:'+product['exact_index_id'],status='NORMAL',strategy_universe=LIQUID_SCOPE,
            account_verified=True,account_permission_basis='HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT',actual_broker_permission_observed=False,
            lot_size=100,tick_size=.001,t_plus=1,legal_fund_name=product['legal_fund_name'],historical_metadata_verified=True,
            source_url=product['source_url'],trading_attribute_basis='ORIGINAL_ORDINARY_DOMESTIC_ETF_AND_DATED_EXCHANGE_RULES',
            tracking_index_display_name=product['exact_index_name_original']))
    supplemental=json.loads((REPORT/'HOLDING_SUPPLEMENTAL_DOCUMENTS.json').read_bytes());bind(REPORT/'HOLDING_SUPPLEMENTAL_DOCUMENTS.json')
    rename=next(r for r in supplemental if r['publication_date']=='2020-06-11');bind(rename['receipt']['raw_path'],rename['receipt']['sha256'])
    first=next(r for r in master if r['instrument_id']=='sh.512760')
    updated=dict(first,**provenance('Issuer index/fund name-only change',rename['source_url'],rename['receipt']['sha256'],rename['receipt']['ingested_at'],'sh.512760:20200616rename','2020-06-11',date_only_available_at('2020-06-11',sessions)))
    updated.update(effective_from='2020-06-16',revision_id='sh.512760_M8_20200616_NAME',supersedes_id=first['revision_id'],revision_kind='TRANSITION',
                   legal_fund_name='国泰CES半导体芯片行业交易型开放式指数证券投资基金',tracking_index_display_name='中华交易服务半导体芯片行业指数',
                   transition_reason='ISSUER_EXPLICIT_INDEX_NAME_CHANGE_ECONOMIC_ID_PRESERVED')
    master.append(updated)
    action_policy=dict(base_policy,action_overrides=events['action_overrides'],license_profile_id=license_id)
    action_rows=normalize_actions(events,action_policy,now)
    actions=pd.DataFrame(action_rows)
    for col in REQUIRED['actions']+PROVENANCE_COLUMNS:
        if col not in actions:actions[col]=None
    bars=[];blockers=[]
    for sid in selected['selected_instruments']:
        path=OUT/'decoded'/('holding_'+sid+'.json');digest=bind(path);payload=json.loads(path.read_bytes())
        if payload.get('reused_source_path'):bind(payload['reused_source_path'],payload['reused_source_sha256'])
        raw_rows=[]
        for values in payload['rows']:
            source=dict(zip(payload['fields'],values));day=source['date']
            row=provenance('BaoStock raw adjustflag=3','query_history_k_data_plus',digest,payload['ingested_at'],sid+':'+day,None,day+'T21:00:00+08:00','reconstructed_market_close')
            row.update(instrument_id=sid,date=day,**{k:float(source[k]) for k in ['open','high','low','close','preclose','amount']},volume=int(source['volume']),
                suspended=source['tradestatus']=='0',source_trade_status=source['tradestatus'],revision_id=digest[:16]+':'+day,supersedes_id=None,
                usage_scope='FULL_STRATEGY',market_event_at=day+'T15:00:00+08:00',
                availability_reconstruction=base_policy['market_availability']['reconstruction_basis'],availability_evidence_url=base_policy['market_availability']['source_url'])
            row.update(historical_limits(row,products[sid]['exact_index_id'],policy['historical_rules']))
            raw_rows.append(row)
        years={int(r['date'][:4]) for r in raw_rows}
        missing=_coverage_complete(events,sid,years)
        if missing:raise ValueError('Action coverage incomplete '+sid+str(missing))
        frame,issues=reconstruct_total_return(pd.DataFrame(raw_rows),actions.loc[actions.instrument_id.eq(sid)],start='2019-01-01')
        blockers+=issues;bars.append(frame)
    prior=ROOT/'data/admitted_r1/phase2_v1/validation';prior_manifest=json.loads((prior/'manifest.json').read_bytes())
    bind(prior/'benchmark.json',prior_manifest['file_sha256']['benchmark.json']);b=json.loads((prior/'benchmark.json').read_bytes())
    benchmark=pd.DataFrame(b['records'],columns=b['columns']);benchmark['quality_status']='provisional'
    benchmark_root=ROOT/'data/normalized_csi/h00300_2010_2024_v1';bm=json.loads((benchmark_root/'manifest.json').read_bytes());bind(benchmark_root/'manifest.json')
    for path,digest in bm['files'].items():bind(benchmark_root/path,digest)
    cal_evidence=prior_manifest['availability_calendar_evidence'];bind(cal_evidence['raw_path'],cal_evidence['sha256'])
    manifest=dict(schema_version='r1-offline-1.2',dataset_id='real-m8-historical-liquid',dataset_version='stage-v1',research_scope=LIQUID_SCOPE,
        data_origin='REAL',synthetic=False,timezone='Asia/Shanghai',units=dict(volume='shares_or_fund_units',amount='CNY',price='CNY'),
        calendar_kind='VERIFIED_EXCHANGE_CALENDAR',availability_calendar=prior_manifest['availability_calendar'],availability_calendar_evidence=cal_evidence,
        account_start='2020-01-01',market_history_start='2019-01-01',tr_coverage_start='2019-01-01',signal_release_delay=1,
        coverage_start=sessions[0],coverage_end=sessions[-1],build_blockers=blockers,strategy_runs_permitted=False,status='STAGED_PENDING_INDEPENDENT_REVIEW',
        availability_mode='historical_public_asof',license_profile_id=license_id,source_snapshot_hashes=snapshots,
        evidence_gates={gate:dict(status='PENDING_INDEPENDENT_REVIEW') for gate in EVIDENCE_GATES},performance_evidence=False,
        required_full_history_instruments=sorted(selected['selected_instruments']),action_coverage_scope='ALL_SELECTED_COMPETITORS_FULL_2019_2024',
        actual_broker_permissions_observed=False,cohort_selection=selected,cohort_selection_sha256=selection_sha,
        build_policy=dict(policy,action_overrides=events['action_overrides']),event_manifest_path='reports/m8_rotation/EVENT_MANIFEST.json',
        cost_scenario=policy['cost_scenario'],scope_limitations=['Historical public-asof reconstruction, not vendor vintage',
            'Finite archived sector/theme products with economic overlap; not independent industries',
            'Modeled designated-account dividend credits, not observed private broker settlement',
            'Secondary raw OHLC complete on traded sessions; secondary amount not provided; unsolicited quotes quarantined'])
    dataset=Dataset(sessions,pd.DataFrame(master),pd.concat(bars,ignore_index=True),actions,benchmark,manifest)
    manifest['liquid_dependencies']=liquid_dependencies(dataset)
    audit=audit_dataset(dataset);save(REPORT/'STAGE_AUDIT.json',audit)
    if audit['errors']:raise ValueError(str(audit['errors']))
    save_dataset(dataset,STAGE)
    save(REPORT/'DATASET_STAGE_RECEIPT.json',dict(path=str(STAGE),manifest_sha256=sha(STAGE/'manifest.json'),counts=dict(bars=len(dataset.bars),actions=len(actions),master=len(master),benchmark=len(benchmark)),errors=audit['errors'],blockers=audit['blockers']))
    print(json.dumps(dict(stage=str(STAGE),bars=len(dataset.bars),actions=len(actions),errors=audit['errors'],blockers=audit['blockers'])))

if __name__=='__main__':main()
