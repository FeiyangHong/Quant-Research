"""Offline five-case share-scope audit. Never emits a size percentile or signal."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.budget import atomic_json
from m4_data_feasibility import date_only_clock
from m5_sources import reuse

OUT=ROOT/'reports/m5_market_cap'
SNAPSHOT='2020-07-31'
CASES={
 'sh.600519':dict(total=1256197800,a=1256197800,h=0,pages=[2,5,34],published='2020-04-22',economic_asof='2019-12-31',unit='125619.78 ten-thousand shares, explicitly labelled 万股 on PDF page 2',effective_from=None),
 'sz.002526':dict(total=1782793836,a=1782793836,h=0,pages=[1],published='2020-05-26',economic_asof='2020-05-26',unit='shares',effective_from=None),
 'sh.601398':dict(total=356406257089,a=269612212539,h=86794044550,pages=[89],published='2020-04-25',economic_asof='2019-12-31',unit='ordinary shares; preference shares excluded',effective_from=None),
 'sh.600518':dict(total=4973861675,a=4973861675,h=0,pages=[69,70],published='2020-06-18',economic_asof='2019-12-31',unit='ordinary shares; preference shares excluded',effective_from=None),
 'sz.300855':dict(total=200000000,a=200000000,h=0,pages=[28,29],published='2020-07-22',economic_asof='2020-07-23',unit='20000 ten-thousand shares; table confirms 200000000 shares',effective_from='2020-07-23'),
}


def select_vendor_candidate(records, snapshot=SNAPSHOT):
    """Provider-date screening only; these labels do not certify original public dates."""
    eligible=[];rejected=[]
    for row in records:
        end=(row.get('END_DATE') or '')[:10]
        notice=(row.get('NOTICE_DATE') or '')[:10]
        reason=None
        if not end or end>snapshot:reason='MISSING_OR_FUTURE_ECONOMIC_DATE'
        elif not notice:reason='UNKNOWN_PROVIDER_NOTICE_DATE'
        elif notice>=snapshot:reason='PROVIDER_NOTICE_NOT_VISIBLE_DATE_ONLY'
        if reason:rejected.append(dict(row=row,reason=reason))
        else:eligible.append(row)
    eligible.sort(key=lambda r:(r['END_DATE'],r['NOTICE_DATE']),reverse=True)
    if not eligible:return None,rejected
    latest=eligible[0]
    same=[r for r in eligible if (r['END_DATE'],r['NOTICE_DATE'])==(latest['END_DATE'],latest['NOTICE_DATE'])]
    if len({(r.get('TOTAL_SHARES'),r.get('TOTAL_A_SHARES')) for r in same})>1:
        raise ValueError('Conflicting same-date capital records')
    return latest,rejected


def valuation_diagnostics(price, all_ordinary, a_only, *, h_shares=0):
    values=[Decimal(str(x)) for x in (price,all_ordinary,a_only,h_shares)]
    if any(not x.is_finite() for x in values) or min(values[:3])<=0 or values[3]<0:
        raise ValueError('Finite positive price/share counts required')
    if values[2]+values[3]!=values[1]:raise ValueError('Share classes must reconcile')
    return dict(a_price_times_all_ordinary_cny=str(values[0]*values[1]),
                a_share_only_value_cny=str(values[0]*values[2]),
                per_class_aggregate_market_value_cny=None,
                per_class_value_gap='H price and contemporaneous FX absent' if h_shares else 'Not computed as a separately certified valuation object',
                convention='A_PRICE_TIMES_ALL_ORDINARY_IS_NOT_A_PER_CLASS_SUM')


def build():
    pool_path=ROOT/'reports/m4_data/full_pool_2020-07-31.json'
    pool=json.loads(pool_path.read_text(encoding='utf8'))['rows']
    if len(pool)!=3779 or len({r['instrument_id'] for r in pool})!=3779:
        raise ValueError('Fixed original denominator changed')
    ledger=json.loads((ROOT/'data/raw_m5_equity/budget.json').read_text(encoding='utf8'))
    attempts=[r for r in ledger['attempts'] if r.get('scope')=='market_cap']
    sources={r['label']:r for r in attempts}
    for source in attempts:
        if not source.get('terminal'):raise ValueError('Incomplete collection attempt')
        reuse(source['raw_path'],expected_sha256=source['sha256'])
    calendar_path=ROOT/'data/admitted_r1/phase2_v1/development/calendar.json'
    cal=json.loads(calendar_path.read_text(encoding='utf8'))
    days=cal['trading_dates'] if isinstance(cal,dict) else cal
    cases=[]
    for instrument,fact in CASES.items():
        code=instrument[3:]
        member=next(r for r in pool if r['instrument_id']==instrument)
        vendor=sources['market_eastmoney_'+code+'_20200731']
        response=json.loads(Path(vendor['raw_path']).read_bytes())
        result=response.get('result') or {}
        if not response.get('success') or result.get('pages')!=1:
            raise ValueError('Vendor response/pagination incomplete for fixed case')
        records=result.get('data') or []
        if any(r.get('SECURITY_CODE')!=code for r in records):raise ValueError('Issuer filter failed')
        chosen,rejected=select_vendor_candidate(records)
        pdf=sources['market_pdf_'+code]
        total_match=chosen and chosen.get('TOTAL_SHARES')==fact['total']
        a_match=chosen and chosen.get('TOTAL_A_SHARES')==fact['a']
        cases.append(dict(instrument_id=instrument,snapshot_date=SNAPSHOT,
            original_document_fact=fact|date_only_clock(fact['published'],days),
            document_source=pdf,publication_metadata_source=sources['market_search_'+code],provider_source=vendor,provider_candidate=chosen,
            provider_screen_rejections=rejected,provider_original_notice_semantics_verified=False,
            ordinary_share_count_matches_document=bool(total_match),a_share_count_matches_document=bool(a_match),
            raw_A_close=member['raw_ohlcv']['close'],price_origin='REUSED_M4_RAW_UNADJUSTED_SNAPSHOT',
            diagnostic_values=valuation_diagnostics(member['raw_ohlcv']['close'],fact['total'],fact['a'],h_shares=fact['h']),
            economic_effective_date_note='Annual report balance date does not prove exact share-change effective_from; IPO listing date is separately evidenced',
            full_event_chain_through_snapshot_verified=False,formal_PIT_market_cap=None,
            status=('DOCUMENT_VALUE_CROSSCHECK_PASS_FORMAL_SNAPSHOT_PARTIAL'
                    if total_match and a_match else 'SOURCE_CONFLICT_FORMAL_SNAPSHOT_BLOCKED'),
            missing=['Complete capital/cancellation event chain from documentary observation to snapshot',
                     'Independent provider NOTICE_DATE publication precision and revision-chain contract',
                     'Historical whole-pool non-ST denominator remains incomplete'],
            agent_document_verification=True,human_signoff=False))
    normalized=[]
    by_id={c['instrument_id']:c for c in cases}
    for row in pool:
        case=by_id.get(row['instrument_id'])
        normalized.append(dict(instrument_id=row['instrument_id'],snapshot_date=SNAPSHOT,
            diagnostic_total_ordinary_shares=case['original_document_fact']['total'] if case else None,
            diagnostic_A_price_times_all_ordinary_cny=case['diagnostic_values']['a_price_times_all_ordinary_cny'] if case else None,
            formal_PIT_market_cap=None,size_percentile=None,bottom_30_percent=None,
            status=('SAMPLED_DOCUMENT_CROSSCHECK_ONLY'
                    if case['ordinary_share_count_matches_document'] and case['a_share_count_matches_document']
                    else 'SOURCE_CONFLICT_FORMAL_SNAPSHOT_BLOCKED')
                   if case else 'UNMEASURED_FIXED_DENOMINATOR_RETAINED'))
    report=dict(snapshot_date=SNAPSHOT,diagnostic_denominator=3779,structural_sample_count=5,
        vendor_share_values_observed=5,original_document_value_crosschecks=sum(
            c['ordinary_share_count_matches_document'] and c['a_share_count_matches_document'] for c in cases),
        diagnostic_observed_percent=100*5/3779,full_PIT_capital_chain_admitted=0,
        complete_nonST_denominator=None,whole_market_size_percentiles_computed=False,
        new_http_attempts=len(attempts),new_baostock_wire_attempts=0,
        new_response_bytes=sum(a['byte_count'] for a in attempts),
        request_elapsed_seconds=sum(a['elapsed_seconds'] for a in attempts),
        failed_attempts=sum(a['status']=='FAILED' for a in attempts),
        whole_pool_network_expansion='NOT_RUN_SEMANTIC_GATE_NOT_PASSED',
        r2_status='BLOCKED_ADMISSION',r3_status='BLOCKED_ADMISSION',alpha_runs=0,
        cases=cases,provenance=[reuse(pool_path),reuse(calendar_path)],
        reproducible_without_network=True,source_data_origin='REAL_PUBLIC_SOURCE_AND_PROVIDER_HISTORY',
        purpose='ENGINEERING_SNAPSHOT_NOT_STRATEGY_PERFORMANCE')
    atomic_json(OUT/'coverage_summary.json',report)
    atomic_json(OUT/'full_pool_market_cap_2020-07-31.json',dict(rows=normalized))
    atomic_json(OUT/'source_manifest.json',attempts)
    share_events=[]
    for label,public,signed,effective,before,after in [
        ('annual','2018-05-19','2018-05-18','2018-05-28',616883681,1048702257),
        ('interim','2018-09-13','2018-09-13','2018-09-20',1048702257,1782793836)]:
        share_events.append(dict(instrument_id='sz.002526',event_type='CAPITAL_RESERVE_CONVERSION',
            publication_date=public,signature_date=signed,publication_precision='date_only',
            effective_from=effective,source=sources['market_002526_2018_'+label],
            publication_metadata_source=sources['market_002526_2018_capital_query'],
            source_pdf_pages=[1,2],unit='shares',before_shares=before,after_shares=after,
            ratio='7 new shares per 10 old shares',
            rounding_rule='Issuer integer total directly disclosed; do not replace with fractional multiplication',
            agent_visual_check=True,human_signoff=False,**date_only_clock(public,days)))
    atomic_json(OUT/'share_change_events.json',share_events)
    atomic_json(OUT/'code_manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),ROOT/'scripts/m5_sources.py',ROOT/'src/quant_research/budget.py',ROOT/'scripts/m4_data_feasibility.py']})
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','provenance')},ensure_ascii=True))


if __name__=='__main__':build()
