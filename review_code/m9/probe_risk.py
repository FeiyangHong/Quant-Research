"""Adversarial synthetic probes; all numerical expectations are independent."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pandas as pd

from independent_accounts import ROOT, D, close, sha
from independent_risk import risk

sys.path.insert(0,str(ROOT/'src'))
from quant_research.risk_budget import estimate_basket_risk


def sample():
    dates=pd.bdate_range('2020-01-01',periods=72).strftime('%Y-%m-%d').tolist()
    rows=[]
    value=D(100)
    for i,day in enumerate(dates):
        value*=1+D((i%7)-3)/1000
        for sid in ['a','b']:
            rows.append(dict(date=day,instrument_id=sid,total_return_index=float(value),
                available_at=day+'T21:00:00+08:00',total_return_available_at=day+'T21:00:00+08:00'))
    return dict(calendar=dates,bars=rows)


def actual(source,weights):
    return estimate_basket_risk(SimpleNamespace(calendar=source['calendar'],bars=pd.DataFrame(source['bars'])),
                               source['calendar'][60],source['calendar'][61],weights)


def compare(source,weights):
    expected=risk(source,source['calendar'][60],source['calendar'][61],weights)
    observed=actual(source,weights)
    for key in ('complete_dates','complete_count','window_return_dates','zero_variance'):
        assert observed[key]==expected[key],(key,observed[key],expected[key])
    for key in ('sigma','alpha'):
        close(observed[key],expected[key],key,D('1e-12'))
    return observed


def main():
    source=sample()
    single=compare(source,{'a':1})
    split=compare(source,{'a':.5,'b':.5})
    close(single['sigma'],D(str(split['sigma'])),'duplicate split',D('1e-14'))
    # Contrast retained as a mathematical counterexample, never an estimator candidate.
    assert D('.5')+D('.5')*(D('.5')**2+D('.5')**2)==D('.75')
    changed=copy.deepcopy(source)
    for row in changed['bars']:
        if row['date']>source['calendar'][60]: row['total_return_index']=987654321
    close(compare(changed,{'a':1})['sigma'],D(str(single['sigma'])),'future prefix',D('1e-14'))
    # Removing 15 terminal return endpoints leaves exactly 45 complete days.
    fortyfive=copy.deepcopy(source)
    for row in fortyfive['bars']:
        if row['instrument_id']=='a' and source['calendar'][46]<=row['date']<=source['calendar'][60]:
            row['total_return_available_at']='2099-01-01T21:00:00+08:00'
    assert compare(fortyfive,{'a':1})['complete_count']==45
    fortyfour=copy.deepcopy(fortyfive)
    for row in fortyfour['bars']:
        if row['instrument_id']=='a' and row['date']==source['calendar'][45]:
            row['total_return_available_at']='2099-01-01T21:00:00+08:00'
    try:
        actual(fortyfour,{'a':1})
        raise AssertionError('44 complete observations must block')
    except Exception as exc:
        assert not isinstance(exc,AssertionError)
    zero=copy.deepcopy(source)
    for row in zero['bars']: row['total_return_index']=100
    zero_out=compare(zero,{'a':1})
    assert zero_out['sigma']==0 and zero_out['alpha']==1 and zero_out['zero_variance']
    invalid_results=[]
    for invalid in [None,float('nan'),float('inf'),0,-1]:
        broken=copy.deepcopy(zero)
        for row in broken['bars']: row['total_return_index']=invalid
        try:
            actual(broken,{'a':1})
            raise AssertionError('Invalid data must not become zero risk')
        except Exception as exc:
            assert not isinstance(exc,AssertionError)
            invalid_results.append(type(exc).__name__)
    # Both start and end endpoints must be known: an unavailable starting level
    # removes the following return, even when that day's level is available.
    start_late=copy.deepcopy(source)
    for row in start_late['bars']:
        if row['date']==source['calendar'][0]: row['total_return_available_at']='2099-01-01T21:00:00+08:00'
    assert compare(start_late,{'a':1})['complete_count']==59
    out=dict(decision='PASS_INDEPENDENT_RISK_PROBES',author_role='INDEPENDENT_REVIEWER',
        probes=['raw scalar ddof1 variance','duplicate split invariance','diagonal shrinkage .75 counterexample',
                'post-anchor prefix invariance','45 synchronized observations accepted','44 blocked',
                'legal zero sigma gives alpha1','None/NaN/infinity/zero/negative TR blocked',
                'starting endpoint availability'],invalid_exceptions=invalid_results,
        production_file_sha256=sha(ROOT/'src/quant_research/risk_budget.py'),
        reviewer_code_sha256={name:sha(Path(__file__).parent/name) for name in
            ('independent_accounts.py','independent_risk.py','probe_risk.py')},
        observation_scope='Synthetic probes contain no market observations or strategy returns.')
    (ROOT/'reports/m9_review/RISK_PROBES.json').write_text(json.dumps(out,indent=2)+'\n')
    print(out['decision'],len(out['probes']))


if __name__=='__main__':main()
