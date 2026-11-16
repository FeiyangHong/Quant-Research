"""Audit M9 targets and independently rebuild all account ledgers."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from independent_accounts import ROOT, D, read, sha, close, load_stage, review_account
from independent_unscaled import calculate
from independent_risk import add_risk


def risk_equal(observed,expected):
    for field in ('window_return_dates','complete_dates','complete_count','zero_variance'):
        assert observed[field]==expected[field],field
    assert len(observed['missing'])==len(expected['missing'])
    for field in ('sigma','alpha'):
        close(observed[field],expected[field],field,D('2e-12'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--private-root',type=Path,required=True)
    parser.add_argument('--phase',choices=['base','all'],required=True)
    args=parser.parse_args()
    stage=args.private_root/'data/m8_rotation/stage_v1'
    source=load_stage(stage)
    selection=read(args.private_root/'reports/m8_rotation/COHORT_SELECTION.json')
    admission=read(args.private_root/'reports/m8_review/HOLDING_ADMISSION.json')
    assert admission['decision']=='ADMIT_DAILY_SCREEN'
    assert admission['stage_manifest_sha256']==sha(stage/'manifest.json')
    initial_expected=add_risk(source,calculate(source,selection,'E0',1,'2020-01-01','2021-12-31'))
    first=next(e for e in initial_expected if e['weights'])
    assert first['anchor']=='2020-01-23' and first['release']=='2020-02-03' and first['execution']=='2020-02-04'
    c=first['risk']['alpha']
    initializer=read(ROOT/'reports/m9_risk/INITIAL_RISK_ANCHOR.json')
    close(initializer['c'],c,'first legal development anchor c',D('2e-12'))
    assert initializer['anchor_date']==first['anchor'] and initializer['release_date']==first['release']
    assert initializer['available_at']=='2020-02-03T21:00:00+08:00'
    risk_equal(initializer['risk'],first['risk'])
    records=read(ROOT/'reports/m9_risk/ACCOUNT_PATHS.json')
    if isinstance(records,dict): records=records['accounts']
    wanted=[r for r in records if args.phase=='all' or r['path']=='base']
    assert len(wanted)==(6 if args.phase=='base' else 24)
    cache={};summaries=[];ledgers=[]
    for record in wanted:
        key=record['period'],record['variant'],record['execution_delay']
        if key not in cache:
            start,end=('2020-01-01','2021-12-31') if record['period']=='development' else ('2022-01-01','2024-12-31')
            unscaled=calculate(source,selection,'R0' if record['variant']=='VR' else 'E0',record['execution_delay'],start,end)
            cache[key]=add_risk(source,unscaled,c if record['variant']=='CE' else None)
        expected=cache[key]
        actual=read(Path(record['private_artifact_directory'])/'decisions.json')
        assert len(actual)==len(expected),(record['trial_id'],len(actual),len(expected))
        for a,e in zip(actual,expected):
            info=a['diagnostics']
            assert a['decision_at'][:10]==e['release'] and a['execution_date']==e['execution']
            assert info['signal_anchor_date']==e['anchor'] and info['eligible']==e['eligible']
            assert info['eligible_count']==e['eligible_count'] and a['status']==e['status']
            assert info['initializer_hash']==initializer['initializer_hash']
            close(info['fixed_c'],c,'same c all dates/periods/paths',D('2e-12'))
            assert set(info['unscaled_weights'])==set(e['weights']) and set(a['weights'])==set(e['scaled_weights'])
            for sid,w in e['weights'].items():
                close(info['unscaled_weights'][sid],w,'unscaled weights',D('1e-14'))
            for sid,w in e['scaled_weights'].items():
                close(a['weights'][sid],w,'scaled weights',D('2e-12'))
                assert 0<float(a['weights'][sid])<=.35
            assert sum(a['weights'].values())<=D('1.000000000001')
            assert set(info['momentum'])==set(e['momentum'])
            for sid,score in e['momentum'].items():close(info['momentum'][sid],score,'momentum',D('1e-12'))
            if e['weights']:
                risk_equal(info['risk'],e['risk'])
                close(info['alpha_applied'],e['alpha_applied'],'applied alpha',D('2e-12'))
                assert info['risk']['anchor_date']==e['anchor']
                assert info['risk']['available_at']==e['release']+'T21:00:00+08:00'
            else:
                assert info['risk'] is None and info['alpha_applied'] is None
            assert a['ranks']=={sid:i for i,sid in enumerate(sorted(e['weights']),1)}
        summaries.append(dict(trial_id=record['trial_id'],decisions=len(expected),
            nonempty=sum(bool(e['weights']) for e in expected),
            min_sync_days=min(e['risk']['complete_count'] for e in expected if e['risk']),
            max_sigma_error=max([abs(float(a['diagnostics']['risk']['sigma'])-float(e['risk']['sigma']))
                for a,e in zip(actual,expected) if e['risk']]+[0])))
        ledgers.append(review_account(record,source))
        print(record['trial_id'],'PASS',flush=True)
    out=dict(decision='PASS_DATA_AND_ACCOUNTING',author_role='INDEPENDENT_REVIEWER',reviewer='/root/m9_independent',
        phase=args.phase,reviewed_at=datetime.now(timezone.utc).isoformat(),
        base_account_hashes={r['trial_id']:r['exported_tables'] for r in wanted if r['path']=='base'},
        private_table_hashes={r['trial_id']:r['private_table_hashes'] for r in wanted if r['path']=='base'},
        all_reviewed_account_hashes={r['trial_id']:dict(public=r['exported_tables'],private=r['private_table_hashes']) for r in wanted},
        accounts=ledgers,signals=summaries,independent_fixed_c=str(c),
        initializer_sha256=sha(ROOT/'reports/m9_risk/INITIAL_RISK_ANCHOR.json'),
        stage_manifest_sha256=sha(stage/'manifest.json'),source_admission_sha256=sha(args.private_root/'reports/m8_review/HOLDING_ADMISSION.json'),
        selection_sha256=sha(args.private_root/'reports/m8_rotation/COHORT_SELECTION.json'),
        source_table_sha256={n:sha(stage/(n+'.json')) for n in ('bars','instruments','actions','calendar','benchmark')},
        production_sha256={p.name:sha(p) for p in (ROOT/'src/quant_research').glob('*.py')},
        reviewer_code_sha256={name:sha(Path(__file__).parent/name) for name in
            ('independent_accounts.py','independent_unscaled.py','independent_risk.py','review_accounts.py')},
        method='Independent Decimal risk from raw TR/current unscaled weights. Independent 100k cash/zero-inventory ledger from source actions and audited actual fills; observed NAV never supplies an expected balance or order size.',
        limits=['Source acquisition/admission reused from M8, not independently recollected.','Full source and full lot ledgers remain local.','Daily volume is only an execution upper-bound screen.'],
        profitability_is_not_a_gate=True)
    name='BASE_INDEPENDENT_REVIEW.json' if args.phase=='base' else 'ALL_ACCOUNT_INDEPENDENT_REVIEW.json'
    (ROOT/'reports/m9_review'/name).write_text(json.dumps(out,indent=2)+'\n')
    print(name,len(wanted))


if __name__=='__main__':main()
