"""Contract/adversarial tests; invented input in contract attacks is not real evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pandas as pd
import pytest
from quant_research.engineering_replay import synthetic_fixture, REAL_ACCOUNTING_TAG, REAL_CASH_MODE
from quant_research.execution import run_backtest, ExecutionBlockedError


def test_fixed_integer_intent_survives_affordable_gap():
    data,decisions=synthetic_fixture();data['tax_settlements']=[]
    data['bars'].loc[21,['open','close']]=[10.1,10.1]
    result=run_backtest(data,decisions[:1],100000,slippage_multiplier=0,engineering_replay=True)
    assert list(result['fills'].quantity)==[200]
    assert result['fills'].iloc[0].fees==5.02
    assert list(result['orders'].fixed_quantity_intent)==[True]


def test_fixed_integer_intent_still_respects_limit_and_risk():
    data,decisions=synthetic_fixture();data['tax_settlements']=[]
    data['bars'].loc[21,['open','high','close']]=[11.,11.,11.]
    result=run_backtest(data,decisions[:1],100000,slippage_multiplier=0,engineering_replay=True)
    assert result['fills'].empty
    data['bars'].loc[21,['open','high','close']]=[10.1,11.,10.1]
    decisions[0]['fixed_quantities']={'SYNTHETIC_MAIN':10000}
    result=run_backtest(data,decisions[:1],100000,slippage_multiplier=0,engineering_replay=True)
    assert result['fills'].quantity.sum()<=400


def real_contract_attack(tmp_path):
    # Test stand-in bytes test manifest validation only; not a real-source claim.
    data,decisions=synthetic_fixture();data['tax_settlements']=[]
    path=tmp_path/'adversarial_input.txt';path.write_text('invented validation attack')
    data['manifest'].update(purpose=REAL_ACCOUNTING_TAG,synthetic=False,data_origin='REAL',performance_evidence=False,broker_ledger_verification='UNVERIFIED',cash_scenario=REAL_CASH_MODE,source_artifacts=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),origin='REAL')])
    data['actions']['settlement_mode']=REAL_CASH_MODE
    data['actions']['modeled_cash_date']=[data['calendar'][28],data['calendar'][35]]
    return data,decisions


def test_real_contract_preserves_nonperformance_origin_and_cash_delay(tmp_path):
    data,decisions=real_contract_attack(tmp_path)
    result=run_backtest(data,decisions,100000,slippage_multiplier=0,engineering_replay=True)
    assert result['purpose']==REAL_ACCOUNTING_TAG and not result['performance_evidence']
    assert not result['nav'].synthetic.any()
    assert set(result['nav'].broker_ledger_verification)=={'UNVERIFIED'}
    nav=result['nav'].set_index('date')
    assert nav.loc[data['calendar'][27],'receivables']==100
    assert nav.loc[data['calendar'][28],'receivables']==0
    assert result['cash_events'].actual_pay_date.dropna().empty


@pytest.mark.parametrize('field,value',[('synthetic',True),('data_origin','SYNTHETIC'),('performance_evidence',True),('broker_ledger_verification','VERIFIED'),('source_artifacts',[])])
def test_real_contract_bad_declarations_rejected(tmp_path,field,value):
    data,decisions=real_contract_attack(tmp_path);data['manifest'][field]=value
    with pytest.raises(ExecutionBlockedError):run_backtest(data,decisions,100000,engineering_replay=True)


def test_archive_hash_changed_rejected(tmp_path):
    data,decisions=real_contract_attack(tmp_path)
    Path(data['manifest']['source_artifacts'][0]['path']).write_text('changed')
    with pytest.raises(ExecutionBlockedError,match='hash'):run_backtest(data,decisions,100000,engineering_replay=True)


def test_actual_debit_and_early_modeled_cash_rejected(tmp_path):
    data,decisions=real_contract_attack(tmp_path)
    data['actions']['modeled_cash_date']=data['actions']['pay_date']
    with pytest.raises(ExecutionBlockedError,match='Conservative dividend'):run_backtest(data,decisions,100000,engineering_replay=True)


def test_normal_entry_still_rejects_real_fixed_quantities(tmp_path):
    data,decisions=real_contract_attack(tmp_path)
    with pytest.raises(ExecutionBlockedError,match='Fixed quantities'):run_backtest(data,decisions,100000)


@pytest.mark.parametrize('kind',['BONUS','RIGHTS_ISSUE','MERGER'])
def test_unsupported_action_never_dropped(tmp_path,kind):
    data,decisions=real_contract_attack(tmp_path);data['actions'].loc[0,'action_type']=kind
    with pytest.raises(ExecutionBlockedError,match='Unsupported corporate action'):run_backtest(data,decisions,100000,engineering_replay=True)


def test_prefix_at_record_close_matches_full_known_cash(tmp_path):
    data,decisions=real_contract_attack(tmp_path)
    full=run_backtest(data,decisions,100000,slippage_multiplier=0,engineering_replay=True)
    last=data['calendar'][24];data['calendar']=data['calendar'][:25]
    decisions=[d for d in decisions if d['execution_date']<=last]
    prefix=run_backtest(data,decisions,100000,slippage_multiplier=0,engineering_replay=True)
    fields=['date','cash_total','receivables','cash_reserved','dividend_tax_payable','nav']
    pd.testing.assert_frame_equal(full['nav'].loc[full['nav'].date<=last,fields],prefix['nav'][fields])
