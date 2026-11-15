import json,hashlib,sys,collections
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.baostock import canonical,utc_now,write_immutable
from quant_research.providers.equity_audit import inspect_records
from quant_research.data import date_only_available_at
OUT=ROOT/'data/raw_equity_admission'; REPORT=ROOT/'reports/m3_equity_admission'
REPORT.mkdir(parents=True,exist_ok=True)
raw=[(p,json.loads(p.read_bytes())) for p in sorted((OUT/'raw').glob('*.json'))]
for p,r in raw:
    if r['status']=='SUCCESS':inspect_records(r['query'],r['fields'],r['rows'])
http=[json.loads(p.read_bytes()) for p in sorted((OUT/'http_manifests').glob('*.json'))]
docs={r['id']:r for r in http}
def evidence(label):
    d=docs[label]
    return {k:d.get(k) for k in ['id','url','raw_path','sha256','requested_at','ingested_at','role']}
def get(kind,code=None):
    return [r for p,r in raw if r['query']['kind']==kind and (code is None or r['query'].get('code')==code)]
calendar=[]
for p in (OUT/'calendars/raw').glob('*.json'):
    r=json.loads(p.read_bytes());calendar.extend(row[0] for row in r['rows'] if row[1]=='1')
calendar=sorted(set(calendar))
original_available=date_only_available_at('2018-04-26',calendar)
revision_available=date_only_available_at('2019-04-30',calendar)
case=dict(case_id='KANGMEI_2017_ORIGINAL_TO_2019_RESTATEMENT',instrument_id='sh.600518',period_end='2017-12-31',
          report_scope='consolidated; net profit attributable to parent',publication_precision='date_only',
          availability_mode='historical_public_asof',vendor_first_seen_at=None,
          original=dict(revision_id='KM2017_AS_PUBLISHED_20180426',supersedes_id=None,published_date='2018-04-26',available_at=original_available,
                        earliest_execution='2018-05-02',document=evidence('kangmei_original_2017'),pages=[6,7],
                        values=dict(net_profit_parent='4100926148.57',operating_cash_flow='1842794237.84',total_assets='68722020630.61')),
          revision=dict(revision_id='KM2017_RESTATED_20190430',supersedes_id='KM2017_AS_PUBLISHED_20180426',published_date='2019-04-30',available_at=revision_available,
                        earliest_execution='2019-05-07',document=evidence('kangmei_2018_first'),pages=[6],
                        supporting_correction_document=evidence('kangmei_revision_2019'),
                        values=dict(net_profit_parent='2149836281.41',operating_cash_flow='-4840052606.46',total_assets='65292951329.52')),
          validation=dict(original_and_comparative_values_crosschecked=True,original_pdf_page6_render_viewed=True,
                          comparative_pdf_page6_render_viewed=True,scanned_correction_pdf_pages5_6_render_viewed=True,
                          calendar_api_verified=True,exact_intraday_time_verified=False,independent_human_signoff=False),
          gate_count=1,limitation='One issuer-period revision case, not three cases for three fields; agent documentary reconciliation is not independent human signoff.')
write_immutable(REPORT/'financial_vintage_case.json',case)
queue=json.loads((OUT/'revision_candidate_queue_v3.json').read_bytes())
write_immutable(REPORT/'revision_candidate_queue.json',queue)
findings=[]
for r in get('history'):
    rr=[dict(zip(r['fields'],v)) for v in r['rows']]
    findings.append(dict(query=r['query'],row_count=len(rr),first_date=rr[0]['date'],last_date=rr[-1]['date'],
                         trade_status_counts=dict(collections.Counter(x['tradestatus'] for x in rr)),
                         st_counts=dict(collections.Counter(x['isST'] for x in rr)),last_rows=rr[-2:]))
universe=[]
for r in get('universe'):
    if r['status']!='SUCCESS':continue
    rows=[dict(zip(r['fields'],x)) for x in r['rows']]
    # Board-prefix diagnostic only, not an instrument-master acceptance rule.
    relevant=[x for x in rows if x['code'].startswith(('sh.600','sh.601','sh.603','sh.605','sz.000','sz.001','sz.002','sz.003','sz.300','sz.301'))]
    universe.append(dict(day=r['query']['day'],all_securities_count=len(rows),provisional_main_chinext_prefix_count=len(relevant),
                         hard_cases=[x for x in rows if x['code'] in ('sz.000979','sz.300104')]))
