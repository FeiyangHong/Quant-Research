"""Historical initializer audit and byte binding, without any account runs."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from independent_accounts import ROOT, D, read, sha, close, load_stage
from independent_unscaled import calculate
from independent_risk import add_risk
sys.path.insert(0,str(ROOT/'src'))
from quant_research.data import load_dataset
from quant_research.risk_budget import initialize_fixed_scale


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--private-root',type=Path,required=True)
    args=parser.parse_args();private=args.private_root
    binding=read(ROOT/'reports/m9_risk/DATA_BINDING.json')
    for name,digest in binding['original_file_sha256'].items():
        assert sha(private/name)==digest,name
    source=load_stage(private/'data/m8_rotation/stage_v1')
    selection=read(private/'reports/m8_rotation/COHORT_SELECTION.json')
    expected=add_risk(source,calculate(source,selection,'E0',1,'2020-01-01','2021-12-31'))
    first=next(e for e in expected if e['weights'])
    assert expected[0]['weights']=={} and expected[0]['anchor']=='2019-12-31'
    assert first['anchor']=='2020-01-23' and first['release']=='2020-02-03'
    actual=read(ROOT/'reports/m9_risk/INITIAL_RISK_ANCHOR.json')
    close(actual['c'],first['risk']['alpha'],'historical independent c',D('2e-12'))
    close(actual['risk']['sigma'],first['risk']['sigma'],'historical independent sigma',D('2e-12'))
    assert actual['risk']['complete_dates']==first['risk']['complete_dates']
    assert actual['unscaled_weights']==first['weights']
    # Alter all later TR levels in memory. Calendar and order reference dates
    # remain fixed; no changed dataset or market observation is written.
    development=load_dataset(private/'data/m8_rotation/admitted_v1/development')
    changed=development.bars.copy()
    changed.loc[changed.date.gt(first['anchor']),'total_return_index']=12345.6789
    counterfactual=initialize_fixed_scale(replace(development,bars=changed))
    assert counterfactual['c']==float(actual['c'])
    assert counterfactual['risk']['input_sha256']==actual['risk']['input_sha256']
    out=dict(decision='PASS_INDEPENDENT_INITIALIZER_AND_SOURCE_IDENTITY',author_role='INDEPENDENT_REVIEWER',
        initializer_sha256=sha(ROOT/'reports/m9_risk/INITIAL_RISK_ANCHOR.json'),
        binding_sha256=sha(ROOT/'reports/m9_risk/DATA_BINDING.json'),
        original_file_hash_checks=len(binding['original_file_sha256']),
        first_anchor=first['anchor'],release=first['release'],first_base_execution=first['execution'],
        unscaled_weights={k:str(v) for k,v in first['weights'].items()},
        independent_sigma=str(first['risk']['sigma']),independent_c=str(first['risk']['alpha']),
        complete_count=first['risk']['complete_count'],window_start=first['risk']['window_return_dates'][0],
        empty_precohort_anchor_does_not_initialize=True,post_anchor_tr_perturbation_leaves_c_unchanged=True,
        source_scope='Byte identity for reused local M8 originals. No new acquisition or independent confirmation of historical vendor accuracy.',
        performance_evidence=False)
    (ROOT/'reports/m9_review/INITIALIZER_REVIEW.json').write_text(json.dumps(out,indent=2)+'\n')
    print(out['decision'],out['original_file_hash_checks'],out['independent_c'])


if __name__=='__main__':main()
