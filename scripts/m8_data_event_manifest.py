"""Hash-bound complete action years and five dated economic events for M8."""
from decimal import Decimal
import json
from pathlib import Path
import re
from m8_data_collect import ROOT, REPORT, save, sha
from m7_data_audit import calendar
from quant_research.data import date_only_available_at

def main():
    annual=json.loads((REPORT/'ANNUAL_ACTION_EVIDENCE.json').read_bytes())['records']
    draft=json.loads((REPORT/'EVENT_TERMS_DRAFT.json').read_bytes());sessions=calendar();events=[];overrides={};documents=[]
    for item in json.loads((REPORT/'holding_documents.json').read_bytes()):
        documents.append(dict(item,pdf_sha256=item['receipt']['sha256'],pdf_path=item['receipt']['raw_path']))
    for item in draft['parsed_dividends']:
        doc=item['document'];text=Path(doc['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        if item['unresolved'] or '投资者可在红利发放日领取现金红利' not in compact:raise ValueError('Dividend investor cash date unproved')
        event={k:v for k,v in item.items() if k!='document'};event.update(engine_ready=True,verification_kind='AGENT_SOURCE_REVIEW_NOT_HUMAN_SIGNOFF')
        events.append(event)
        quote=re.search(r'中国证券登记结算有限责任公司上海分公司收到相应款项后.{0,200}投资者可在红利发放日领取现金红利',compact)
        if not quote:raise ValueError('Missing designated-broker settlement clause')
        overrides[event['action_id']]=dict(settlement_mode='RULE_BASED_SIMULATION',actual_pay_date=None,
            scheduled_pay_date=event['scheduled_pay_date'],pay_date=event['scheduled_pay_date'],
            settlement_account_type='HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT',settlement_rule_verified=True,
            settlement_rule_event_types=['CASH_DIVIDEND'],settlement_rule_source_url=event['source_url'],
            settlement_rule_source_hash=event['source_sha256'],settlement_rule_available_at=event['available_at'],
            settlement_rule_effective_from=event['announcement_date'],settlement_rule_effective_to=event['scheduled_pay_date'],
            settlement_rule_id=event['action_id']+'_ISSUER_DESIGNATED_BROKER_CASH_DAY',
            settlement_rule_credit_basis='ANNOUNCED_INVESTOR_PAY_DATE',settlement_rule_physical_page=2,
            settlement_rule_evidence=quote[0],actual_account_receipt_observed=False)
    specifications=[('sh.512760','2020-08-31','2020-09-08','2020-09-09','BOD','2020-09-10'),
                    ('sh.512710','2021-03-10','2021-03-18','2021-03-19','BOD','2021-03-22'),
                    ('sz.159939','2023-02-10','2023-02-15','2023-02-15','EOD','2023-02-16')]
    for sid,public,record,effective,phase,result_day in specifications:
        item=next(r for r in draft['attention'] if r['document']['instrument_id']==sid and r['document']['publication_date']==public)
        doc=item['document'];text=Path(doc['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        if sid[3:] not in compact or not re.search(r'1[:：]2',compact):raise ValueError('Split ratio/code not in plan')
        if phase=='EOD' and '权益登记日日终' not in compact:raise ValueError('EOD basis missing')
        result=next(r['document'] for r in draft['attention'] if r['document']['instrument_id']==sid and r['document']['publication_date']==result_day)
        rtext=re.sub(r'\s+','',Path(result['text_path']).read_text(encoding='utf8'))
        if not re.search(r'1[:：]2',rtext):raise ValueError('Split result ratio mismatch')
        events.append(dict(action_id=sid+'_SPLIT_'+effective,instrument_id=sid,type='SPLIT',
            announcement_date=public,available_at=date_only_available_at(public,sessions),ratio_available_at=date_only_available_at(public,sessions),
            record_date=record,ex_date='2023-02-16' if sid=='sz.159939' else effective,effective_date=effective,effective_phase=phase,
            split_ratio='2',cash_per_share='0',scheduled_pay_date=None,actual_pay_date=None,fractional_share_rounding='EXACT',
            source_url=doc['source_url'],source_sha256=doc['receipt']['sha256'],source_path=doc['receipt']['raw_path'],
            result_source_url=result['source_url'],result_source_sha256=result['receipt']['sha256'],
            result_publication_date=result_day,result_available_at=date_only_available_at(result_day,sessions),
            parse_status='PARSED_LABELED_TABLE',verification_kind='AGENT_HASH_BOUND_SOURCE_REVIEW_NOT_HUMAN_SIGNOFF',
            ratio_known_before_event=True,phase_basis='SUSPENDED_SESSION_BOD_MARK' if phase=='BOD' else 'EXPLICIT_RECORD_DATE_END_OF_DAY',engine_ready=True))
    coverage=[]
    for item in annual:
        sid,year=item['instrument_id'],item['year'];doc=item['document'];digest=doc['receipt']['sha256']
        split_events=[e for e in events if e['instrument_id']==sid and e['type']=='SPLIT' and e['effective_date'].startswith(str(year))]
        dividends=[e for e in events if e['instrument_id']==sid and e['type']=='DIVIDEND' and e['ex_date'].startswith(str(year))]
        split_status='EXECUTED_CHANGE_DOCUMENTED' if split_events else item['splits_status']
        split_evidence=item['split_evidence'];none=item['dividend_none_evidence']
        if (sid,year)==('sh.512710',2019):
            if digest!='16bd7760b12a5780b930f9cd463b35ba53662452616f1d13f1bb336981a7ccba':raise ValueError('Reviewed manual source changed')
            split_status='EXPLICIT_NONE';split_evidence=[dict(pdf_page=53,status='EXPLICIT_NONE',snippet='基金合同生效日2019年7月23日起至报告期期末基金拆分变动份额: —',method='VISUAL_PDF_PAGE_REVIEW')]
        if (sid,year)==('sh.512880',2019):
            text=Path(doc['text_path']).read_text(encoding='utf8').split('\f')[44]
            if '本基金本报告期无利润分配事项' not in re.sub(r'\s+','',text):raise ValueError('Manual distribution quote missing')
            none=none+[dict(pdf_page=45,statement='本基金本报告期无利润分配事项。',covered_years=[2019])]
        expected=sum(Decimal(e['cash_per_share']) for e in dividends)
        yearly=[r for r in item['dividend_totals'] if r['year']==year]
        if dividends:
            if not yearly or any(Decimal(r['cash_per_share'])!=expected for r in yearly):raise ValueError('Annual dividend mismatch')
            dividend_status='RECONCILED_POSITIVE'
        elif any(year in r['covered_years'] for r in none) or yearly and all(Decimal(r['cash_per_share'])==0 for r in yearly):dividend_status='EXPLICIT_ZERO_RECONCILED'
        else:raise ValueError('Annual zero distribution not proved '+sid+str(year))
        if split_status not in ('EXPLICIT_NONE','EXECUTED_CHANGE_DOCUMENTED'):raise ValueError('Annual split unresolved')
        coverage.append(dict(instrument_id=sid,year=year,status='COMPLETE',source_url=doc['source_url'],report_hashes=[digest],
            report_publication_date=doc['publication_date'],role='RETROSPECTIVE_COMPLETENESS_ONLY_NOT_SIGNAL_INPUT',
            dividend_status=dividend_status,split_status=split_status,annual_dividend_per_share=str(expected),
            dividend_none_evidence=none,dividend_annual_totals=yearly,split_evidence=split_evidence,
            dividend_source_hashes=[e['source_sha256'] for e in dividends],split_source_hashes=[e['source_sha256'] for e in split_events],unresolved=[]))
    save(REPORT/'EVENT_MANIFEST.json',dict(scope='R1I_HISTORICAL_LIQUID_V1',status='AUTHOR_COMPLETE_PENDING_INDEPENDENT_REVIEW',
        coverage=coverage,canonical_actions=events,documents=documents,action_overrides=overrides,
        source_policy_addendum_sha256=sha(REPORT/'SOURCE_POLICY_ADDENDUM.md'),source_origin='REAL_OFFICIAL_DOCUMENTS',synthetic=False))
    print('Complete annual product-years',len(coverage),'canonical events',len(events))

if __name__=='__main__':main()