industry=[dict(query=r['query'],records=[dict(zip(r['fields'],x)) for x in r['rows']]) for r in get('industry')]
dividend=[dict(query=r['query'],records=[dict(zip(r['fields'],x)) for x in r['rows']]) for r in get('dividend')]
write_immutable(REPORT/'hard_case_findings.json',dict(histories=findings,universes=universe,industry=industry,dividends=dividend))
actions=[dict(instrument_id='sh.600519',action_id='600519_2023-021',action_type='CASH_DIVIDEND',published_date='2023-06-26',
              record_date='2023-06-29',ex_date='2023-06-30',pay_date='2023-06-30',cash_per_share_gross='25.911',
              total_shares_before='1256197800',source=evidence('maotai_dividend_20230626'),sdk_crosscheck='MATCHED_DATES_AND_GROSS_AMOUNT',
              tax_class='DOMESTIC_NATURAL_PERSON_ORDINARY_MARKET_ACQUIRED_A_SHARES',tax_note='Gross payment initially; individual FIFO holding-period tax on transfer; no universal provider after-tax amount'),
         dict(instrument_id='sh.600519',action_id='600519_2023-040',action_type='CASH_DIVIDEND',published_date='2023-12-14',
              record_date='2023-12-19',ex_date='2023-12-20',pay_date='2023-12-20',cash_per_share_gross='19.106',
              total_shares_before='1256197800',source=evidence('maotai_special_original_20231214'),sdk_crosscheck='ABSENT_IN_QUERY_DIVIDEND_OPERATE_2023',
              tax_class='DOMESTIC_NATURAL_PERSON_ORDINARY_MARKET_ACQUIRED_A_SHARES',tax_note='Gross payment initially; FIFO deferred tax')]
write_immutable(REPORT/'corporate_action_cases.json',dict(status='DOCUMENTARY_AUDIT_NOT_RUNNER_DATASET',events=actions,
               missing=['full-universe event coverage','holder lot history','event-specific available_at through validated full calendar','all non-cash tax-source classifications','delisting cash recoveries']))
