"""Original-product evidence before 2019 amount ranking; unknowns stay explicit."""
from bisect import bisect_left
from collections import Counter
import json
import re
import sys
from pathlib import Path
from m8_data_candidates import ROOT, REPORT, save, sha
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.official import listing_evidence, label_date
from quant_research.data import date_only_available_at
from m7_data_audit import calendar

def main():
    sessions=calendar();last=sessions.index('2019-12-31');result=[]
    docs=json.loads((REPORT/'listing_documents.json').read_bytes())
    contracts_path=REPORT/'INDEX_CONTRACT_DOCUMENTS.json'
    contracts={r['instrument_id']:r for r in json.loads(contracts_path.read_bytes())} if contracts_path.exists() else {}
    for record in docs:
        sid=record['instrument_id']
        if not sid.startswith(('sh.51','sz.159')):continue
        cap=record['receipt'];e=record['listing']
        base=dict(instrument_id=sid,status='UNKNOWN_ORIGINAL',original=record)
        if not record.get('text_path'):
            result.append(base);continue
        if sha(cap['raw_path'])!=cap['sha256']:raise ValueError('Source changed')
        text=Path(record['text_path']).read_text(encoding='utf8');compact=re.sub(r'\s+','',text)
        document=dict(instrument_id=sid,title=e['title'],publication_date=e['publication_date'],source_url=e['source_url'],
                      pdf_sha256=cap['sha256'],pdf_path=cap['raw_path'],text_path=record['text_path'],document_kind='LISTING_NOTICE')
        parsed=listing_evidence(document,text,sessions)
        if not parsed['listed_on']:
            parsed['listed_on']=label_date(compact,r'(?:上市日期|上市交易日期|上市交易日|上市交易的时间)')
        if sid=='sh.515070':
            stated=re.search(r'将于(2019)年(12)月(24)日在上海证券交易所上市',compact)
            if stated:parsed['listed_on']='2019-12-24';base['listing_date_exact_quote']=stated[0]
        name=parsed['legal_fund_name']
        if not name:
            match=re.search(r'([\u4e00-\u9fffA-Za-z0-9]+?交易型开放式指数(?:发起式)?证券投资基金)',compact)
            if match:name=match[1];parsed['legal_fund_name']=name
        if sid=='sz.159909' and '深证电子信息传媒产业（TMT）50交易型开放式指数证券投资基金' in compact:
            name='深证电子信息传媒产业（TMT）50交易型开放式指数证券投资基金'
            parsed['legal_fund_name']=name
        if name:
            match=re.search(r'(上证[^。:：]*?|沪深300[^。:：]*?|中证[^。:：]*?|CES[^。:：]*?|深证[^。:：]*?)交易型',name)
            index=match[1] if match else None
            if index:
                index=index.removesuffix('指数')+'指数'
                base['exact_index_name_original']=index
                base['exact_index_id']='NAME:'+index
                base['exact_index_basis']='ORIGINAL_LEGAL_FUND_NAME_AND_ORIGINAL_CONTRACT_INDEX_TEXT_PENDING_REVIEW'
        if sid=='sz.159909' and '深证TMT50指数' in compact:
            base.update(exact_index_name_original='深证TMT50指数',exact_index_id='NAME:深证TMT50指数',exact_index_basis='ORIGINAL_CONTRACT_INVESTMENT_SCOPE')
        if sid in contracts:
            contract=contracts[sid];ctext=Path(contract['text_path']).read_text(encoding='utf8')
            cname={'sh.510230':'上证180金融股指数','sh.512760':'中华交易服务半导体行业指数'}.get(sid,base['exact_index_name_original'])
            clauses=[]
            for page,body in enumerate(ctext.split('\f'),1):
                cbody=re.sub(r'\s+','',body)
                for match in re.finditer(r'(?:标的指数：|本基金的标的指数为|本基金标的指数为|业绩比较基准为).{0,200}',cbody):
                    if cname in match[0]:clauses.append(dict(physical_pdf_page=page,quote=match[0]))
            if not clauses:raise ValueError('Exact index clause unresolved '+sid)
            base.update(exact_index_name_original=cname,exact_index_id='NAME:'+cname,
                exact_index_basis='DATED_ORIGINAL_CONTRACT_OR_PROSPECTUS_EXPLICIT_TARGET_CLAUSE',
                index_alias_original_fund_name=name,index_contract_document=contract,index_contract_clauses=clauses,
                index_contract_available_at=date_only_available_at(contract['publication_date'],sessions))
        base.update(parsed)
        age=max(0,last-bisect_left(sessions,parsed['listed_on'])+1) if parsed.get('listed_on') else None
        base['listed_sessions_at_formation']=age
        base['state_at_formation']='PENDING_PRE2020_LIFECYCLE_REVIEW'
        if name and '交易型开放式' in name:
            base['status']='INCLUDED_PENDING_FORMATION' if age is not None and age>=60 else 'EXCLUDED_LISTED_LESS_THAN_60' if age is not None else 'UNKNOWN_LISTING_DATE'
        result.append(base)
    save(REPORT/'PRODUCT_REVIEW.json',dict(scope='R1I_HISTORICAL_LIQUID_V1',records=result,counts=dict(Counter(r['status'] for r in result)),
        future_information_used=False,formation_market_data_read=False))
    print(Counter(r['status'] for r in result))
    for r in result:print(r['instrument_id'],r['status'],r.get('listed_on'),r.get('exact_index_name_original'),r.get('legal_fund_name'))

if __name__=='__main__':main()
