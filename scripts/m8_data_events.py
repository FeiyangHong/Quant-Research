"""Parse only annual action-completeness and dated event terms, preserving unknowns."""
from collections import Counter
import json
from pathlib import Path
import re
from m8_data_collect import ROOT, REPORT, save, sha
from m7_data_audit import calendar
from quant_research.providers.official import annual_evidence, parse_dividend

def main():
    docs=json.loads((REPORT/'holding_documents.json').read_bytes());annual=[];events=[];attention=[]
    sessions=calendar()
    for row in docs:
        if not row.get('text_path'):raise ValueError('Failed necessary document')
        cap=row['receipt']
        if sha(cap['raw_path'])!=cap['sha256']:raise ValueError('Changed original')
        text=Path(row['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        doc=dict(row,pdf_sha256=cap['sha256'],source_sha256=cap['sha256'],pdf_path=cap['raw_path'],text_sha256=row['text_sha256'])
        if row['kind']=='ANNUAL':
            fact=annual_evidence(doc,text);fact['document']=row
            sections=[]
            for page,body in enumerate(text.split('\f'),1):
                if any(s in body for s in ['利润分配','拆分变动份额','拆分/份额折算','基金份额折算变动','业绩比较基准']):
                    sections.append(dict(physical_pdf_page=page,text=body))
            fact['relevant_pages']=sections;annual.append(fact)
        elif '分红公告' in row['title']:
            events.append(dict(parse_dividend(doc,text,sessions),document=row))
        else:
            attention.append(dict(document=row,
                kind='SPLIT_NOTICE' if '拆分' in row['title'] else 'CONTRACT_OR_LIFECYCLE',
                source_extract=compact[:2500] if '拆分' in row['title'] else compact[:700]))
    save(REPORT/'ANNUAL_ACTION_EVIDENCE.json',dict(records=annual,count=len(annual),source_role='RETROSPECTIVE_COMPLETENESS_ONLY_NOT_SIGNAL_INPUT'))
    save(REPORT/'EVENT_TERMS_DRAFT.json',dict(parsed_dividends=events,attention=attention))
    print('annual',len(annual),Counter(r['splits_status'] for r in annual),'dividends',len(events))
    for r in annual:print(r['instrument_id'],r['year'],r['splits_status'],r['dividend_totals'],[x['statement'][:100] for x in r['dividend_none_evidence']])
    for e in events:print(e['instrument_id'],e['parse_status'],e['record_date'],e['ex_date'],e['scheduled_pay_date'],e['cash_per_share'])

if __name__=='__main__':main()