matrix=[
 dict(dataset='historical_universe_including_delisted',R2='PARTIAL_PENDING_COLLECTION',R3='PARTIAL_PENDING_COLLECTION',
      observed='Four dated all-security snapshots include Zhonghong/Leshi before exit; current code_name leaks later name.',
      missing=['daily membership completeness','immutable security identity and historical board/IPO/exit effective intervals','official independent delisted inventory reconciliation'],
      next_free='Collect dated universe and official listing/termination documents; never filter historical status with returned current names.'),
 dict(dataset='daily_status_and_trading_restrictions',R2='BLOCKED_INCOMPLETE_STATUS',R3='BLOCKED_INCOMPLETE_STATUS',
      observed='Kangmei ST transition and suspension present. Leshi delisting liquidation has isST=0. Zhonghong quote placeholder persists on delisting day.',
      missing=['separate ST versus delisting-risk versus liquidation/suspension intervals','historical board/IPO-specific limits and official reference prices'],
      next_free='Rebuild announcement event ledger; overlay rules and exclude new orders without deleting existing claims.'),
 dict(dataset='historical_industry',R2='PARTIAL_PUBLIC_RECONSTRUCTION',R3='PARTIAL_PUBLIC_RECONSTRUCTION',
      observed='CSRC Q2 2020 original and July 14 publication found; Shijia July 17 change C33 to C39 matches July 13/20 SDK transition.',
      missing=['complete system/version/issuer membership histories','public availability distinct from quarter-end and provider updateDate','2022-2024 complete original announcement coverage'],
      next_free='Archive official quarterly CSRC/CAPCO lists plus change notices; version taxonomies and preserve publication delays; extend weekly SDK audit.'),
 dict(dataset='historical_share_count_market_cap_liquidity',R2='BLOCKED_UNVERIFIED_SHARES',R3='BLOCKED_UNVERIFIED_SHARES',
      observed='Raw volume/amount/turn and quarterly totalShare/liqaShare available; these do not establish daily total/float shares.',
      missing=['shares effective dates','known_at for issuance/cancellation/vesting/restructuring','daily all-pool market-cap ranks and rolling liquidity coverage'],
      next_free='Rebuild original annual/interim share tables and every capital-change event; check shares/turn only as diagnostic, not authoritative total cap.'),
 dict(dataset='corporate_actions_total_return_delisting_claims',R2='BLOCKED_INCOMPLETE_LEDGER',R3='BLOCKED_INCOMPLETE_LEDGER',
      observed='Maotai ordinary 25.911 verified; 19.106 special missing from SDK operate-year query but official original is available. Leshi 2017 capital transfer present in SDK.',
      missing=['complete cash and noncash events','source of capital reserve','rights/merger mapping and recoveries','record/ex/pay dates and lot tax for all holdings'],
      next_free='Official distributions and reorganization notices supplement SDK; zero-mark unknown delisted value while retaining legal claims, never assume cash recovery.'),
 dict(dataset='financial_raw_vintages',R2='BLOCKED_1_OF_20_CASES_AND_NO_FULL_POOL',R3='NOT_REQUIRED_F01_F06',
      observed='One fully documented original-to-restated issuer-period case; 20 separate correction-event PDFs queued, not original-paired. SDK single row cannot address revisions; balance/cashflow are ratios, not raw statements.',
      missing=['20 independently reviewed original/correction/availability cases','full required issuer-period original net profit parent/assets/CFO','revision chain and input revision ids for TTM','verified public clock'],
      next_free='CNInfo bounded date-query works; pair each original filing and correction, extract units/scope and preserve all versions; use historical_public_asof with conservative next-trading-day 21:00.'),
 dict(dataset='fees_and_tax',R2='BLOCKED_UNVERIFIED_EXECUTION_INPUTS',R3='BLOCKED_UNVERIFIED_EXECUTION_INPUTS',
      observed='Official Maotai distribution states deferred holding-period tax; parallel execution audit archives historical rule sources.',
      missing=['account commission profile and fee aggregation basis','complete exchange/transfer/stamp-fee effective intervals','stock tax and claims ledger accepted by main runner'],
      next_free='Use official MOF/SSE/SZSE/CSDC rules and broker fee schedule; four capital tiers share same policy, 100000 CNY main. Do not reuse R1 ETF tax exemptions.'),
]
summary=dict(schema_version='m3-equity-source-audit-1.0',created_at=utc_now(),R2_admission='BLOCKED',R3_admission='BLOCKED',
             no_performance_evidence=True,final_holdout_locked=True,requested_through='2024-12-31',
             retrospective_document_role='QUALITY_AUDIT_ONLY_NOT_ASOF_SIGNAL_OR_UNIVERSE_SELECTION',
             sdk_probe_count=len(raw),sdk_status_counts=dict(collections.Counter(r['status'] for p,r in raw)),
             calendar_probe_count=2,http_request_count=len(http),http_status_counts=dict(collections.Counter(r['status'] for r in http)),
             official_correction_documents_in_queue=len(queue['cases']),original_vintage_reconciliation_case_count=1,
             independently_human_signed_cases=0,required_handoff_cases=20,matrix=matrix,
             license=dict(BaoStock='Official current home documents free API and local storage for research; no broad redistribution/commercial sublicensing inferred.',
                          official_documents='Public source originals locally retained for individual verification; redistribution rights not inferred.',
                          Eastmoney='HTTP samples failed; undocumented endpoint access is not a data license; not admitted.'),
             conditional_paid_fallback='Only if free official reconstruction cannot meet dated coverage: request field-level sample/rights quote for immutable financial revisions, industry membership history, daily shares, delisted claims. No purchase, no invented price.')
write_immutable(REPORT/'data_audit.json',summary)
objects=[]
for p in sorted(OUT.rglob('*')):
    if p.is_file():objects.append(dict(path=p.relative_to(ROOT).as_posix(),byte_count=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
source_manifest=dict(schema_version='m3-equity-sources-1.0',raw_root='data/raw_equity_admission',
                     objects=objects,http_requests=http,immutable_append_only=True,
                     sealed_R1_files_modified=False,source_timestamp_policy='ingested_at is actual current capture; never historical first seen; date-only documents conservatively delayed',
                     sdk_snapshot_format='Decoded SDK response and diagnostics; not original TCP wire bytes',
                     sdk_calls=sum(1 for _ in raw)+2,
                     code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'scripts/audit_equity_sources.py',ROOT/'src/quant_research/providers/equity_audit.py',ROOT/'tests/test_equity_data_audit.py']})
write_immutable(REPORT/'source_manifest.json',source_manifest)
print(json.dumps({k:v for k,v in summary.items() if k.endswith('count') or k.endswith('counts') or k.endswith('admission')},ensure_ascii=False))
