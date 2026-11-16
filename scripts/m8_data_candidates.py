"""Freeze M8 historical title discovery without reading post-2019 market data."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/m8_rotation'
FRAME = ROOT / 'reports/m6_r1i/official_listing_inventory.json'
FRAME_SHA = '55b7b554d5e785b91a743960dec5f84f45bfdac13c70f191fd5f71c308e58b7a'
KEYWORDS = '能源、材料、原料、资源、有色、煤炭、钢铁、化工、工业、制造、机械、军工、国防、消费、食品、饮料、酒、农业、医药、医疗、生物、健康、金融、银行、非银、证券、保险、地产、房地产、信息、科技、TMT、通信、计算机、电子、半导体、芯片、互联网、人工智能、机器人、新能源、环保、公用事业、大宗商品股票'.split('、')
GENERIC = ['证券投资基金', '上市交易公告书', '上市交易公告', '基金份额', '交易型开放式', '指数发起式', '证券投资', '指数型']

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    if sha(FRAME) != FRAME_SHA:
        raise ValueError('Frozen M6 sample identity changed')
    rows=[]
    for record in json.loads(FRAME.read_bytes())['records']:
        evidence=sorted([e for e in record['original_listing_title_evidence'] if e['publication_date'] <= '2019-12-31'], key=lambda e:(e['publication_date'],e['source_url']))
        matched=[]
        for e in evidence:
            title=e['title']
            for generic in GENERIC:
                title=title.replace(generic, '')
            words=[word for word in KEYWORDS if word.lower() in title.lower()]
            if words:
                matched.append(dict(e, stripped_title=title, matched_keywords=words))
        status='OUTSIDE_FIXED_ARCHIVAL_SAMPLE'
        reason='No pre-2020 original public listing title in frozen archive' if not evidence else 'No closed keyword matched after stripping generic fund text'
        if matched:
            full=' '.join(e['title'] for e in matched)
            excluded=next((word for word in ['LOF','联接','混合','债券','货币','QDII','海外','恒生','港股','期货','国企','央企','京津冀','一带一路'] if word.lower() in full.lower()),None)
            if excluded:
                status='EXCLUDED_HISTORICAL_TITLE';reason='Explicit out-of-scope title token: '+excluded
            else:
                status='PENDING_ORIGINAL_PRODUCT_REVIEW';reason='Historical closed-keyword hit; original required for product/industry/index/listing/state'
        rows.append(dict(instrument_id=record['instrument_id'], status=status, reason=reason,
                         pre2020_title_evidence=evidence, keyword_evidence=matched,
                         future_survival_used=False, future_returns_used=False))
    result=dict(scope='R1I_HISTORICAL_LIQUID_V1', frozen_at=datetime.now(timezone.utc).isoformat(),
                frame_path=FRAME.relative_to(ROOT).as_posix(), frame_sha256=FRAME_SHA,
                keywords=KEYWORDS, stripped_generic_phrases=GENERIC, discovery_cutoff='2019-12-31',
                pre2020_identity_count=sum(bool(r['pre2020_title_evidence']) for r in rows),
                counts=dict(Counter(r['status'] for r in rows)), records=rows,
                next_stage='Review original product evidence; identities remain until explicit evidence excludes them',
                post2019_market_data_read=False, strategy_returns_read=False,
                limitation='Finite M6 archival sample; absence of keyword is not a claim that product is never a sector ETF')
    path=REPORT/'CANDIDATE_REVIEW.json'
    if path.exists():
        raise RuntimeError('Candidate discovery freeze immutable; use supplemental review file')
    save(path,result)
    save(REPORT/'CANDIDATE_FREEZE_RECEIPT.json',dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),frozen_at=result['frozen_at'],post2019_market_data_read=False))
    print(json.dumps(result['counts']))
    for r in rows:
        if r['status']=='PENDING_ORIGINAL_PRODUCT_REVIEW':print(r['instrument_id'],r['keyword_evidence'][0]['title'])

if __name__=='__main__':main()
