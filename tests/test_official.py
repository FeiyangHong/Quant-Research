import hashlib
import json
from pathlib import Path

import pytest

from quant_research.providers.official import (OfficialArchive,annual_evidence,
    classify_document,parse_dividend,parse_split_notice,query_announcements,validate_url,
    reconcile_coverage,query_announcement_titles,build_master_records)


def document(**changes):
    result=dict(instrument_id='sh.510300',title='测试ETF分红公告',publication_date='2024-01-11',
                source_url='https://www.sse.com.cn/test.pdf',pdf_sha256='a'*64,
                text_sha256='b'*64,pdf_path='raw/test.bin',report_year=2023)
    result.update(changes)
    return result


def test_dividend_exact_units_and_source_dates_are_preserved():
    text='本次分红方案（单位：元/10份基金份额）0.6900\n有关年度分红次数\n权益登记日2024年1月17日\n除息日2024年1月18日\n现金红利发放日2024年1月23日'
    event=parse_dividend(document(),text,['2024-01-11','2024-01-12','2024-01-15'])
    assert event['cash_per_share']=='0.0690'
    assert event['available_at']=='2024-01-12T21:00:00+08:00'
    assert event['ex_date']=='2024-01-18'
    assert event['actual_pay_date'] is None and not event['engine_ready']
    late=parse_dividend(document(publication_date='2024-01-18'),text,['2024-01-19'])
    assert late['ex_date']=='2024-01-18'
    assert late['available_at']=='2024-01-19T21:00:00+08:00'


def test_ambiguous_amount_and_missing_dates_do_not_become_zero():
    text='本次分红方案(单位:元/10份基金份额) 0.69 0.70\n有关年度分红次数'
    event=parse_dividend(document(),text)
    assert event['cash_per_share'] is None
    assert event['parse_status']=='NEEDS_REVIEW'
    assert 'ex_date' in event['unresolved']


def test_wrapped_dividend_unit_keeps_interleaved_table_value():
    event=parse_dividend(document(),'本次分红方案(单位:元/10\n     1.633\n份基金份额)\n有关年度分红次数\n权益登记日2018年11月7日\n除息日2018年11月8日\n现金红利发放日2018年11月13日')
    assert event['cash_per_share']=='0.1633'
    assert event['parse_status']=='PARSED_LABELED_TABLE'


def test_annual_negative_split_is_not_no_split():
    no=annual_evidence(document(),'本报告期基金拆分变动份额       -\n本报告期期末基金份额总额 100\n本基金过去三年未进行利润分配。')
    assert no['splits_status']=='EXPLICIT_NONE'
    assert no['dividend_none_evidence'][0]['covered_years']==[2021,2022,2023]
    actual=annual_evidence(document(),'本报告期基金拆分变动份额       -100,000.00\n本报告期期末基金份额总额 100')
    assert actual['splits_status']=='NEEDS_REVIEW'
    absent=annual_evidence(document(),'No statement')
    assert absent['splits_status']=='NEEDS_REVIEW'


def test_post2024_only_retrospective_annuals_and_no_link_funds():
    assert classify_document(document(publication_date='2025-01-03')) is None
    assert classify_document(document(publication_date='2025-03-31',title='测试ETF2024年年度报告'))==('ANNUAL_REPORT',2024)
    assert classify_document(document(publication_date='2025-03-31',title='测试ETF2025年年度报告')) is None
    assert classify_document(document(title='测试ETF联接基金2023年年度报告')) is None


def test_public_url_validation():
    for url in ['http://www.sse.com.cn/a','https://sse.com.cn.evil.test/a','https://user:pass@www.sse.com.cn/a']:
        with pytest.raises(ValueError):validate_url(url)
    validate_url('https://disc.static.szse.cn/download/example.PDF')


