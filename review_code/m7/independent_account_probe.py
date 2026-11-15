"""M7 real-account oracle from raw eligibility, flat funding and zero cash yield.

No expected trade, share, cash or PnL value is derived from actual fills/NAV.
"""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(Path(path).read_bytes())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--expected-count',type=int,choices=[8,32],required=True)
    count=parser.parse_args().expected_count
    raw=read(ROOT/'reports/m7_review/independent_raw_probe.json')
    assert all(row['N_upper_bound']<3 for row in raw['months'])
    registry=read(ROOT/'reports/m7_cohort/EXPERIMENT_REGISTRY.json')
    paths=read(ROOT/'reports/m7_cohort/ACCOUNT_PATHS.json')
    assert len(paths)==count and len({r['trial_id'] for r in paths})==count
    pressures=['base'] if count==8 else ['base','cost_2x','cost_3x','delay_1_session']
    assert {(r['period'],r['variant'],r['path']) for r in paths}==set(itertools.product(
        ['development','validation'],['E0','R0','E1','R1'],pressures))
    source_versions=set();results=[]
    for record in paths:
        assert record['status']=='COMPLETED'
        path=ROOT/record['artifact_directory']
        for name,expected in record['exported_tables'].items():assert sha(path/name)==expected,(record['trial_id'],name)
        provenance=read(path/'provenance.json');config=read(path/'config.json')
        source_versions.add(provenance['source_hash'])
        assert hashlib.sha256(canonical(config)).hexdigest()==record['actual_config_hash']
        assert hashlib.sha256(canonical(provenance['source_files'])).hexdigest()==provenance['source_hash']
        assert provenance['data_hash']==record['data_hash']
        assert config['annual_incremental_cost'] is None and config['initial_cash']==100000
        assert config['risk_scaling'] is False and config['live_enabled'] is False
        calendar=read(ROOT/('data/admitted_r1/phase2_v1/'+record['period']+'/calendar.json'))
        begin='2016-01-01' if record['period']=='development' else '2022-01-01'
        end='2021-12-31' if record['period']=='development' else '2024-12-31'
        expected_dates=[d for d in calendar if begin<=d<=end]
        nav=read(path/'nav.json')
        assert [r['date'] for r in nav]==expected_dates
        for row in nav:
            for field in ('cash_total','cash_available','cash_withdrawable','nav','hypothetical_liquidation_nav'):
                assert Decimal(str(row[field]))==Decimal('100000'),(record['trial_id'],row['date'],field)
            for field in ('cash_reserved','holdings_value','receivables','dividend_tax_payable','dividend_tax_paid'):
                assert Decimal(str(row[field]))==0,(record['trial_id'],row['date'],field)
            assert row['valuation_uncertainty'] is False
        for table in ('orders','fills','positions','cash_events','rights','costs','rejected_orders'):
            assert read(path/(table+'.json'))==[],(record['trial_id'],table)
        decisions=read(path/'decisions.json')
        for decision in decisions:
            assert decision['weights']=={} and decision['ranks']=={}
            anchor=decision['diagnostics']['signal_anchor_date']
            if anchor<'2016-01-29':
                assert decision['status']=='CASH_COHORT_NOT_YET_KNOWN'
            else:
                e=next(r for r in raw['months'] if r['anchor']==anchor)
                assert decision['diagnostics']['eligible_count']<=e['N_upper_bound']<3
                assert decision['status']=='CASH_INSUFFICIENT_PRODUCTS'
                assert decision['decision_date']==e['release']
            assert begin<=decision['execution_date']<=end
        results.append(dict(trial_id=record['trial_id'],n_dates=len(nav),first=nav[0]['date'],last=nav[-1]['date'],
                            cash_oracle='100000.00',holdings_oracle='0',net_pnl_oracle='0.00',
                            legal_decisions=sum(d['diagnostics']['signal_anchor_date']>='2016-01-29' for d in decisions),
                            account_artifact_hashes_verified=True))
    assert len(source_versions)==1,'Code changed across registered real-account matrix'
    output=dict(status='PASS_BASE_8_INDEPENDENT_GATE' if count==8 else 'PASS_ALL32_INDEPENDENT_ACCOUNTS',
                oracle_basis='Independent raw eligibility upper bound<3 plus flat initial funding and registered zero cash yield. No actual fill/NAV-derived expectations.',
                actual_accounts=count,total_account_dates=sum(r['n_dates'] for r in results),
                source_hash=next(iter(source_versions)),accounts=results,
                proceed_registered_stresses_without_profit_gate=count==8)
    target=ROOT/'reports/m7_review'/('independent_base_checkpoint.json' if count==8 else 'independent_all32_accounts.json')
    target.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='accounts'}))


if __name__=='__main__':main()
