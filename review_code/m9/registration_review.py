"""Review the fixed scope before the first new account is created."""
import json
import itertools
import subprocess
from datetime import datetime,timezone
from independent_accounts import ROOT, read, sha


def main():
    registry=ROOT/'reports/m9_risk/EXPERIMENT_REGISTRY.json'
    plan=ROOT/'docs/M9_PLAN.md'
    r=read(registry)
    assert sha(plan)==r['plan_sha256']
    trials=r['trials']
    expected=set(itertools.product(['development','validation'],['VE','CE','VR'],
                                   ['base','cost_2x','cost_3x','delay_1_session']))
    assert len(trials)==24 and {(t['period'],t['variant'],t['path']) for t in trials}==expected
    for t in trials:
        mult={'base':1,'cost_2x':2,'cost_3x':3,'delay_1_session':1}[t['path']]
        assert t['initial_cash']==100000 and t['cost_multiplier']==mult and t['slippage_multiplier']==mult
        assert t['execution_delay']==(2 if t['path']=='delay_1_session' else 1)
        assert t['annual_incremental_cost'] is None and t['seed']==20261114
        assert t['risk_scaling'] is True and t['signal_release_delay']==1
    for k,v in dict(window=60,min_complete=45,ddof=1,annualization=252,vol_target=.1,zero_sigma_alpha=1).items():
        assert float(r['risk_estimator'][k])==v
    assert r['primary']['gamma']==5 and r['primary']['candidate']=='VE' and r['primary']['baseline']=='CE'
    assert r['primary']['period']=='validation' and r['primary']['path']=='base'
    assert r['bootstrap']['seed']==20261114 and r['bootstrap']['repetitions']==5000
    assert r['bootstrap']['main_block']==60 and r['bootstrap']['sensitivity_blocks']==[20,120]
    assert r['bootstrap']['stress_ci'] is False
    assert r['fixed_control']['expected_anchor']=='2020-01-23' and r['fixed_control']['same_across_all_periods_and_paths']
    assert not (ROOT/'reports/m9_risk/ACCOUNT_PATHS.json').exists(), 'Registration review must precede new performance'
    # Hash both working bytes and committed bytes; no mutating Git command.
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    committed={}
    for p in (registry,plan):
        content=subprocess.check_output(['git','show',commit+':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)
        import hashlib
        committed[p.relative_to(ROOT).as_posix()]=hashlib.sha256(content).hexdigest()
        assert committed[p.relative_to(ROOT).as_posix()]==sha(p)
    out=dict(decision='PASS_INDEPENDENT_PREREGISTRATION',author_role='INDEPENDENT_REVIEWER',
        reviewed_at=datetime.now(timezone.utc).isoformat(),commit=commit,committed_file_sha256=committed,
        fixed_trials=24,new_accounts_present=False,profitability_is_not_a_gate=True,
        boundaries=['No new market collection','Independent periods','Single gamma5','Only base paired CIs',
                    'Shared first legal development anchor c','Unknown fixed cost remains null'])
    (ROOT/'reports/m9_review/PREREGISTRATION_REVIEW.json').write_text(json.dumps(out,indent=2)+'\n')
    print(out['decision'],commit)


if __name__=='__main__':main()