def test_cache_is_hash_checked_and_failed_attempt_retained(tmp_path):
    calls=[]
    def worker(config):
        calls.append(config)
        if len(calls)==1:raise TimeoutError('bounded simulated failure')
        return {'http_status':200},b'verified'
    archive=OfficialArchive(tmp_path,min_interval=0,transport=worker)
    cap=archive.fetch('https://www.sse.com.cn/example')
    assert len(list((tmp_path/'captures').glob('*.json')))==2
    assert archive.fetch('https://www.sse.com.cn/example')==cap
    assert len(calls)==2
    (tmp_path/cap['raw_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash'):archive.fetch('https://www.sse.com.cn/example')


def test_pagination_repeated_page_fails_closed(tmp_path):
    row={'TITLE':'Test','SSEDATE':'2024-01-01','SECURITY_CODE':'510300','URL':'/test.pdf'}
    payload=json.dumps({'pageHelp':{'total':2},'result':[row]}).encode()
    archive=OfficialArchive(tmp_path,min_interval=0,transport=lambda c:({'http_status':200},payload))
    with pytest.raises(ValueError,match='Repeated'):query_announcements(archive,'sh.510300','2024-01-01','2024-12-31')


def test_miskeyed_sse_records_fail_closed(tmp_path):
    row={'TITLE':'Test','SSEDATE':'2024-01-01','SECURITY_CODE':'510500','URL':'/test.pdf'}
    payload=json.dumps({'pageHelp':{'total':1},'result':[row]}).encode()
    archive=OfficialArchive(tmp_path,min_interval=0,transport=lambda c:({'http_status':200},payload))
    with pytest.raises(ValueError,match='Mis-keyed'):query_announcements(archive,'sh.510300','2024-01-01','2024-12-31')


def test_wrapped_annual_label_does_not_swallow_no_split_value():
    evidence=annual_evidence(document(),'本报告期期间基金拆分变动份额(份额减少\n        -\n以"-"填列)\n本报告期期末基金份额总额 100')
    assert evidence['splits_status']=='EXPLICIT_NONE'


def test_cancelled_split_is_retained_but_never_applied():
    evidence=parse_split_notice(document(title='取消基金份额拆分的公告'),
        '权益登记日:2022年8月2日。份额拆分日:2022年8月3日。基金份额拆分比例为1.5。取消本次拆分。')
    assert evidence['status']=='CANCELLED'
    assert evidence['ex_date']=='2022-08-03'
    assert evidence['apply_to_ledger'] is False


def test_eod_split_and_ceil_are_explicit():
    evidence=parse_split_notice(document(title='基金份额拆分公告'),
        '份额拆分日:2022年8月26日。拆分对象:份额拆分日登记在册的基金份额。份额拆分比例为1.14539。份额拆分日日终完成登记。采用上进位。')
    assert evidence['split_ratio']=='1.14539'
    assert evidence['record_date']=='2022-08-26'
    assert evidence['effective_phase']=='END_OF_DAY'
    assert evidence['fractional_share_rounding']=='CEIL'


def test_parenthesized_effective_date_and_cancel_narrative():
    event=parse_split_notice(document(title='基金份额合并公告'),'份额合并日(2022年9月2日)。份额合并比例为0.36555。')
    assert event['ex_date']=='2022-09-02'
    cancelled=parse_split_notice(document(title='取消基金份额拆分公告'),'2022年8月3日为份额拆分日。')
    assert cancelled['ex_date']=='2022-08-03' and cancelled['apply_to_ledger'] is False


def test_two_column_annual_accounting_no_share_change():
    event=annual_evidence(document(),'基金拆分/份额折算变动份额      -      -\n其他 123')
    assert event['splits_status']=='EXPLICIT_NONE'
    actual=annual_evidence(document(),'基金拆分/份额折算变动份额      -100.00      -200.00\n其他 123')
    assert actual['splits_status']=='NEEDS_REVIEW'


def test_chinese_year_and_duplicate_annual_title_are_recognized():
    assert classify_document(document(title='富国ETF二0二三年年度报告'))==('ANNUAL_REPORT',2023)
    assert classify_document(document(title='建信ETF2023年度年度报告'))==('ANNUAL_REPORT',2023)
    assert classify_document(document(title='关于推迟披露2019年年度报告的公告')) is None


def test_birth_year_wrapped_dash_and_no_distribution_word_order():
    evidence=annual_evidence(document(),'基金合同生效日起至报告期期末基金\n       -\n拆分变动份额\n过去三年本基金未实施利润分配。')
    assert evidence['splits_status']=='EXPLICIT_NONE'
    assert evidence['dividend_none_evidence'][0]['covered_years']==[2021,2022,2023]


def test_reconciliation_rejects_missing_and_mismatching_notices():
    doc=document(status='SUCCESS')
    annual=annual_evidence(doc,'本报告期基金拆分变动份额 -\n本基金本报告期未进行利润分配。')
    _,coverage=reconcile_coverage([], [annual], [doc])
    row=next(r for r in coverage if r['year']==2023)
    assert row['status']=='COMPLETE' and row['notice_total_per_share']=='0'
    annual['dividend_none_evidence']=[]
    annual['dividend_totals']=[{'year':2023,'cash_per_share':'0.1','pdf_page':1}]
    _,coverage=reconcile_coverage([], [annual], [doc])
    assert next(r for r in coverage if r['year']==2023)['dividend_status']=='NOTICE_ANNUAL_MISMATCH'
    _,coverage=reconcile_coverage([],[],[doc])
    assert all(r['status']=='INCOMPLETE' for r in coverage)


def test_global_title_query_rejects_ignored_filter(tmp_path):
    payload=json.dumps({'announceCount':1,'data':[{'title':'unrelated','publishTime':'2024-01-01','secCode':['159915'],'attachPath':'/test.pdf'}]}).encode()
    archive=OfficialArchive(tmp_path,min_interval=0,transport=lambda c:({'http_status':200},payload))
    with pytest.raises(ValueError,match='filter was ignored'):query_announcement_titles(archive,'sz','转型')


def test_post_split_dividend_entitlement_and_transfer_are_not_broker_receipt():
    text='本次分红方案(单位:元/10份基金份额)1.2920\n有关年度分红次数\n权益登记日2024年11月29日\n除息日2024年12月2日\n现金红利发放日2024年12月3日\n本次分红方案对应的基金份额为在权益登记日实施拆分业务后的基金份额。\n本次派发的现金红利将于2024年12月3日自本基金托管账户划出。投资者收到时间遵循销售机构规定。'
    event=parse_dividend(document(publication_date='2024-11-16'),text)
    assert event['cash_per_share']=='0.1292'
    assert event['entitlement_unit_basis']=='POST_SPLIT_REGISTERED_UNITS'
    assert event['cash_schedule_meaning']=='CUSTODIAN_TRANSFER_DATE'
    assert event['settlement_notice_evidence']==[] and event['actual_pay_date'] is None


def test_original_index_conversion_has_separate_known_and_effective_dates():
    source='75777d1377e0e3a97ebaee30ec10086f366241e59f8a356de24a5e10d66aafaf'
    original=dict(instrument_id='sz.159908',role='ORIGINAL_PUBLIC_LISTING_NOTICE',is_correction=False,
                  source_sha256=source,listed_on='2011-07-13',benchmark_id=None,
                  announcement_date='2011-07-08',available_at='2011-07-11T21:00:00+08:00',
                  source_url='https://disc.static.szse.cn/original.pdf',source_path='raw/original.bin',
                  legal_fund_name='深证基本面200交易型开放式指数证券投资基金')
    conversion=document(instrument_id='sz.159908',publication_date='2018-12-04',
                        pdf_sha256='f45e0013666c49bed93ad891e58f9fa59389faac65a60f1e8acc5c50b2a7ac10')
    records=build_master_records([original],[{'code':'sz.159908','category':'CHINEXT'}],[conversion],['2018-12-05','2018-12-10'])
    assert [r['strategy_universe'] for r in records]==['OUTSIDE','R1B']
    assert records[1]['effective_from']=='2018-12-10'
    assert records[1]['available_at']=='2018-12-05T21:00:00+08:00'
    assert records[0]['effective_to'] is None  # No retroactive future information on original record.
    original['source_sha256']='a'*64
    with pytest.raises(ValueError,match='reviewed immutable source'):
        build_master_records([original],[{'code':'sz.159908','category':'CHINEXT'}],[],[])
