"""Resolve exact historical tracking-index clauses before selection freeze."""
import json
from m8_data_collect import REPORT, titles_one, document, save

def main():
    for sid in ['sh.512480','sh.512710']:
        titles_one(sid,'2019-01-01','2019-12-31','contract')
    needed=['sh.510230','sh.512000','sh.512290','sh.512480','sh.512660','sh.512710','sh.512720','sh.512760','sh.512800','sh.512880','sh.512900','sh.515000','sh.515880']
    products={r['instrument_id']:r for r in json.loads((REPORT/'PRODUCT_REVIEW.json').read_bytes())['records']}
    result=[]
    for sid in needed:
        path=REPORT/'titles'/ (('contract_' if sid in ['sh.512480','sh.512710'] else 'formation_')+sid+'.json')
        rows=json.loads(path.read_bytes())['records'];name={'sh.510230':'上证180金融','sh.512760':'CES半导体行业'}.get(sid,products[sid]['exact_index_name_original'].removesuffix('指数'))
        choices=[r for r in rows if ('招募说明书' in r['title'] or r['title'].endswith('基金合同')) and name in r['title'] and '摘要' not in r['title'] and '提示' not in r['title']]
        if not choices:raise ValueError('No historical index contract '+sid)
        row=sorted(choices,key=lambda r:(r['publication_date'],'招募' in r['title']),reverse=True)[0]
        result.append(document('index_contract_'+sid,row));save(REPORT/'INDEX_CONTRACT_DOCUMENTS.json',result)

if __name__=='__main__':main()
