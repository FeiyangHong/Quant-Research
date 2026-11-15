import pytest
from quant_research.providers.equity_audit import validate_query, inspect_records, FIELDS


@pytest.mark.parametrize('query', [
    {'kind':'universe','day':'2025-01-01'},
    {'kind':'industry','code':'sh.600518','date':''},
    {'kind':'profit','code':'sh.600518','year':2024,'quarter':4},
    {'kind':'history','code':'sh.600518','start_date':'2024-12-01','end_date':'2025-01-01'},
    {'kind':'universe'},
    {'kind':'master','code':'sh.600518'},
    {'kind':'industry','code':'sh.600518','date':'2024-12-31','asof':'2020-01-01'},
])
def test_final_holdout_and_implicit_defaults_rejected(query):
    with pytest.raises(ValueError):
        validate_query(query)


def test_vendor_unsolicited_current_industry_never_persisted_as_historical():
    query={'kind':'industry','code':'sh.600518','date':'2017-01-03'}
    accepted, forensic=inspect_records(query,['updateDate','code','industry','industryClassification'],[
        ['2026-01-01','sh.600518','future_information','CSRC'],
        ['2017-01-03','sh.600518','historical_candidate','CSRC']])
    assert accepted == [['2017-01-03','sh.600518','historical_candidate','CSRC']]
    assert forensic['unsolicited_post_cutoff_rows_discarded']==1
    assert len(forensic['discarded_rows_sha256'])==64
    # A passing response says nothing about historical availability.
    assert 'available_at' not in forensic


def test_raw_price_request_rejects_adjusted_response():
    query={'kind':'history','code':'sh.600518','start_date':'2017-01-03','end_date':'2017-01-04'}
    fields=FIELDS.split(',')
    row=['2017-01-03','sh.600518']+['1']*(len(fields)-2)
    row[fields.index('adjustflag')]='2'
    with pytest.raises(ValueError,match='raw price'):
        inspect_records(query,fields,[row])


def test_cross_security_response_rejected():
    query={'kind':'industry','code':'sh.600518','date':'2017-01-03'}
    with pytest.raises(ValueError,match='Security mismatch'):
        inspect_records(query,['updateDate','code','industry','industryClassification'],[['2017-01-03','sh.600519','C27','CSRC']])


def test_success_response_missing_required_columns_rejected():
    with pytest.raises(ValueError,match='Missing required'):
        inspect_records({'kind':'universe','day':'2017-01-03'},['code'],[['sz.000979']])


def test_duplicate_historical_members_rejected():
    with pytest.raises(ValueError,match='Duplicate response'):
        inspect_records({'kind':'universe','day':'2017-01-03'},['code','tradeStatus','code_name'],
                        [['sz.000979','1','name'],['sz.000979','1','name']])
