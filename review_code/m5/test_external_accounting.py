"""Independent M5 accounting oracles: invented mechanism inputs, no real PASS.

No expected value reads production fills/NAV or production accounting helpers.
REAL-tag stand-ins below exercise contract validation only, never authenticity.
"""
from copy import deepcopy
from decimal import Decimal as D, ROUND_HALF_UP, ROUND_CEILING
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_research.execution import ExecutionBlockedError, run_backtest

ROOT = Path(__file__).resolve().parents[2]
SID = 'INVENTED_ACCOUNTING_ORACLE'
URL = 'https://example.test/independent-invented-mechanism-input'
REAL = 'ENGINEERING_ACCOUNTING_VALIDATION'
SYNTHETIC = 'ENGINEERING_REPLAY_NOT_STRATEGY_PERFORMANCE'
CASH_MODE = 'ENGINEERING_CONSERVATIVE_CASH_SCENARIO'


def fixture(tmp_path, real=False):
    cal = pd.bdate_range('2023-07-03', periods=40).strftime('%Y-%m-%d').tolist()
    meta = dict(instrument_id=SID, asset_type='STOCK', board='MAIN',
        listed_on='2010-01-04', delisted_on=None, available_at='2015-01-01T00:00:00+08:00',
        account_verified=True, industry='INVENTED', lot_size=100, tick_size=.01,
        t_plus=1, status='NORMAL', is_st=False, ipo_regime='APPROVAL')
    bars = [dict(date=day, instrument_id=SID, open=10., high=11., low=9., close=10.,
        volume=10000000, amount=100000000, upper_limit=11., lower_limit=9.,
        suspended=False, available_at=day+'T16:00:00+08:00', limit_terms_verified=True,
        limit_source_url=URL, limit_rule_available_at='2020-01-01T08:00:00+08:00',
        listing_session=3000+i, special_session=False, limit_reference_price=10.)
        for i, day in enumerate(cal)]
    actions = [dict(action_id=kind, instrument_id=SID, action_type='CASH_DIVIDEND',
        record_date=cal[i], ex_date=cal[i+1], pay_date=cal[i+2],
        modeled_cash_date=cal[i+3], available_at=cal[i-1]+'T20:00:00+08:00',
        cash_per_share=gross, cash_dividend_kind=kind,
        tax_category='ORDINARY_CASH_DIVIDEND', terms_verified=True, source_url=URL,
        settlement_mode=CASH_MODE if real else 'SYNTHETIC_SCHEDULED_SIMULATION')
        for kind, i, gross in [('ORDINARY',24,'.25'),('SPECIAL',28,'.75')]]
    fees = [dict(effective_from='2022-04-29', effective_to='2023-08-27',
        stamp_duty_sell=.001, transfer_fee_both=.00001, verified=True, source_url=URL,
        available_at='2022-04-28T21:00:00+08:00')]
    manifest = dict(purpose=SYNTHETIC, synthetic=True, data_origin='SYNTHETIC',
        account_type='DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE')
    if real:
        path = tmp_path/'contract_standin.txt'
        path.write_text('INVENTED INPUT. Tests declaration/hash checks, not real provenance.')
        manifest.update(purpose=REAL, synthetic=False, data_origin='REAL',
            performance_evidence=False, broker_ledger_verification='UNVERIFIED',
            cash_scenario=CASH_MODE, source_artifacts=[dict(path=str(path), origin='REAL',
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
    decisions = [dict(decision_date=cal[i-1], execution_date=cal[i], weights={},
        reference_prices={SID:10.}, adv20={SID:1e8}, fixed_quantities={SID:q})
        for i,q in [(21,100),(23,300),(32,200)]]
    settlements = [dict(settlement_id='MODEL20',debit_date=cal[33],amount=20.,
        terms_verified=True,source_url=URL,mode='RULE_BASED_SIMULATION')]
    return dict(calendar=cal,instruments=pd.DataFrame([meta]),bars=pd.DataFrame(bars),
        actions=pd.DataFrame(actions),tax_rules=pd.DataFrame(fees),
        tax_settlements=settlements,manifest=manifest), decisions


def execute(data, decisions, cash=100000):
    return run_backtest(data, decisions, cash, slippage_multiplier=0, engineering_replay=True)


def near(actual, expected):
    assert abs(D(str(actual))-D(str(expected))) <= D('.000001')


def assert_day(result, day, **expected):
    row = result['nav'].set_index('date').loc[day]
    for key, value in expected.items():
        near(row[key], value)


def test_handwritten_two_dividend_lots_partial_sale_late_credit_debit(tmp_path):
    data, decisions = fixture(tmp_path, real=True)
    out = execute(data, decisions)
    cal = data['calendar']
    # Buy100:1000+5+.01; buy200:2000+5+.02. No result-derived expectation.
    base = D('100000')-D('1005.01')-D('2005.02')
    assert list(out['fills'].quantity) == [100,200,100]
    assert list(out['fills'].side) == ['BUY','BUY','SELL']
    for actual, expected in zip(out['fills'].fees, ['5.01','5.02','6.01']):
        near(actual,expected)
    assert_day(out,cal[24],cash_total=base,receivables=0,cash_reserved=15,
        dividend_tax_payable=0,nav=base+3000)
    assert_day(out,cal[25],cash_total=base,receivables=75,nav=base+3075)
    assert_day(out,cal[26],cash_total=base,receivables=75)
    assert_day(out,cal[27],cash_total=base+75,receivables=0)
    assert_day(out,cal[28],cash_total=base+75,cash_reserved=60)
    assert_day(out,cal[29],cash_total=base+75,receivables=225)
    assert_day(out,cal[30],cash_total=base+75,receivables=225)
    assert_day(out,cal[31],cash_total=base+300,receivables=0)
    # 100 FIFO shares sold, (.25+.75)*100*.20=20 accrued, unsold200 potential40.
    sold_cash=base+D('300')+D('1000')-D('6.01')
    assert_day(out,cal[32],cash_total=sold_cash,dividend_tax_payable=20,
        dividend_tax_paid=0,cash_reserved=60,cash_available=sold_cash-60,
        nav=sold_cash+2000-20,hypothetical_liquidation_nav=sold_cash+2000-60)
    assert_day(out,cal[33],cash_total=sold_cash-20,dividend_tax_payable=0,
        dividend_tax_paid=20,cash_reserved=40,cash_available=sold_cash-60,
        nav=sold_cash+2000-20,hypothetical_liquidation_nav=sold_cash+2000-60)
    final_claims=out['dividend_entitlements'].query('date == @cal[-1]')
    assert final_claims.entitled_quantity.sum()==600
    assert final_claims.remaining.sum()==400
    assert out['cash_events'].actual_pay_date.dropna().empty
    assert out['cash_events'].actual_debit_date.dropna().empty
    assert out['purpose']==REAL and out['performance_evidence'] is False
    assert set(out['nav'].data_origin)=={'REAL'} and not out['nav'].synthetic.any()
    assert set(out['nav'].broker_ledger_verification)=={'UNVERIFIED'}


@pytest.mark.parametrize('cutoff',[24,25,26,27,28,32])
def test_handwritten_prefix_balances_do_not_need_future_bars(tmp_path, cutoff):
    data, decisions=fixture(tmp_path,real=True)
    data['calendar']=data['calendar'][:cutoff+1]
    last=data['calendar'][-1]
    data['bars']=data['bars'].query('date <= @last').copy()
    out=execute(data,[d for d in decisions if d['execution_date']<=last])
    expected={24:('96989.97',0,15,0,'99989.97'),25:('96989.97',75,15,0,'100064.97'),
        26:('96989.97',75,15,0,'100064.97'),27:('97064.97',0,15,0,'100064.97'),
        28:('97064.97',0,60,0,'100064.97'),32:('98283.96',0,60,20,'100263.96')}[cutoff]
    assert_day(out,last,**dict(zip(['cash_total','receivables','cash_reserved','dividend_tax_payable','nav'],expected)))


@pytest.mark.parametrize('close',[9.,10.,11.])
def test_gap_fixed_shares_reserve_known_upper_limit_not_future_close(tmp_path,close):
    data, decisions=fixture(tmp_path)
    data['actions']=pd.DataFrame(); data['tax_settlements']=[]
    data['bars'].loc[21,['open','close']]=[10.1,close]
    out=execute(data,decisions[:1])
    assert list(out['fills'].quantity)==[100]
    assert list(out['fills'].price)==[10.1]
    near(out['fills'].iloc[0].fees,'5.01')
    reserve=out['order_events'].query("event == 'RESERVE'").iloc[0]
    near(reserve.cash_reserved,'1105.01')
    near(reserve.nav,100000)


def test_fixed_intent_audit_is_boolean_true_not_nan(tmp_path):
    data,decisions=fixture(tmp_path)
    data['tax_settlements']=[]
    out=execute(data,decisions[:1])
    value=out['orders'].iloc[0].fixed_quantity_intent
    assert pd.notna(value) and value == True


def test_fixed_batch_risk_cap_limits_to_four_hundred_before_future_close(tmp_path):
    data,decisions=fixture(tmp_path)
    data['actions']=pd.DataFrame(); data['tax_settlements']=[]
    decisions[0]['fixed_quantities'][SID]=10000
    data['bars'].loc[21,['open','close']]=[10.1,11.]
    out=execute(data,decisions[:1])
    # Known band11: 400*11=4400 <5%*100000; 500*11=5500 exceeds cap.
    assert list(out['fills'].quantity)==[400]
    near(out['order_events'].query("event == 'RESERVE'").iloc[0].cash_reserved,'4405.04')
    near(out['nav'].set_index('date').loc[data['calendar'][21],'cash_total'],'95954.96')


@pytest.mark.parametrize('is_st',[None,True,'false',0])
def test_unknown_st_never_buys(tmp_path,is_st):
    data,decisions=fixture(tmp_path)
    data['tax_settlements']=[]
    data['instruments']['is_st']=pd.Series([is_st],dtype=object)
    out=execute(data,decisions[:1])
    assert out['fills'].empty
    assert 'INSTRUMENT_STATUS_DENIED' in set(out['rejected_orders'].reason)


@pytest.mark.parametrize('field,value,reason',[
    ('open',11.,'OPEN_AT_ADVERSE_LIMIT'),
    ('suspended',True,'SUSPENDED_OR_UNKNOWN_STATUS'),
    ('limit_terms_verified',False,'HISTORICAL_LIMIT_EVIDENCE_REQUIRED'),
    ('upper_limit',12.,'HISTORICAL_LIMIT_PRICE_MISMATCH'),
    ('limit_rule_available_at','2023-08-01T16:00:00+08:00','HISTORICAL_LIMIT_NOT_KNOWN_AT_OPEN')])
def test_known_bad_execution_input_rejected(tmp_path,field,value,reason):
    data,decisions=fixture(tmp_path)
    data['tax_settlements']=[]
    data['bars'].loc[21,field]=value
    out=execute(data,decisions[:1])
    assert out['fills'].empty
    assert reason in set(out['rejected_orders'].reason)


@pytest.mark.parametrize('kind',['BONUS','RIGHTS_ISSUE','MERGER','SPLIT','LIQUIDATION_PAYMENT'])
def test_unsupported_stock_actions_fail_closed(tmp_path,kind):
    data,decisions=fixture(tmp_path)
    data['actions'].loc[0,'action_type']=kind
    with pytest.raises(ExecutionBlockedError): execute(data,decisions)


def test_explicit_real_origin_cannot_be_relabelled_synthetic(tmp_path):
    data,decisions=fixture(tmp_path)
    data['manifest']['data_origin']='REAL'
    with pytest.raises(ExecutionBlockedError): execute(data,decisions)


@pytest.mark.parametrize('field,value',[
    ('synthetic',True),('data_origin','SYNTHETIC'),('purpose','ALPHA'),
    ('performance_evidence',True),('broker_ledger_verification','VERIFIED'),('source_artifacts',[])])
def test_contradictory_real_contract_rejected(tmp_path,field,value):
    data,decisions=fixture(tmp_path,real=True)
    data['manifest'][field]=value
    with pytest.raises(ExecutionBlockedError):execute(data,decisions)


def test_modified_archived_bytes_block_engine(tmp_path):
    data,decisions=fixture(tmp_path,real=True)
    Path(data['manifest']['source_artifacts'][0]['path']).write_text('changed')
    with pytest.raises(ExecutionBlockedError,match='hash'):execute(data,decisions)


def test_ordinary_entry_cannot_enable_fixed_quantity_accounting(tmp_path):
    data,decisions=fixture(tmp_path,real=True)
    with pytest.raises(ExecutionBlockedError,match='Fixed quantities'):
        run_backtest(data,decisions,100000)


def test_ordinary_entry_retains_stock_dividend_block(tmp_path):
    data,decisions=fixture(tmp_path,real=True)
    for d in decisions:
        d.pop('fixed_quantities'); d['weights']={SID:.03}
    with pytest.raises(ExecutionBlockedError,match='dividend'):
        run_backtest(data,decisions,100000,slippage_multiplier=0)


def load_script():
    spec=importlib.util.spec_from_file_location('m5_execution_external_review',ROOT/'scripts/m5_execution.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.archived_source
def test_registered_rule_artifact_hash_is_not_silently_repinned():
    module=load_script()
    rules=json.loads((ROOT/'reports/m5_execution/rules.json').read_text(encoding='utf-8'))
    case=json.loads((ROOT/'reports/m5_execution/registration.json').read_text(encoding='utf-8'))['cases'][0]
    prerequisites=[ROOT/'data/admitted_r1/phase2_v1'/part/'calendar.json' for part in ['development','validation']]
    prerequisites += [ROOT/'data/raw_m5_equity/budget.json']
    prerequisites += [ROOT/r['path'] for r in rules['sources']]
    missing=[str(p) for p in prerequisites if not p.is_file()]
    if missing:
        pytest.skip('Archived real-source builder integration unavailable; mechanism and conditional arithmetic tests still run: '+missing[0])
    budget=json.loads(prerequisites[2].read_text(encoding='utf-8'))
    wires=[r for r in budget['attempts'] if r.get('scope')=='execution' and
           r.get('label') in (case['case_id']+'_daily',case['instrument_id']+'_basic')]
    events=json.loads((ROOT/'reports/m4_data/normalized_events.json').read_text(encoding='utf-8'))['events']
    archived=[Path(r['raw_path']) for r in wires]
    archived += [Path(e['source']['raw_path']) for e in events if e['event_id'] in case['event_ids']]
    if any(not p.is_file() for p in archived):
        pytest.skip('Archived raw wire/event original unavailable for builder hash integration')
    rules['sources'][0]['sha256']='0'*64
    # A registry's declared digest is an input constraint, not a new hash to replace.
    with pytest.raises(ValueError,match='(?i)hash|digest|source'):
        module.build(case,rules)


def test_artifact_hash_validation_portable_contract(tmp_path):
    module=load_script();path=tmp_path/'invented_artifact.bin'
    path.write_bytes(b'INVENTED HASH-CONTRACT FIXTURE, NOT REAL EVIDENCE')
    with pytest.raises(ValueError,match='Registered source hash mismatch'):
        module.artifact(path,'0'*64)
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    assert module.artifact(path,expected)['sha256']==expected


def test_unknown_delisting_rights_keep_shares_and_uncertainty(tmp_path):
    data,decisions=fixture(tmp_path)
    cal=data['calendar'];data['tax_settlements']=[]
    data['actions']=pd.DataFrame([dict(action_id='UNPRICED_EXIT',instrument_id=SID,
        action_type='DELISTING',ex_date=cal[25],available_at=cal[24]+'T20:00:00+08:00',
        recovery_per_share=None)])
    out=execute(data,decisions[:2])
    assert_day(out,cal[-1],cash_total='96989.97',receivables=0,holdings_value=0,nav='96989.97')
    assert out['positions'].iloc[-1].quantity==300
    assert out['rights'].iloc[-1].entitled_quantity==300
    assert out['rights'].iloc[-1].status=='UNPRICED_DELISTED_RIGHT'
    assert bool(out['nav'].iloc[-1].valuation_uncertainty)


def test_five_failed_sales_retain_shares_no_sixth_attempt(tmp_path):
    data,decisions=fixture(tmp_path)
    data['actions']=pd.DataFrame();data['tax_settlements']=[]
    data['bars'].loc[32:37,'suspended']=True
    out=execute(data,decisions)
    sells=out['orders'].query("side == 'SELL'")
    assert list(sells.attempt)==[1,2,3,4,5]
    assert list(out['fills'].quantity)==[100,200]
    assert out['positions'].iloc[-1].quantity==300
    assert_day(out,data['calendar'][-1],cash_total='96989.97',nav='99989.97')
    assert 'SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS' in set(out['rejected_orders'].reason)


def source_scenario_oracle(case):
    """Separate conditional model arithmetic directly from archived raw inputs.

    Fees remain candidate rule assumptions until primary evidence is verified.
    This oracle cannot promote a source scenario to real settlement acceptance.
    """
    raw=json.loads((ROOT/'reports/m5_execution/raw'/f"{case['case_id']}_daily.json").read_text(encoding='utf-8'))['rows']
    all_events=json.loads((ROOT/'reports/m4_data/normalized_events.json').read_text(encoding='utf-8'))['events']
    actions=[e for e in all_events if e['event_id'] in case['event_ids'] and e['event_type'].startswith('CASH_DIVIDEND')]
    cal=[r['date'] for r in raw]
    targets=dict(case['targets'])
    cash=D('10000000');qty=0;last=D(0);pending=None;paid=D(0);payable=D(0)
    claims=0;receivable=D(0);gross=D(str(actions[0]['cash_per_share_gross'])) if actions else D(0)
    rows=[];fills=[]
    cent=lambda x:D(str(x)).quantize(D('.01'),rounding=ROUND_HALF_UP)
    sale_day=case['targets'][-1][0];debit=cal[cal.index(sale_day)+1]
    for row in raw:
        day=row['date'];old_qty=qty;new_shares=0
        if actions:
            a=actions[0]
            if day==a['ex_date']:receivable=cent(claims*gross)
            credit=cal[cal.index(a['pay_date'])+1]
            if day==credit:cash+=receivable;receivable=D(0)
        if day in targets and targets[day]!=qty:
            pending=[targets[day]-qty,0]
        if pending:
            signed=pending[0];pending[1]+=1;buy=signed>0
            ratio=D('.05') if row['isST']=='1' else D('.10')
            op=D(row['open']);upper=cent(D(row['preclose'])*(1+ratio));lower=cent(D(row['preclose'])*(1-ratio))
            blocked=row['tradestatus']!='1' or (op>=upper if buy else op<=lower)
            if buy and row['isST']=='1':blocked=True
            if not blocked:
                amount=abs(signed)*op
                commission=max(D(5),cent(amount*D('.0003')))
                stamp=cent(amount*(D('.0005') if day>='2023-08-28' else D('.001'))) if not buy else D(0)
                transfer=cent(amount*(D('.00001') if day>='2022-04-29' else D('.00002')))
                fees=commission+stamp+transfer
                if buy:
                    # Fixed cases fit independently established cash and5%cap.
                    assert abs(signed)*upper+fees<cash
                    assert (qty+signed)*upper<D('500000')
                    cash-=amount+fees;new_shares=signed
                else:
                    cash+=amount-fees
                    payable+=cent(abs(signed)*gross*D('.20'))
                qty+=signed
                fills.append(dict(date=day,quantity=abs(signed),side='BUY' if buy else 'SELL',price=float(op),fees=float(fees)))
                pending=None
            elif buy or pending[1]>=5:pending=None
        if day==debit and payable:
            cash-=payable;paid+=payable;payable=D(0)
        if actions and day==actions[0]['record_date']:claims=qty
        if row['tradestatus']=='1':last=D(row['close'])
        potential=(qty*gross*D('.20')).quantize(D('.01'),rounding=ROUND_CEILING) if claims else D(0)
        reserve=potential+payable;value=qty*last;nav=cash+value+receivable-payable
        rows.append(dict(date=day,quantity=qty,sellable_quantity=qty-new_shares,
            cash_total=cash,receivables=receivable,holdings_value=value,
            dividend_tax_payable=payable,dividend_tax_paid=paid,cash_reserved=reserve,
            potential_terminal_tax=potential,cash_available=cash-reserve,nav=nav,
            hypothetical_liquidation_nav=nav-potential,entitled_quantity=claims,unknown_right_quantity=0))
    return rows,fills


@pytest.mark.parametrize('case_id',['moutai_ordinary','moutai_special','kangmei_st'])
def test_three_registered_source_scenario_oracles_separate_from_real_acceptance(case_id):
    reg=json.loads((ROOT/'reports/m5_execution/registration.json').read_text(encoding='utf-8'))
    case=next(c for c in reg['cases'] if c['case_id']==case_id)
    rows,fills=source_scenario_oracle(case)
    evidence=ROOT/'reports/m5_execution'
    conditional=evidence/f'{case_id}_conditional_expected.csv'
    model=pd.read_csv(conditional if conditional.exists() else evidence/f'{case_id}_expected.csv').set_index('date')
    for row in rows:
        for key,value in row.items():
            if key!='date':near(model.loc[row['date'],key],value)
    prediction=evidence/f'{case_id}_conditional_predicted_fills.json'
    source_prediction=json.loads((prediction if prediction.exists() else evidence/f'{case_id}_predicted_fills.json').read_text(encoding='utf-8'))
    if isinstance(source_prediction,dict):source_prediction=source_prediction['fills']
    assert source_prediction==fills
    # Conditional expectations carry no proof of source rules, queue, or broker cash.
    results=json.loads((evidence/'results.json').read_text(encoding='utf-8'))
    outcome=next(c for c in results['cases'] if c['case']==case_id)
    assert outcome['broker_ledger_verification']=='UNVERIFIED'
    assert results['real_strategy_runs']==0 and results['performance_evidence'] is False
