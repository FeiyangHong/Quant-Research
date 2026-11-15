import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from m5_market_cap import select_vendor_candidate,valuation_diagnostics


def test_period_end_does_not_grant_visibility_before_notice():
    old=dict(END_DATE='2020-01-03',NOTICE_DATE='2019-12-31',TOTAL_SHARES=100,TOTAL_A_SHARES=100)
    late=dict(END_DATE='2020-06-30',NOTICE_DATE='2020-08-20',TOTAL_SHARES=110,TOTAL_A_SHARES=110)
    selected,rejected=select_vendor_candidate([late,old])
    assert selected==old and rejected[0]['row']==late


def test_date_only_snapshot_notice_is_not_available_same_day():
    row=dict(END_DATE='2020-07-30',NOTICE_DATE='2020-07-31',TOTAL_SHARES=100,TOTAL_A_SHARES=100)
    assert select_vendor_candidate([row])[0] is None


def test_same_date_conflicting_counts_fail_closed():
    row=dict(END_DATE='2020-01-01',NOTICE_DATE='2019-12-30',TOTAL_SHARES=100,TOTAL_A_SHARES=100)
    with pytest.raises(ValueError,match='Conflicting'):
        select_vendor_candidate([row,row|dict(TOTAL_SHARES=101)])


def test_multiclass_diagnostic_is_explicitly_not_perclass_aggregate():
    d=valuation_diagnostics('4.97',356406257089,269612212539,h_shares=86794044550)
    assert d['a_price_times_all_ordinary_cny']=='1771339097732.33'
    assert d['a_share_only_value_cny']=='1339972696318.83'
    assert d['per_class_aggregate_market_value_cny'] is None


@pytest.mark.parametrize('p,total,a,h',[('NaN',100,100,0),('1',100,50,20),('1',0,0,0)])
def test_bad_or_inconsistent_share_scope_rejected(p,total,a,h):
    with pytest.raises(ValueError):valuation_diagnostics(p,total,a,h_shares=h)
