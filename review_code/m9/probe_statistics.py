"""Independent score-unit, nonlinear-difference and degeneracy checks."""
import json
import sys
import numpy as np
import pandas as pd
from independent_accounts import ROOT, D, close, sha
sys.path.insert(0,str(ROOT/'src'))
from quant_research.risk_evaluation import quadratic_utility, utility_inference, classify_utility


def main():
    a=pd.Series([.02,-.03,.01,0])
    b=pd.Series([.01,-.01,.02,0])
    expected=[D(str(x))-D('2.5')*D(str(x))**2-D(str(y))+D('2.5')*D(str(y))**2 for x,y in zip(a,b)]
    actual=quadratic_utility(a)-quadratic_utility(b)
    for x,y in zip(actual,expected):close(x,y,'u(a)-u(b)',D('1e-14'))
    assert not np.allclose(actual,quadratic_utility(a-b))
    zeros=pd.Series(np.zeros(300))
    interval=utility_inference(zeros,zeros)
    assert interval['utility_ci'] is None and classify_utility(interval)=='INCONCLUSIVE'
    for bad in ('mean_net_increment','annual_incremental_cost','daily_hurdle','p_net','p_hac'):
        assert bad not in interval
    for ci,expected in [([1,2],'DESCRIPTIVE_UTILITY_SUPPORT'),([-2,0],'NOT_SUPPORTED_CURRENT_RISK_RULE'),
                        ([0,2],'INCONCLUSIVE'),([-1,2],'INCONCLUSIVE')]:
        assert classify_utility(dict(descriptive_status='DESCRIPTIVE_INFERENCE',utility_ci=ci))==expected
    for value in [float('nan'),float('inf')]:
        try:
            quadratic_utility(pd.Series([value]))
            raise AssertionError('Invalid utility input accepted')
        except ValueError:
            pass
    out=dict(decision='PASS_INDEPENDENT_UTILITY_PROBES',author_role='INDEPENDENT_REVIEWER',
        checks=['u(a)-u(b), not u(a-b)','gamma5 arithmetic','degenerate CI remains null/INCONCLUSIVE',
                'utility fields exclude return and currency-hurdle labels','registered CI boundary states',
                'nonfinite returns rejected'],
        production_file_sha256=sha(ROOT/'src/quant_research/risk_evaluation.py'))
    (ROOT/'reports/m9_review/UTILITY_PROBES.json').write_text(json.dumps(out,indent=2)+'\n')
    print(out['decision'])


if __name__=='__main__':main()
