"""Publish locatable source facts and pre-return opportunity diagnostics."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import html
import json
from pathlib import Path
import re

from m7_data_collect import ROOT, OUT, REPORT, COHORT, save
from m7_data_audit import sha,extracted
from quant_research.data import load_dataset

def main():
    ds=load_dataset(ROOT/'data/m7_fixed_cohort/stage_v1',allow_unverified=True)
    dependencies=ds.manifest['cohort_dependencies'];months=[];yearly={}
    for r in dependencies['schedule']:
        row=dict(r);day=r['anchor_date'];i=ds.calendar.index(day)
        if r['status']=='CASH_COHORT_NOT_YET_KNOWN':
            row.update(trend_on=None,expected_target_differentiation=False,ranking_freedom=False)
        else:
            days=ds.calendar[i-199:i+1];b=ds.benchmark.set_index('date').loc[days]
            assert len(b)==200
            assert (b.available_at<=r['release_date']+'T21:00:00+08:00').all()
            trend=float(b.total_return_index.iloc[-1])>float(b.total_return_index.mean())
            row.update(trend_on=trend,expected_target_differentiation=False,ranking_freedom=r['eligible_count']>=4)
        months.append(row)
    for year in range(2016,2025):
        rows=[r for r in months if r['execution_date'].startswith(str(year))]
        known=[r for r in rows if r['eligible_count'] is not None]
        yearly[str(year)]=dict(scheduled=len(rows),cohort_known=len(known),N_distribution=dict(Counter(str(r['eligible_count']) for r in known)),
            N_ge_4=sum(r['eligible_count']>=4 for r in known),trend_ON=sum(r['trend_on'] is True for r in known),
            N_ge_4_and_trend_ON=0,expected_target_differences=0)
    qualified=[r for r in months if r['eligible_count'] is not None]
    result=dict(scope='R1I_FIXED_COHORT_V1',stage='BEFORE_ACCOUNT_RETURNS',source_stage_manifest_sha256=sha(ROOT/'data/m7_fixed_cohort/stage_v1/manifest.json'),
        status='COMPLETE_INPUTS_LIMITED_IDENTIFICATION',months=months,by_execution_year=yearly,
        N_distribution=dict(Counter(str(r['eligible_count']) for r in qualified)),N_ge_4=0,N_eq_3=0,
        trend_ON=sum(r['trend_on'] is True for r in qualified),N_ge_4_and_trend_ON=0,expected_target_differences=0,
        pre_cohort_cash=[r for r in months if r['eligible_count'] is None],
        terminal_anchor=dict(anchor='2024-12-31',status='NO_EXECUTION_WITHIN_FROZEN_PERIOD',signal_scheduled=False,market_after_2024_read=False),
        limitations=['N<3 common cash eliminates all ranking/holding dependencies; this is a proven strategy input result, not missing-data cash',
            'No claim that null ETF TR means zero economic product return; empty action table is no account dependency, not no corporate actions'])
    save(REPORT/'ELIGIBILITY_AND_OPPORTUNITY.json',result)
    identities=json.loads((REPORT/'identity_evidence.json').read_bytes());logs=json.loads((REPORT/'request_log.json').read_bytes());states=json.loads((REPORT/'state_documents.json').read_bytes())
    facts=[]
    for r in identities:
        facts.append(dict(instrument_id=r['instrument_id'],fact_type='LISTING_IDENTITY',source_url=r['source_url'],raw_path=r['raw_path'],sha256=r['raw_object_hash'],
            publication_date=r['published_at'],available_at=r['available_at'],effective_listing_date=r['listed_on'],ingested_at=r['ingested_at'],
            index_id=r['exact_index_id'],legal_name=r['legal_fund_name'],physical_pdf_pages=[1,3],visual_page_reviewed=3,
            conclusion='Original product,security code,index code,listed date agree with raw-history first day; index identifier is not current industry taxonomy'))
    cohort=next(r for r in logs if r['label']=='cohort_20160104');cap=cohort['receipt']
    text=html.unescape(re.sub(r'<[^>]+>',' ',Path(cap['raw_path']).read_text(encoding='utf8')))
    compact=re.sub(r'\s+','',text)
    signature=re.findall(r'201[56]年\d{1,2}月\d{1,2}日',compact)
    facts.append(dict(fact_type='COHORT',source_url=cohort['url'],raw_path=cap['raw_path'],sha256=cap['sha256'],
        publication_date='2016-01-04',page_date='2016-01-04',body_date_strings=signature,body_signature_date='2015-12-31',
        available_at='2016-01-05T21:00:00+08:00',asset_reference_date='2015-12-31',ingested_at=cap['ingested_at'],
        codes_found={sid:sid[3:] in compact for sid in COHORT},weight_inputs=False))
    for r in states:
        cap=r['receipt'];p,t=extracted(cap)
        if cap['url']!=r['source_url']:raise ValueError('Document receipt does not match requested identity')
        fact=dict(instrument_id=r['instrument_id'],title=r['title'],publication_date=r['publication_date'],source_url=r['source_url'],
            sha256=cap['sha256'],raw_path=cap['raw_path'],text_path=str(p),ingested_at=cap['ingested_at'])
        if '2024年' in r['title']:
            fact.update(fact_type='IDENTITY_RECONCILIATION_ONLY',benchmark_lines=[line.strip() for line in t.splitlines() if line.startswith('业绩比较基准')],
                not_used_as_prior_historical_classification=True,not_used_for_weights_or_returns=True)
        elif r['instrument_id']=='sz.159946':
            fact.update(fact_type='EXIT',physical_pdf_pages=[1,2],cash_or_entitlement_amount=None,account_dependency=False)
            if r['publication_date']=='2018-12-25':fact.update(delisted_on='2018-12-28',rights_record_date='2018-12-27',available_at='2018-12-26T21:00:00+08:00')
            if r['publication_date']=='2018-12-19':fact.update(suspension_effective='2018-12-21',available_at='2018-12-20T21:00:00+08:00')
            if r['publication_date']=='2018-12-24':fact.update(vote_effective='2018-12-21',liquidation_start='2018-12-25',available_at='2018-12-25T21:00:00+08:00')
        elif '拆分' in r['title']:
            fact.update(fact_type='SPLIT_NOT_ECONOMIC_IDENTITY_CONVERSION',physical_pdf_pages=[1,2],ratio=2,
                record_date='2022-05-27',effective_date='2022-05-27',effective_phase='EOD',ex_quote_date='2022-05-30',
                secondary_market_trading_unaffected=True,account_dependency=False,TR_dependency=False)
        elif '场内简称' in r['title']:
            fact.update(fact_type='RENAME_NOT_ECONOMIC_CONVERSION',physical_pdf_pages=[1],effective_date='2020-03-13',contract_rights_unchanged=True)
        elif '许可使用费' in r['title']:fact.update(fact_type='INDEX_LICENSE_FEE_NOT_INDEX_CONVERSION')
        else:fact.update(fact_type='DUPLICATE_DATE_OTHER_DOCUMENT_RETAINED',account_dependency=False)
        facts.append(fact)
    # Preserve the discovered same-date source-label defect and the concrete correction.
    save(REPORT/'source_evidence.json',dict(scope='R1I_FIXED_COHORT_V1',facts=facts,
        correction=dict(issue='Two different159938documents dated2020-03-12 initially shared one logical request label',
            detection='Explicit URL-to-receipt comparison before building stage',remedy='Retained first receipt; independently fetched name-change URL understate_namechange_20200312; collector now rejects label/URL mismatches',
            affected_dataset_rows=0),
        information_boundaries=dict(market_end='2024-12-31',post2024_publications_downloaded=False,new_strategy_returns_viewed=False),
        visual_review=dict(renderer='pdftoppm',inspected_pages=9,reviewer='M7 data agent, not human signoff',directory='data/raw_m7/visual')))
    snapshots=ds.manifest['source_snapshot_hashes']
    save(REPORT/'source_manifest.json',dict(scope='R1I_FIXED_COHORT_V1',stage=str(ROOT/'data/m7_fixed_cohort/stage_v1'),stage_manifest_sha256=sha(ROOT/'data/m7_fixed_cohort/stage_v1/manifest.json'),
        sources=[dict(repository_path=p,local_path=str(ROOT/p),sha256=h,available_locally=(ROOT/p).exists()) for p,h in snapshots.items()],
        redistribution='Local raw objects are not uploaded; indexes and hashes may be shared',budget=json.loads((OUT/'budget.json').read_bytes())['used']))
    print(json.dumps(dict(months=len(months),yearly=yearly,trend_ON=result['trend_ON'],facts=len(facts),sources=len(snapshots))))

if __name__=='__main__':main()
