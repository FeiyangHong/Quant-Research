"""Offline reconciliation of the finite M6 documentary pilot; no performance.

The dated taxonomy facts below were transcribed from identified primary pages.
This is an agent evidence table, not a claim of human or full-dataset admission.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from m6_r1i_data_audit import ROOT, OUT, SCOPE, digest, read, save


def main():
    log = read(OUT/'pilot_request_log.json')
    receipts = {r['label']:r['receipt'] for r in log}
    for r in receipts.values():
        if digest(r['raw_path']) != r['sha256']:
            raise ValueError('Pilot source hash mismatch')
    all_rows = []
    batches = []
    for exchange, tag, total, pages in [('sh','sse',1166,12),('sz','szse',1221,25)]:
        rows = []
        captures = []
        source_records = 0
        for page in range(1,pages+1):
            receipt=receipts[f'r1i_{tag}_listing_page_{page}']
            if receipt['status'] != 'FETCHED':
                raise ValueError('Incomplete batch discovery')
            payload=read(receipt['raw_path'],receipt['sha256'])
            actual_total=payload['pageHelp']['total'] if exchange=='sh' else payload['announceCount']
            if actual_total != total:
                raise ValueError('Batch total changed')
            raw_rows=payload['result'] if exchange=='sh' else payload['data']
            source_records+=len(raw_rows)
            for row in raw_rows:
                ids=['sh.'+row['SECURITY_CODE']] if exchange=='sh' else ['sz.'+x for x in row['secCode']]
                title=row['TITLE'] if exchange=='sh' else row['title']
                publication=row['SSEDATE'] if exchange=='sh' else row['publishTime'][:10]
                url='https://www.sse.com.cn'+row['URL'] if exchange=='sh' else 'https://disc.static.szse.cn/download'+row['attachPath']
                if not '2010-01-01'<=publication<='2024-12-31' or '上市交易公告书' not in title:
                    raise ValueError('Source ignored date/title filter')
                for code in ids:
                    rows.append(dict(instrument_id=code,title=title,publication_date=publication,source_url=url,
                                     capture_sha256=receipt['sha256'], historical_scope_admitted=False))
            captures.append(dict(page=page,receipt_id=receipt['id'],sha256=receipt['sha256'],raw_path=receipt['raw_path']))
        if source_records != total or len({(r['instrument_id'],r['source_url'],r['publication_date']) for r in rows}) != len(rows):
            raise ValueError('Batch pages incomplete or repeated')
        batches.append(dict(exchange=exchange,reported_records=total,returned_records=source_records,
                            code_associations=len(rows),pages=pages,pagination_complete=True,captures=captures))
        all_rows.extend(rows)
    inventory=read(OUT/'candidate_inventory.json')['records']
    provider_ids={r['instrument_id'] for r in inventory}
    title_ids={r['instrument_id'] for r in all_rows}
    extras=sorted(title_ids-provider_ids)
    # All supplementary IDs survive. These include LOFs, structured funds and
    # late announcements; a title heuristic does not establish lifetime scope.
    union=[]
    for code in sorted(provider_ids|title_ids):
        notices=[r for r in all_rows if r['instrument_id']==code]
        union.append(dict(instrument_id=code,in_historical_provider_inventory=code in provider_ids,
                          original_listing_title_evidence=notices,
                          original_listing_file_reviewed=code in {'sh.510820','sz.159940'},
                          economic_scope_status='UNRESOLVED_HISTORY_NO_NAME_BASED_DELETION',
                          historical_csi_l1_mapping=None))
    save('official_listing_inventory.json',dict(scope=SCOPE,batches=batches,
         unique_official_fund_ids=len(title_ids),provider_intersection=len(provider_ids&title_ids),
         provider_ids_without_matching_title=sorted(provider_ids-title_ids),
         supplemental_ids=extras,union_fund_identity_count=len(union),records=union,
         limitation='All-fund title discovery is not an ETF admission list. Complete pagination proves the query result, not that alternate titles or absent records never existed.'))
    old_names=['能源','原材料','工业','可选消费','主要消费','医药卫生','金融地产','信息技术','电信业务','公用事业']
    new_names=['能源','原材料','工业','可选消费','主要消费','医药卫生','金融','房地产','信息技术','通信服务','公用事业']
    def evidence(label,**facts):
        r=receipts[label]
        return dict(label=label,url=r['url'],sha256=r['sha256'],raw_path=r['raw_path'],ingested_at=r['ingested_at'],
                    extracted_by='AGENT_DOCUMENT_REVIEW_NOT_HUMAN_SIGNOFF',**facts)
    versions=[evidence('r1i_csi_2014_classification_xls',
                      version_id='CSI_L1_OBSERVED_2014_06_16',version_kind='DATED_CLASSIFICATION_RESULT_SNAPSHOT',
                      publication_date='2014-05-27',available_at='2014-05-28T21:00:00+08:00',effective_from='2014-06-16',effective_to=None,
                      clock_source_sha256=receipts['r1i_csi_industry_2014_notice']['sha256'],
                      sheet='全部股票最新分类',rows_excluding_header=2621,industry_code_column=3,industry_name_column=4,
                      l1=[dict(code=f'{i:02d}',name=n) for i,n in enumerate(old_names)],
                      range_admitted_for_m6=False,
                      limitation='Real historical ten-industry snapshot; no assertion all intervening revisions through2016/2021 are covered.'),
              evidence('r1i_csi_method_2023',version_id='CSI_ALL_SHARE_SECTOR_METHOD_V1_7_2023_10',
                       version_kind='DOCUMENT_INTERNAL_VERSION',document_version='V1.7',internal_month='2023-10',
                       publication_date=None,available_at=None,effective_from=None,effective_to=None,
                       physical_pdf_pages=[1,2,3],l1=[dict(name=n) for n in new_names],
                       exact_l1_index_codes=['932077','932078','932079','932080','932081','932082','932083','931775','932084','932085','932086'],
                       range_admitted_for_m6=False,
                       limitation='Month/version header and method/appendix verified. No original publication day or complete predecessor/change chronology; do not backfill2016 or infer code equivalence. Admits no product by name alone.')]
    save('historical_industry_versions.json',dict(scope=SCOPE,status='PARTIAL_PRIMARY_VERSIONS_NOT_COMPLETE_PIT_CHAIN',versions=versions,
        unclosed_transitions=[dict(event='Ten to eleven L1 split and telecom renaming',
                                  claimed_effective_date_in_secondary_discovery='2021-12-13',
                                  primary_transition_notice_acquired=False,admitted_effective_date=None,
                                  affected_industries=['金融地产','金融','房地产','电信业务','通信服务'],
                                  treatment='No transition date or mapping admitted from secondary search snippets')],
        midquarter_policy='Freeze quarterly security IDs and original amount/listing/ID keys; remap at month end using known effective classification; merge collision keeps best original key, split adds no new representative; unknown mapping BLOCKED; economic-index change inactive until next quarter.'))
    facts=[evidence('r1i_csi_industry_2014_notice',publication_date='2014-05-27',effective_from='2014-06-16',
                    available_at='2014-05-28T21:00:00+08:00',fact='Primary issuer notice links the dated classification spreadsheet;54company classifications changed.',url_migration_year=2015),
           evidence('r1i_financial_realestate_2015',instrument_id='sz.159940',publication_date='2015-04-14',
                    available_at='2015-04-15T21:00:00+08:00',effective_listing_date='2015-04-17',
                    exact_index_code='000992',exact_index_name='中证全指金融地产指数',physical_pdf_pages=[1,3],
                    limitation='Original listing and index identity verified; no proof of full historical classification/liquidity eligibility.'),
           evidence('r1i_510820_original_listing',instrument_id='sh.510820',publication_date='2019-07-04',
                    available_at='2019-07-05T21:00:00+08:00',effective_listing_date='2019-07-09',
                    product_name='上证上海改革发展主题交易型开放式指数发起式证券投资基金',physical_pdf_pages=[1,3,4],
                    fact='Official ETF listing absent from all61 archived provider discovery endpoints.',
                    limitation='A real discovery discrepancy; does not itself prove eligibility, survival to an endpoint or a qualifying omitted industry competitor.'),
           evidence('r1i_512220_2020_index_rename',instrument_id='sh.512220',publication_date='2020-12-10',
                    available_at='2020-12-11T21:00:00+08:00',index_name_effective_from='2020-12-14',fund_name_effective_from='2020-12-15',
                    old_name='中证TMT150指数',new_name='中证科技传媒通信150指数',physical_pdf_pages=[1,2,3],
                    index_method_unchanged_explicitly=True,economic_index_conversion=False,
                    limitation='Name changes have separate clocks; this notice does not establish single-L1 scope.'),
           evidence('r1i_512760_2020_index_rename',instrument_id='sh.512760',publication_date='2020-06-11',
                    available_at='2020-06-12T21:00:00+08:00',index_name_effective_from='2020-06-15',fund_name_effective_from='2020-06-16',
                    old_name='中华交易服务半导体行业指数',new_name='中华交易服务半导体芯片行业指数',physical_pdf_pages=[1,2],
                    economic_index_conversion=None,
                    limitation='Primary name change verified; do not automatically classify it as an economic index replacement or grant CSI L1 admission.')]
    book=read(ROOT/'data/raw_m6/budget.json')
    requests=[r for r in book['attempts'] if r['scope']=='r1i']
    if len(requests)>48 or any(not r.get('terminal') for r in requests):
        raise ValueError('Finite source pilot exceeded or unresolved')
    save('source_evidence.json',dict(scope=SCOPE,status='FINITE_PILOT_CLOSED_DATA_BLOCKED',facts=facts,
         new_http_equivalents=len(requests),new_sdk_calls=0,new_observed_body_bytes=sum(r['byte_count'] for r in requests),
         source_receipts=requests,pdf_visual_review_pages=dict(r1i_csi_method_2023=[1,3],r1i_financial_realestate_2015=[1,3],
             r1i_510820_original_listing=[1,4],r1i_512220_2020_index_rename=[1],r1i_512760_2020_index_rename=[1]),
         network_stop='No further collection in this pilot. Historical complete identity/method/taxonomy/amount gate remains unproved.',
         source_plan_result='Batch listing discovery is feasible:37requests rather than one search perID. Full historical single-industry identity and amount dependency remains unresolved; no universal free-source impossibility claim.'))
    save('data_gate_decision.json',dict(scope=SCOPE,status='DATA_BLOCKED',returns_matrix_data_gate_passed=False,
         decision='STOP_THIS_M6_DATASET_NO_PERFORMANCE_MATRIX',
         specific_blockers=[
           'Historical CSI ten/eleven-industry transition and intervening effective/public versions not complete for2016-2024.',
           'Exact-index-to-one-historical-L1 methods and identity changes for the full potential competitor set not verified.',
           '991 required-provider-review IDs lack full raw amount histories; no selection over available-only competitors.',
           'Official batch and provider discovery disagree;822supplemental fund IDs retained, not deleted by present-day type or name.',
           'Final representatives therefore unknown; their TR, actions, daily status, account and risk dependencies cannot be signed off.'],
         eligibility_distribution={'UNKNOWN':108},n_ge4_development=None,n_ge4_validation=None,
         n_ge4_by_validation_year={'2022':None,'2023':None,'2024':None},n_ge4_and_trend_on=None,
         not_claimed=['Strategy unprofitable','Insufficient true selection opportunity','All free historical sources impossible','Stock financial/human gates block ETFs'],
         finite_stop=True,performance_metrics_computed=False))
    print(json.dumps(dict(official_unique_fund_ids=len(title_ids),union_ids=len(union),pilot_requests=len(requests),status='DATA_BLOCKED')))


if __name__=='__main__':
    main()
