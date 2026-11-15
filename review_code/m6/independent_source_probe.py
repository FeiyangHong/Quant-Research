"""Run with existing E:/Anaconda/python.exe; no imports from production code."""
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import xlrd
import fitz

ROOT=Path(__file__).resolve().parents[2]


def read(name):return json.loads((ROOT/'reports/m6_r1i'/name).read_text('utf-8'))


def main():
    discovered=read('official_listing_inventory.json')
    ids=set();counts={};identities=[];sources={}
    for batch in discovered['batches']:
        rows=[];total=None
        for cap in batch['captures']:
            raw=Path(cap['raw_path']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==cap['sha256']
            sources[cap['raw_path']]=cap['sha256']
            body=json.loads(raw)
            if batch['exchange']=='sh':
                page=body['pageHelp']['data'];reported=body['pageHelp']['total']
                for row in page:
                    assert '上市交易公告书' in row['TITLE']
                    assert '2010-01-01'<=row['SSEDATE']<='2024-12-31'
                    ids.add('sh.'+row['SECURITY_CODE']);identities.append(row['URL'])
            else:
                page=body['data'];reported=body['announceCount']
                for row in page:
                    assert '上市交易公告书' in row['title']
                    assert '2010-01-01'<=row['publishTime'][:10]<='2024-12-31'
                    ids.update('sz.'+code for code in row['secCode']);identities.append(row['id'])
            if total is not None:assert total==reported
            total=reported;rows.extend(page)
        assert len(rows)==total
        counts[batch['exchange']]=len(rows)
    assert counts=={'sh':1166,'sz':1221}
    assert len(identities)==len(set(identities))==2387
    assert len(ids)==1959
    original={r['instrument_id'] for r in read('candidate_inventory.json')['records']}
    assert len(original & ids)==1137 and len(ids-original)==822 and len(original-ids)==11
    assert len(original | ids)==1970
    versions=read('historical_industry_versions.json')['versions']
    old,new=versions
    oldraw=Path(old['raw_path']).read_bytes();newraw=Path(new['raw_path']).read_bytes()
    assert hashlib.sha256(oldraw).hexdigest()==old['sha256']
    assert hashlib.sha256(newraw).hexdigest()==new['sha256']
    sheet=xlrd.open_workbook(file_contents=oldraw).sheet_by_index(0)
    counts2014=Counter(str(sheet.cell_value(i,2)).zfill(2) for i in range(1,sheet.nrows))
    labels={str(sheet.cell_value(i,2)).zfill(2):sheet.cell_value(i,3) for i in range(1,sheet.nrows)}
    assert sheet.nrows==2622 and set(labels)=={f'{i:02}' for i in range(10)}
    assert labels['06']=='金融地产' and labels['08']=='电信业务'
    doc=fitz.open(stream=newraw,filetype='pdf')
    text='\n'.join(page.get_text() for page in doc)
    assert 'V1.7' in text and '2023' in text and '10' in text
    expected=['能源','原材料','工业','可选消费','主要消费','医药卫生','金融','房地产','信息技术','通信服务','公用事业']
    assert all(label in text for label in expected)
    assert len(new['l1'])==11 and new['available_at'] is None and new['effective_from'] is None
    assert old['available_at']=='2014-05-28T21:00:00+08:00' and old['effective_from']=='2014-06-16'
    assert all(v['range_admitted_for_m6'] is False for v in versions)
    source=read('source_evidence.json')
    assert source['network_stop']
    assert source['new_http_equivalents']==46 and source['new_sdk_calls']==0
    assert sum(r['byte_count'] for r in source['source_receipts'])==source['new_observed_body_bytes']==4508462
    report=dict(status='PASS_FINITE_DATA_BLOCK_SUPPORTED_NOT_PERFORMANCE',independent_runtime='Python3.9.19 xlrd2.0.1 PyMuPDF1.26.5',
        new_network_attempts=0,batch_counts=counts,batch_unique_ids=len(ids),provider_union=1970,
        supplemental_ids_retained=822,provider_without_listing_title=11,
        classification2014_rows=sheet.nrows-1,classification2014_labels=labels,classification2014_counts=dict(counts2014),
        methodology2023_labels_checked=expected,source_hashes=sources,
        limitations=['Title-query pagination complete, not full lifecycle admission','2014 and2023 snapshots do not establish intervening effective/public chain',
                    'No unavailable2025+ search text opened by independent reviewer','Data gate based on missing evidence, not measured insufficientN or strategy failure'])
    target=ROOT/'reports/m6_review/independent_final_source_probe.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS:37rawpages,2387uniqueannouncements,1959IDs,1970union,2014tenindustry2621rows;2023elevenindustryclockunknown')


if __name__=='__main__':main()
