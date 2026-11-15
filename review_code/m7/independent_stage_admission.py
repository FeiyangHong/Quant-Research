"""Admit only the proved all-cash M7 path, never general seven-ETF trading."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from quant_research.data import EVIDENCE_GATES, audit_dataset, load_dataset
from quant_research.cohort import cohort_dependencies

ROOT=Path(__file__).resolve().parents[2]
STAGE=ROOT/'data/m7_fixed_cohort/stage_v1'


def read(path):return json.loads(Path(path).read_bytes())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ds=load_dataset(STAGE,allow_unverified=True)
    manifest=ds.manifest
    for path,expected in manifest['source_snapshot_hashes'].items():
        assert sha(ROOT/path)==expected,path
    for path,expected in manifest['file_sha256'].items():assert sha(STAGE/path)==expected
    raw=read(ROOT/'reports/m7_review/independent_raw_probe.json')
    assert manifest['synthetic'] is False and manifest['data_origin']=='REAL'
    assert ds.calendar==sorted(set(read(ROOT/'data/admitted_r1/phase2_v1/development/calendar.json')+
                                  read(ROOT/'data/admitted_r1/phase2_v1/validation/calendar.json')))
    for sid in raw['raw_coverage']:
        decoded=read(ROOT/('data/raw_m7/decoded/history_'+sid+'.json'))
        rows=[dict(zip(decoded['fields'],r)) for r in decoded['rows']]
        actual=ds.bars.loc[ds.bars.instrument_id.eq(sid)].sort_values('date').to_dict('records')
        assert len(actual)==len(rows)
        for a,e in zip(actual,rows):
            assert a['date']==e['date']
            assert Decimal(str(a['amount']))==Decimal(e['amount'])
            assert a['volume']==int(e['volume']) and a['suspended']==(e['tradestatus']=='0')
            assert a['usage_scope']=='COHORT_ELIGIBILITY_ONLY'
        original=ds.instruments.loc[ds.instruments.instrument_id.eq(sid)].iloc[0]
        assert original['listed_on']==raw['listing_dates_hand_read_from_original_PDF_page1'][sid]
        assert original['account_permission_basis']=='HYPOTHETICAL_ORDINARY_DOMESTIC_EQUITY_ETF_ACCOUNT'
        assert original['actual_broker_permission_observed']==False
    # Complete official title pagination, distinct rows and source security IDs.
    receipts=read(ROOT/'reports/m7_cohort/request_log.json')
    title_counts={}
    for sid in raw['raw_coverage']:
        pages=[r['receipt'] for r in receipts if r['label'].startswith('titles_'+sid+'_')]
        records=[];total=None
        for receipt in pages:
            assert sha(receipt['raw_path'])==receipt['sha256']
            page=read(receipt['raw_path'])
            if total is not None:assert total==page['announceCount']
            total=page['announceCount'];records.extend(page['data'])
        assert len(records)==total==len({r['id'] for r in records})
        assert all(sid[3:] in r['secCode'] and r['publishTime'][:10]<='2024-12-31' for r in records)
        title_counts[sid]=total
    dependency=cohort_dependencies(ds)
    assert dependency==manifest['cohort_dependencies']
    assert dependency['required_full_history_instruments']==[]
    assert set(dependency['no_ranking_or_holding_dependency'])==set(raw['raw_coverage'])
    legal=[r for r in dependency['schedule'] if r['eligible_count'] is not None]
    assert len(legal)==107
    for row,expected in zip(legal,raw['months']):
        assert row['anchor_date']==expected['anchor']
        assert row['eligible_count']<=expected['N_upper_bound']<3
    audit=audit_dataset(ds)
    assert not audit['errors']
    expected_blockers={'manifest: staging snapshot has not been admitted for research'}
    expected_blockers.update(key+': non-accepted records present' for key in ('instruments','bars','benchmark'))
    expected_blockers.update('evidence: '+key+' unverified' for key in EVIDENCE_GATES)
    assert set(audit['blockers'])==expected_blockers,audit['blockers']
    limitations=[
        'Admission covers only32 registered all-cash paths starting with100000 and no positions; every legal decision has a raw liquidity/age upper bound below3.',
        'Hypothetical ordinary domesticETF permissions are a stated research model, not observed personal broker permissions. Exact eligible counts have that model qualification.',
        'No ETF TR, full action chain, liquidation cash timing, execution price, legal fee, or dual-source price completeness is certified. Those are unreachable under this hash-bound no-position dependency proof.',
        'Empty actions is not a claim of no events:159938 has1:2 split in2022 and159946 terminates in2018; their account entitlements are zero by input proof.',
        'All seven raw histories retained;159946847 lifetime sessions and zero eligible months independently proved. No current-survivor deletion or zero-recovery assumption.',
        'Market-asof timing is the registered reconstructed close clock, not a vendor historical vintage guarantee.32 sub-one-yuan small-trade discrepancies retained; classification invariant under±1yuan.',
        'Official source identity and calendar checks supplement one vendor amount history. The dual-source gate does not certify a second independent full market-price series.',
        'Private local noncommercial source storage only; this review grants no redistribution or future live-trading permission.',
        'If any snapshot, source, qualification, starting holding, or threshold changes, this attestation does not authorize a new holding dependency.'
    ]
    now=datetime.now(timezone.utc).isoformat();reviewer='M7 independent reviewer agent /root/m7_independent (not human signoff)'
    report=dict(status='PASS_SCOPED_NO_HOLDING_DEPENDENCY',reviewer=reviewer,reviewed_at=now,
                stage_manifest_sha256=sha(STAGE/'manifest.json'),source_files_checked=len(manifest['source_snapshot_hashes']),
                table_files_checked=len(manifest['file_sha256']),raw_rows=len(ds.bars),title_counts=title_counts,
                legal_decisions=107,model_qualified_N_distribution=dict(Counter(r['eligible_count'] for r in legal)),
                full_history_dependencies=[],audit_errors=audit['errors'],pre_admission_blockers=audit['blockers'],
                qualifications=limitations)
    report_path=ROOT/'reports/m7_review/independent_stage_review.json'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    references=['reports/m7_review/independent_raw_probe.json','reports/m7_review/independent_document_probe.json',
                'reports/m7_review/independent_stage_review.json','docs/M7_PLAN.md',
                'reports/m7_cohort/identity_evidence.json','reports/m7_cohort/state_documents.json',
                'review_code/m7/test_independent_cohort.py']
    gates={key:dict(status='VERIFIED',reviewer=reviewer,reviewed_at=now,evidence=references,
                    scope='ONLY_REACHABLE_ALL_CASH_DEPENDENCIES; see qualifications; not full trading-source certification')
           for key in EVIDENCE_GATES}
    attestation=dict(schema_version=1,decision='ADMIT_DAILY_SCREEN',research_scope='R1I_FIXED_COHORT_V1',
                     reviewer=reviewer,reviewed_at=now,stage_manifest_sha256=sha(STAGE/'manifest.json'),
                     qualifications=limitations,evidence_gates=gates,evidence_files={p:sha(ROOT/p) for p in references},
                     reachable_account_scope='ALL_CASH_ONLY_N_UPPER_BOUND_LT3',actual_broker_permission_verified=False,
                     full_TR_action_execution_price_coverage_verified=False)
    target=ROOT/'reports/m7_review/independent_admission_attestation.json'
    target.write_text(json.dumps(attestation,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','source_files_checked','table_files_checked','raw_rows','title_counts','model_qualified_N_distribution')}))


if __name__=='__main__':main()
