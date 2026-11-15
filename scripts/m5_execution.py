"""Fixed real-source engineering cases. No strategy selection or performance metrics."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import pandas as pd
from quant_research.engineering_replay import REAL_ACCOUNTING_TAG, REAL_CASH_MODE
from quant_research.execution import run_backtest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/m5_execution'
D = Decimal

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path, value): Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str),encoding='utf-8')
def cents(value): return D(str(value)).quantize(D('.01'),rounding=ROUND_HALF_UP)
def artifact(path, expected_sha256=None):
    path=Path(path);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Registered source hash mismatch: '+str(path))
    return dict(path=str(path.resolve()),sha256=digest,origin='REAL')

def load_calendar():
    return sorted(set(read(ROOT/'data/admitted_r1/phase2_v1/development/calendar.json')+read(ROOT/'data/admitted_r1/phase2_v1/validation/calendar.json')))

def build(case, rules):
    reg=read(OUT/'registration.json');full_calendar=load_calendar()
    calendar=[d for d in full_calendar if case['start']<=d<=case['end']]
    raw_path=OUT/'raw'/(case['case_id']+'_daily.json');raw=read(raw_path)['rows']
    if [row['date'] for row in raw]!=calendar: raise ValueError('Raw bars/calendar mismatch')
    basic_path=OUT/'raw'/(case['instrument_id']+'_basic.json');basic=read(basic_path)['rows'][0]
    sid=case['instrument_id'];events=[e for e in read(ROOT/'reports/m4_data/normalized_events.json')['events'] if e['event_id'] in case['event_ids']]
    sources=[artifact(raw_path),artifact(basic_path)]
    wire=[r for r in read(ROOT/'data/raw_m5_equity/budget.json')['attempts']
          if r.get('scope')=='execution' and r.get('label') in
          (case['case_id']+'_daily', sid+'_basic')]
    if len(wire)!=2 or any(r.get('status')!='RETURNED' for r in wire):
        raise ValueError('Successful archived raw wire sources required')
    sources += [artifact(r['raw_path'], r['sha256']) for r in wire]
    fields=['date','code','open','high','low','close','preclose','volume','amount','adjustflag','tradestatus','isST']
    for record in wire:
        body=Path(record['raw_path']).read_text(encoding='utf-8')
        wire_rows=json.JSONDecoder().raw_decode(body[body.index('{'):])[0]['record']
        if record['label']==case['case_id']+'_daily':
            normalized_rows=[[r[k] for k in fields] for r in raw]
        else:
            normalized_rows=[[basic[k] for k in ['code','code_name','ipoDate','outDate','type','status']]]
        if wire_rows!=normalized_rows:raise ValueError('Normalized source differs from registered raw wire')
    sources += [artifact(ROOT/'data/admitted_r1/phase2_v1'/part/'calendar.json') for part in ['development','validation']]
    sources += [artifact(e['source']['raw_path'],e['document_hash']) for e in events]
    sources += [artifact(ROOT/r['path'],r['sha256']) for r in rules['sources']]
    bars=[];masters=[];actions=[]
    for e in events:
        if e['event_type'].startswith('CASH_DIVIDEND'):
            actions.append(dict(action_id=e['action_id'],instrument_id=sid,action_type='CASH_DIVIDEND',record_date=e['record_date'],ex_date=e['ex_date'],pay_date=e['pay_date'],cash_per_share=e['cash_per_share_gross'],available_at=e['available_at'],cash_dividend_kind=e['event_type'].split('_')[-1],tax_category='ORDINARY_CASH_DIVIDEND',terms_verified=True,source_url=e['source']['url'],document_hash=e['document_hash'],settlement_mode=REAL_CASH_MODE,modeled_cash_date=full_calendar[full_calendar.index(e['pay_date'])+1],actual_account_credit=None))
    for i,row in enumerate(raw):
        day=row['date'];st=(sid=='sh.600518' and day>='2019-05-21')
        if row['isST'] != ('1' if st else '0'): raise ValueError('Vendor/event ST conflict')
        # Previous observed session close determines today's normal reference;
        # known cash distribution adjusts the ex-date reference before opening.
        preclose=D(row['preclose']);prior=D(raw[i-1]['close']) if i else preclose
        for a in actions:
            if a['ex_date']==day: prior-=D(a['cash_per_share'])
        if i and abs(prior-preclose)>D('.011'): raise ValueError('Preclose inconsistent with known raw close/actions')
        reference=cents(prior)
        ratio=D('.05') if st else D('.10')
        available=day+'T21:00:00+08:00'
        bars.append(dict(instrument_id=sid,date=day,**{k:float(row[k]) for k in ['open','high','low','close','volume','amount']},suspended=row['tradestatus']=='0',available_at=available,upper_limit=float(cents(reference*(1+ratio))),lower_limit=float(cents(reference*(1-ratio))),limit_reference_price=float(reference),limit_terms_verified=rules.get('verified') is True,limit_source_url=rules['limit_source_url'],limit_rule_available_at=rules['limit_available_at'],listing_session_lower_bound=sum(basic['ipoDate']<=d<=day for d in full_calendar),special_session=False,limit_source_kind='CALCULATED_FROM_PRIOR_RAW_CLOSE_AND_PUBLIC_EX_TERMS',vendor_preclose=row['preclose'],raw_object_hash=artifact(raw_path)['sha256'],vendor_first_seen_at=None,availability_basis='MODELED_DAILY_CLOSE_21:00_NOT_OBSERVED_VENDOR_FIRST_SEEN'))
    # The daily vendor status is retrospective evidence, not invented historic
    # ingestion. Baseline state is anchored to the first archived window row;
    # the precise ST transition is anchored to its prior public announcement.
    masters.append(dict(instrument_id=sid,asset_type='STOCK',board='MAIN',listed_on=basic['ipoDate'],delisted_on=None,available_at=case['start']+'T21:00:00+08:00',effective_from=case['start'],account_verified=True,account_permission_basis='REGISTERED_ENGINEERING_ACCOUNT_ASSUMPTION',industry='ENGINEERING_SINGLE_ISSUER_BUCKET',lot_size=100,tick_size=.01,t_plus=1,status='NORMAL',is_st=False,ipo_regime='APPROVAL'))
    if sid=='sh.600518':
        masters.append(dict(masters[0],effective_from='2019-05-21',available_at=events[0]['available_at'],status='ST',is_st=True))
    decisions=[]
    lookup={r['date']:r for r in bars}
    for execute,target in case['targets']:
        idx=calendar.index(execute);day=calendar[idx-1]
        decisions.append(dict(decision_date=day,execution_date=execute,weights={},fixed_quantities={sid:target},reference_prices={sid:lookup[day]['close']},adv20={sid:sum(lookup[d]['amount'] for d in calendar[idx-20:idx])/20}))
    dataset=dict(calendar=calendar,bars=pd.DataFrame(bars),instruments=pd.DataFrame(masters),actions=pd.DataFrame(actions),tax_rules=pd.DataFrame(rules['fee_rows']),tax_settlements=[],manifest=dict(purpose=REAL_ACCOUNTING_TAG,data_origin='REAL',synthetic=False,performance_evidence=False,broker_ledger_verification='UNVERIFIED',cash_scenario=REAL_CASH_MODE,source_artifacts=sources,account_type='DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE',account_permission='ENGINEERING_ASSUMPTION_NOT_HISTORICAL_BROKER_PERMISSION',industry='SINGLE_ISSUER_SCENARIO_NOT_HISTORICAL_INDUSTRY_CLASSIFICATION'))
    return dataset,decisions

def independent_expected(case, dataset):
    """Independent Decimal oracle from fixed instructions/source prices only.

    Does not call engine/FIFO/rate/fee functions or inspect actual fills/NAV.
    Fees and20% short-holding tax specified in frozen rules, two lots; full
    integer batches fit10m cash/5% cap. Limits/suspensions may block a batch.
    """
    calendar=dataset['calendar'];bars=dataset['bars'].set_index('date').to_dict('index')
    actions=dataset['actions'].to_dict('records');targets=dict(case['targets'])
    cash=D('10000000');paid=payable=D(0);lots=[];claims=[];receivables=[];rows=[];orders=[];predicted=[];settlements=[];last_mark=D(0)
    sale_date=case['targets'][-1][0];debit_date=calendar[calendar.index(sale_date)+1]
    for index,day in enumerate(calendar):
        row=bars[day];qty=sum(q['remaining'] for q in lots)
        for a in actions:
            if day==a['ex_date']:
                amount=cents(sum(c['entitled_quantity'] for c in claims if c['action_id']==a['action_id'])*D(a['cash_per_share']))
                receivables.append(dict(amount=amount,date=a['modeled_cash_date']))
        for receivable in receivables[:]:
            if receivable['date']==day: cash+=receivable['amount'];receivables.remove(receivable)
        if day in targets:
            delta=targets[day]-qty
            if delta:orders.append(dict(side='BUY' if delta>0 else 'SELL',remaining=abs(delta),attempts=0))
        for order in orders[:]:
            order['attempts']+=1;buy=order['side']=='BUY';op=D(str(row['open']))
            blocked=row['suspended'] or op >= D(str(row['upper_limit'])) if buy else row['suspended'] or op <=D(str(row['lower_limit']))
            if blocked:
                if buy or order['attempts']>=5:orders.remove(order)
                continue
            quantity=order['remaining'];notional=cents(quantity*op)
            commission=max(D(5),cents(notional*D('.0003')))
            stamp=D(0) if buy else cents(notional*(D('.0005') if day>='2023-08-28' else D('.001')))
            transfer=cents(notional*(D('.00001') if day>='2022-04-29' else D('.00002')))
            fee=commission+stamp+transfer
            if buy:
                lots.append(dict(acquired_on=day,original_quantity=quantity,remaining=quantity));cash-=notional+fee
            else:
                cash+=notional-fee;left=quantity;charges={}
                for lot in lots:
                    take=min(left,lot['remaining']);lot['remaining']-=take;left-=take
                    for claim in claims:
                        if claim['acquired_on']==lot['acquired_on']:
                            taxable=min(take,claim['remaining']);claim['remaining']-=taxable
                            charges[claim['action_id']]=charges.get(claim['action_id'],D(0))+taxable*claim['gross_per_share']*D('.20')
                    if left==0:break
                payable+=sum((cents(v) for v in charges.values()),D(0))
            predicted.append(dict(date=day,side=order['side'],quantity=quantity,price=float(op),fees=float(fee)));orders.remove(order)
        if day==debit_date and payable:
            amount=payable;cash-=amount;paid+=amount;payable=D(0)
            settlements.append(dict(settlement_id=case['case_id']+'_MODELED_DEBIT',debit_date=day,amount=float(amount),terms_verified=True,source_url='https://szs.mof.gov.cn/zhengcejiedu/201509/t20150909_1455696.htm',mode='RULE_BASED_SIMULATION'))
        for action in actions:
            if day==action['record_date']:
                for lot in lots:
                    if lot['remaining']:claims.append(dict(action_id=action['action_id'],acquired_on=lot['acquired_on'],entitled_quantity=lot['remaining'],remaining=lot['remaining'],gross_per_share=D(action['cash_per_share'])))
        potential_by_action={}
        for c in claims:
            potential_by_action[c['action_id']]=potential_by_action.get(c['action_id'],D(0))+c['remaining']*c['gross_per_share']*D('.20')
        potential=sum((v.quantize(D('.01'),rounding=ROUND_CEILING) for v in potential_by_action.values()),D(0));reserve=payable+potential
        qty=sum(l['remaining'] for l in lots)
        if not row['suspended']:last_mark=D(str(row['close']))
        value=qty*last_mark;receivable=sum((r['amount'] for r in receivables),D(0));nav=cash+value+receivable-payable
        rows.append(dict(date=day,quantity=qty,sellable_quantity=sum(l['remaining'] for l in lots if l['acquired_on']<day),cash_total=float(cash),receivables=float(receivable),holdings_value=float(value),dividend_tax_payable=float(payable),dividend_tax_paid=float(paid),cash_reserved=float(reserve),potential_terminal_tax=float(potential),cash_available=float(max(D(0),cash-reserve)),nav=float(nav),hypothetical_liquidation_nav=float(nav-potential),entitled_quantity=sum(c['entitled_quantity'] for c in claims),unknown_right_quantity=0))
    return pd.DataFrame(rows),predicted,settlements

def reconcile(result, expected):
    failures=[];nav=result['nav'].set_index('date')
    for row in expected.to_dict('records'):
        day=row['date'];positions=result['positions'].query('date == @day')
        claims=result['dividend_entitlements'];entitled=claims.loc[claims.date==day,'entitled_quantity'].sum() if 'date' in claims else 0
        actual=dict(nav.loc[day]);actual.update(quantity=positions.quantity.sum(),sellable_quantity=positions.sellable_quantity.sum(),entitled_quantity=entitled,potential_terminal_tax=actual['cash_reserved']-actual['dividend_tax_payable'],unknown_right_quantity=0)
        for key,value in row.items():
            if key!='date' and abs(float(actual[key])-value)>1e-6:failures.append(dict(date=day,field=key,expected=value,actual=float(actual[key])))
    return failures

def main():
    rules_path=OUT/'rules.json'
    if not rules_path.exists():raise SystemExit('BLOCKED: historical rule source manifest missing')
    rules=read(rules_path);cases=read(OUT/'registration.json')['cases'];statuses=[]
    for case in cases:
        dataset,decisions=build(case,rules)
        expected,predicted,settlements=independent_expected(case,dataset)
        name=case['case_id']
        source_blocked=rules.get('verified') is not True
        if source_blocked:
            expected['status']='CONDITIONAL_UNVERIFIED_RULE_INPUTS_NOT_REAL_RECONCILIATION'
            expected.to_csv(OUT/(name+'_conditional_expected.csv'),index=False)
            save(OUT/(name+'_conditional_predicted_fills.json'),dict(status='CONDITIONAL_UNVERIFIED_RULE_INPUTS',fills=predicted,not_actual_fills=True))
            # The actual gate has no lawful fee admission; the independently
            # expected outcome is no fill and unchanged engineering cash.
            expected=pd.DataFrame([dict(date=d,quantity=0,sellable_quantity=0,cash_total=10000000.,receivables=0.,holdings_value=0.,dividend_tax_payable=0.,dividend_tax_paid=0.,cash_reserved=0.,potential_terminal_tax=0.,cash_available=10000000.,nav=10000000.,hypothetical_liquidation_nav=10000000.,entitled_quantity=0,unknown_right_quantity=0) for d in dataset['calendar']])
            predicted=[];settlements=[]
        dataset['tax_settlements']=settlements
        expected.to_csv(OUT/(name+'_expected.csv'),index=False)
        save(OUT/(name+'_predicted_fills.json'),predicted)
        snapshot=dict(calendar=dataset['calendar'],manifest=dataset['manifest'],decisions=decisions,tax_settlements=settlements,**{k:dataset[k].astype(object).where(dataset[k].notna(),None).to_dict('records') for k in ['instruments','bars','actions','tax_rules']})
        save(OUT/(name+'_inputs.json'),snapshot)
        result=run_backtest(dataset,decisions,10000000,slippage_multiplier=0,engineering_replay=True)
        failures=reconcile(result,expected)
        for key,table in result.items():
            if isinstance(table,pd.DataFrame):table.to_csv(OUT/(name+'_'+key+'.csv'),index=False)
        statuses.append(dict(case=name,status='BLOCKED_RULE_SOURCES' if source_blocked and not failures else 'PASS' if not failures else 'FAIL',daily_rows=len(expected),differences=failures,predicted_fills=predicted,actual_fill_count=len(result['fills']),broker_ledger_verification='UNVERIFIED'))
    save(OUT/'results.json',dict(purpose=REAL_ACCOUNTING_TAG,synthetic=False,data_origin='REAL',performance_evidence=False,real_strategy_runs=0,cases=statuses))
    print(json.dumps(statuses,indent=2))
    if any(s['status']=='FAIL' for s in statuses):raise SystemExit(1)

if __name__=='__main__': main()
