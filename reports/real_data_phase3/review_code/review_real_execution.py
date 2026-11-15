"""Read-only execution audit. Never imports or invokes the strategy/execution engine.

Run after a matrix_summary.json exists. Reuses no performance/evaluation routines.
Outputs engineering checks, not evidence of minute-window liquidity or real fills.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import itertools
import json
import math
from pathlib import Path

D=Decimal
PATHS={(1,1,1,0),(2,2,1,0),(3,3,1,0),(1,0,1,0),(1,1,2,0),(1,1,1,1),(1,1,1,3)}
EXPECTED=set((c,v,s,*p) for c,v,s,p in itertools.product((10000,100000,500000,1000000),('E0','R0','E1','R1'),(False,True),PATHS))
TABLES=('orders','fills','positions','costs','order_events','share_events')

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(p):
    value=read(p)
    return value['records'] if isinstance(value,dict) else value
def dec(x):return D(str(x))
def money(x):return dec(x).quantize(D('.01'),rounding=ROUND_HALF_UP)
def tick_price(x,tick,buy):return (dec(x)/dec(tick)).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*dec(tick)
def close(a,b,tol=1e-7):return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b))<=tol
def check(ok,message,**context):
    if not ok:raise AssertionError(json.dumps(dict(check=message,**context),ensure_ascii=True))
def key(c):return(c['initial_cash'],c['variant'],c['risk_scaling'],c.get('cost_multiplier',1),c.get('slippage_multiplier',1),c.get('execution_delay',1),c.get('cash_delay_sessions',0))
def cutoff(day,clock='21:00:00'):return day+'T'+clock+'+08:00'
def qty_after(q,action):
    x=dec(q)*dec(action['share_factor']);policy=action.get('rounding_policy') or 'EXACT'
    check(policy in ('EXACT','FLOOR','CEIL'),'split rounding documented')
    if policy=='EXACT':check(x==x.to_integral_value(),'exact split integral')
    return int(x.to_integral_value(rounding=ROUND_CEILING if policy=='CEIL' else ROUND_FLOOR))

class Data:
    def __init__(self,root,repo):
        self.root=Path(root);self.repo=Path(repo);self.manifest=read(self.root/'manifest.json')
        for name,expected in self.manifest['file_sha256'].items():check(sha(self.root/name)==expected,'admitted file hash',file=name)
        self.calendar=read(self.root/'calendar.json');self.index={d:i for i,d in enumerate(self.calendar)}
        self.bars=defaultdict(list);self.masters=defaultdict(list);self.actions=defaultdict(list)
        for r in rows(self.root/'bars.json'):self.bars[r['instrument_id'],r['date']].append(r)
        for r in rows(self.root/'instruments.json'):self.masters[r['instrument_id']].append(r)
        for mapping in (self.bars,self.masters):
            for group in mapping.values():group.sort(key=lambda r:r['available_at'])
        for a in rows(self.root/'actions.json'):
            if a['action_type']=='SPLIT' and a.get('action_status')!='CANCELLED' and a.get('action_usage_scope')!='PRE_LISTING_METADATA_ONLY':
                self.actions[a['ex_date']].append(a)
        self.hash_paths=defaultdict(list)
        for p,h in self.manifest['source_snapshot_hashes'].items():self.hash_paths[h].append(Path(p))
        self.raw_cache={};self.checked_bars=set();self.adv_cache={};self.meta_cache={}
        self.policy=read(self.repo/'configs/r1_build_policy.json')
        self.rules={r['rule_id']:r for r in self.policy['historical_rules']}
    def bar(self,sid,day,asof=None):
        found=[r for r in self.bars.get((sid,day),[]) if r['available_at']<=(asof or cutoff(day))]
        return found[-1] if found else None
    def meta(self,sid,day):
        k=(sid,day)
        if k not in self.meta_cache:
            found=[r for r in self.masters.get(sid,[]) if r['available_at']<=cutoff(day,'09:30:00')]
            self.meta_cache[k]=found[-1] if found else None
        return self.meta_cache[k]
    def verify_raw(self,b):
        k=(b['instrument_id'],b['date'],b['raw_object_hash'])
        if k in self.checked_bars:return
        h=b['raw_object_hash']
        if h not in self.raw_cache:
            paths=self.hash_paths[h];check(bool(paths),'raw quote hash bound to admitted manifest',hash=h)
            p=paths[0];check(sha(p)==h,'raw quote source hash',path=str(p))
            obj=read(p);check(obj.get('status')=='SUCCESS' and obj.get('query',{}).get('kind')=='history','raw historical query')
            self.raw_cache[h]={(r[0],r[1]):dict(zip(obj['fields'],r)) for r in obj['rows']}
        source=self.raw_cache[h].get((b['date'],b['instrument_id']))
        check(source is not None,'raw quote row exists',instrument=b['instrument_id'],date=b['date'])
        check(source.get('adjustflag')=='3','raw quotes unadjusted')
        for field in ('open','high','low','close','preclose','volume','amount'):
            check(close(b[field],source[field]),'raw quote field equality',field=field,instrument=b['instrument_id'],date=b['date'],normalized=b[field],raw=source[field])
        check(b['suspended']==(source['tradestatus']!='1'),'raw suspension equality')
        self.checked_bars.add(k)
    def adv(self,sid,day):
        k=(sid,day)
        if k not in self.adv_cache:
            i=self.index[day];check(i>=19,'20 historical exchange sessions')
            values=[self.bar(sid,d,cutoff(day)) for d in self.calendar[i-19:i+1]]
            check(all(r is not None for r in values),'ADV missing historical row',instrument=sid,date=day)
            for r in values:self.verify_raw(r)
            self.adv_cache[k]=sum(dec(r['amount']) for r in values)/20
        return self.adv_cache[k]
    def limits(self,b):
        r=self.rules.get(b['rule_id']);check(r is not None,'known frozen limit rule')
        day=b['date'];check(r['effective_from']<=day<=r['effective_to'] and r['available_at']<=cutoff(day,'09:30:00'),'dated limit rule active',date=day,rule=r['rule_id'])
        check(r['instrument_id']==b['instrument_id'],'limit rule instrument')
        check(close(b['limit_reference_price'],b['preclose']),'limit uses raw ex-rights preclose')
        for field,direction in [('upper_limit',1),('lower_limit',-1)]:
            value=(dec(b['preclose'])*(1+direction*dec(r['limit_ratio']))).quantize(dec(r['tick_size']),rounding=ROUND_HALF_UP)
            check(close(value,b[field]),'limit price independently rounded',field=field,date=day)

def verify_fill(f,o,b,m,c,capacity_used,findings=None):
    sid=f['instrument_id'];day=f['date'];buy=f['side']=='BUY';q=f['quantity'];tick=m['tick_size']
    check(f['side'] in ('BUY','SELL') and int(q)==q and q>0,'positive integral fill quantity')
    check(f['instrument_id']==o['instrument_id'] and f['side']==o['side'] and day==o['execution_date'],'fill joins immutable order')
    check(q<=o['quantity'],'fill does not exceed intended units')
    check(m['asset_type']=='ETF' and m['t_plus']==1 and m['lot_size']==100,'audited ordinary ETF trading scope')
    check(m['listed_on']<=day and (not m.get('delisted_on') or m['delisted_on']>day),'listed at execution')
    if buy:
        check(m['account_verified'] is True and m.get('status','NORMAL') in ('NORMAL','ACTIVE') and not m.get('is_st') and not m.get('delisted_on'),'entry permission under hypothetical account scenario')
        check(q%100==0,'buy lots of 100')
    check(b['suspended'] is False and b['volume']>0 and b['amount']>0,'tradable daily row')
    for field in ('open','upper_limit','lower_limit'):
        check(close(float(b[field])/tick,round(float(b[field])/tick)),'price grid',field=field)
    check((b['open']<b['upper_limit']-1e-10) if buy else (b['open']>b['lower_limit']+1e-10),'adverse limit opening blocked')
    expected=tick_price(dec(b['open'])*(1+(1 if buy else -1)*D('.0003')*c.get('slippage_multiplier',1)),tick,buy)
    if not close(f['price'],expected):
        legacy=tick_price(float(b['open'])*(1+float(D('.0003')*c.get('slippage_multiplier',1)) if buy else 1-float(D('.0003')*c.get('slippage_multiplier',1))),tick,buy)
        check(findings is not None and close(f['price'],legacy),'adverse slippage and tick',expected=float(expected),actual=f['price'],instrument=sid,date=day)
        findings.append(dict(kind='DECIMAL_SLIPPAGE_TICK',date=day,instrument_id=sid,order_id=f['order_id'],expected_decimal=str(expected),actual=f['price']))
    check(b['low']-1e-10<=f['price']<=b['high']+1e-10 and b['lower_limit']-1e-10<=f['price']<=b['upper_limit']+1e-10,'fill inside OHLC and limits')
    correct_notional=money(dec(q)*dec(f['price']))
    if not close(f['notional'],correct_notional):
        check(findings is not None and close(f['notional'],money(q*f['price'])),'fill notional')
        findings.append(dict(kind='DECIMAL_NOTIONAL_ROUNDING',date=day,instrument_id=sid,order_id=f['order_id'],quantity=q,price=f['price'],expected_decimal=str(correct_notional),actual=f['notional']))
    commission=money(max(D(5),dec(f['notional'])*D('.0003'))*c.get('cost_multiplier',1))
    frozen_commission=money(max(5.,f['notional']*.0003)*c.get('cost_multiplier',1))
    check((close(f['commission'],commission) or close(f['commission'],frozen_commission)) and f['stamp_duty']==0 and f['transfer_fee']==0 and close(f['fees'],f['commission']),'registered commission and ETF tax scenario',expected=str(commission),actual=f['commission'])
    if not close(f['commission'],commission):
        check(findings is not None,'decimal fee mismatch',expected=str(commission),actual=f['commission'])
        findings.append(dict(kind='DECIMAL_COMMISSION_ROUNDING',date=day,instrument_id=sid,order_id=f['order_id'],
            expected_decimal=str(commission),actual=f['commission'],notional=f['notional'],
            cost_multiplier=c.get('cost_multiplier',1),frozen_float_unrounded=max(5.,f['notional']*.0003)*c.get('cost_multiplier',1)))
    correct_slippage=money(dec(q)*abs(dec(f['price'])-dec(b['open'])))
    if not close(f['slippage_cost'],correct_slippage):
        check(findings is not None and close(f['slippage_cost'],money(q*abs(f['price']-b['open']))),'slippage cost amount')
        findings.append(dict(kind='DECIMAL_SLIPPAGE_AMOUNT_ROUNDING',date=day,instrument_id=sid,order_id=f['order_id'],quantity=q,price=f['price'],raw_open=b['open'],expected_decimal=str(correct_slippage),actual=f['slippage_cost']))
    exposure=dec(q)*max(dec(f['price']),dec(o['reference_price']))
    used=capacity_used.get(sid,D(0))+exposure
    check(used<=D('.01')*dec(o['adv20'])+D('.00001'),'shared daily 1pct historical ADV capacity',used=str(used),cap=str(D('.01')*dec(o['adv20'])))
    capacity_used[sid]=used
    check(f['mode']=='DAILY_SCREEN_ONLY','daily simulation label')
    return float(used/(D('.01')*dec(o['adv20'])))

def verify_sale(q,total,mature):
    check(q<=mature,'T+1 no sale of same-day acquisitions',quantity=q,mature=mature)
    check(q%100==0 or q==total,'odd-lot sale only entire holding',quantity=q,total=total)

def audit_run(directory,config,data):
    directory=Path(directory);hashes=read(directory/'table_hashes.json')
    check(read(directory/'config.json')==config,'matrix and run config equality')
    tables={}
    for name in TABLES:
        check(sha(directory/(name+'.json'))==hashes[name],'run table hash',table=name)
        tables[name]=rows(directory/(name+'.json'))
    provenance=read(directory/'provenance.json')
    check(sha(directory/'source_snapshot/src/quant_research/execution.py')==provenance['source_files']['src/quant_research/execution.py'],'execution source snapshot hash')
    check(sha(data.repo/'configs/r1_build_policy.json')==provenance['source_files']['configs/r1_build_policy.json'],'frozen policy version')
    order_list=tables['orders'];orders={o['order_id']:o for o in order_list};check(len(orders)==len(order_list),'order ids unique')
    fills=tables['fills'];check(len({f['order_id'] for f in fills})==len(fills),'one commission-bearing fill per actual order')
    costs={r['order_id']:r for r in tables['costs']};check(set(costs)=={f['order_id'] for f in fills},'cost/fill bijection')
    byday=defaultdict(list);positionday=defaultdict(dict)
    for f in fills:byday[f['date']].append(f)
    for p in tables['positions']:
        check(p['instrument_id'] not in positionday[p['date']],'unique daily position')
        positionday[p['date']][p['instrument_id']]=p
    reservations={e['order_id']:e for e in tables['order_events'] if e['event']=='RESERVE'}
    previous={};counts=defaultdict(int);findings=[];max_capacity=0.;max_adv_gap=0.;run_start='2016-01-01' if config['sample']=='development' else '2022-01-01'
    for day in data.calendar:
        if day<run_start:continue
        opening={s:int(p['quantity']) for s,p in previous.items()};marks={s:p['price'] for s,p in previous.items()}
        eod=[]
        for a in data.actions.get(day,[]):
            sid=a['instrument_id'];owned=opening.get(sid,0)
            if a.get('available_at')>cutoff(day,'15:00:00' if a.get('effective_phase')=='EOD' else '09:30:00'):
                check(not owned,'no owned unknown split terms');continue
            if a.get('effective_phase')=='EOD':eod.append(a)
            else:
                opening[sid]=qty_after(owned,a)
                if sid in marks:marks[sid]/=float(a['share_factor'])
        total=dict(opening);mature=dict(opening);bought=defaultdict(int);used={}
        expected_ordering=sorted(byday[day],key=lambda f:(f['side']!='SELL',f['order_id']))
        check(byday[day]==expected_ordering,'sales precede purchases')
        for f in byday[day]:
            sid=f['instrument_id'];o=orders.get(f['order_id']);check(o is not None,'fill has immutable order')
            check(o['decision_date']<day and o['decision_at'].replace(' ','T')==cutoff(o['decision_date']),'decision known before execution')
            check(1<=o['attempt']<=5,'max five actual sell attempts')
            if o['side']=='BUY':check(o['attempt']==1 and o['parent_order_id'] is None,'no buy retry')
            adv=data.adv(sid,o['decision_date']);gap=float(dec(o['adv20'])-adv);max_adv_gap=max(max_adv_gap,gap)
            check(o['adv20']>0 and gap<=max(.00001,abs(float(adv))*1e-12),'order ADV bounded by known 20-session turnover',gap=gap)
            refbar=data.bar(sid,o['decision_date']);check(refbar is not None,'reference day known raw bar');data.verify_raw(refbar)
            basis=o['reference_basis']
            if basis=='RAW_CLOSE' and not o['parent_order_id']:
                check(close(o['reference_price'],refbar['close']) and close(o['source_reference_price'],refbar['close']),'reference raw decision close')
            elif basis=='POST_EOD_ADJUSTED':
                factors=[a for a in data.actions.get(o['decision_date'],[]) if a['instrument_id']==sid and a.get('effective_phase')=='EOD']
                factor=math.prod(float(a['share_factor']) for a in factors)
                check(bool(factors) and close(o['source_reference_price']/factor,o['reference_price']),'post EOD reference units')
            else:
                p=positionday[o['decision_date']].get(sid)
                check(p is not None and close(o['reference_price'],p['price']),'carried/retry reference matches known mark')
            b=data.bar(sid,day);m=data.meta(sid,day);check(b is not None and m is not None,'known instrument and matching daily quote')
            data.verify_raw(b);data.limits(b)
            max_capacity=max(max_capacity,verify_fill(f,o,b,m,config,used,findings))
            q=int(f['quantity'])
            if f['side']=='SELL':
                verify_sale(q,total.get(sid,0),mature.get(sid,0));mature[sid]-=q;total[sid]-=q
                counts['sell_fills']+=1;counts['odd_lot_sales']+=int(q%100!=0)
            else:
                r=reservations.get(f['order_id']);check(r is not None,'buy cash reservation exists')
                check(f['notional']+f['fees']<=r['cash_reserved']+1e-7 and r['cash_available']>=-1e-7 and close(r['cash_total'],r['cash_reserved']+r['cash_available']),'buy reference cash reservation ceiling')
                total[sid]=total.get(sid,0)+q;bought[sid]+=q;counts['buy_fills']+=1
            cost=costs[f['order_id']]
            for field in ('commission','stamp_duty','transfer_fee','slippage_cost'):check(close(cost[field],f[field]),'cost table agrees',field=field)
            check(close(cost['total_cost'],f['fees']),'total costs agree')
            counts['fills']+=1
        for sid in list(total):
            b=data.bar(sid,day)
            if b and b['suspended'] is False and b['volume']>0 and b['close']>0:
                data.verify_raw(b);marks[sid]=float(b['close'])
        for a in eod:
            sid=a['instrument_id'];total[sid]=qty_after(total.get(sid,0),a)
            if sid in marks:marks[sid]/=float(a['share_factor'])
        expected={s:q for s,q in total.items() if q}
        actual={s:p for s,p in positionday[day].items() if p['quantity']}
        check(set(expected)==set(actual),'position identities after fill and share boundaries',date=day)
        for sid,q in expected.items():
            p=actual[sid];check(q==p['quantity'],'units at T+1 boundary',date=day,instrument=sid)
            check(p['sellable_quantity']+p['locked_quantity']==q and p['locked_quantity']>=0,'locked/sellable partition')
            # All overnight lots mature for ordinary T+1 ETFs. Share rounding
            # across same-day lots is separately reviewed by inventory reviewer.
            if not bought[sid]:check(p['locked_quantity']==0,'no residual T+1 lock after overnight maturity')
            if not any(a['instrument_id']==sid for a in eod):check(p['locked_quantity']==bought[sid],'same-day acquisitions stay locked')
            check(close(p['price'],marks[sid]),'raw close mark with documented split carry',date=day,instrument=sid,expected=marks[sid],actual=p['price'])
            check(close(p['market_value'],q*marks[sid],1e-6),'position uses raw mark not total-return index')
            counts['position_rows']+=1
        previous=actual
    return dict(run_id=directory.name,status='FAIL_NUMERICAL_FINDINGS' if findings else 'PASS',findings=findings,config_key=key(config),source_hash=provenance['source_hash'],
        counts=dict(counts),max_capacity_fraction=max_capacity,max_adv_excess_cny=max_adv_gap,
        evidence_sha256={n+'.json':hashes[n] for n in TABLES},
        config_sha256=sha(directory/'config.json'),provenance_sha256=sha(directory/'provenance.json'))

def audit_period(period,run_root,data_root,repo):
    run_root=Path(run_root);summary=run_root/'matrix_summary.json'
    if not summary.exists():return dict(period=period,status='PENDING_MATRIX_COMPLETION',reviewed_runs=0)
    entries=read(summary);keys=[key(e['config']) for e in entries]
    check(len(entries)==224 and len(set(keys))==224 and set(keys)==EXPECTED,'complete registered 224 grid',period=period)
    check(not(run_root/'.runner.lock').exists(),'matrix writer finished',period=period)
    data=Data(data_root,repo);results=[]
    for i,e in enumerate(entries):
        name=e['directory'];check(Path(name).name==name,'run direct child')
        check(e['config']['sample']==period and e['config'].get('live_enabled') is False,'period and offline configuration')
        try:results.append(audit_run(run_root/name,e['config'],data))
        except Exception as error:
            print(json.dumps(dict(event='EXECUTION_REVIEW_FAILURE',period=period,run_id=name,error=str(error))),flush=True)
            return dict(period=period,status='FAIL',reviewed_runs=len(results),failure=dict(run_id=name,error=str(error)),runs=results)
        if (i+1)%28==0:print(json.dumps(dict(event='execution_review_progress',period=period,reviewed=i+1,total=224)),flush=True)
    return dict(period=period,status='FAIL_NUMERICAL_FINDINGS' if any(r['findings'] for r in results) else 'PASS',reviewed_runs=224,summary_sha256=sha(summary),
        dataset_manifest_sha256=sha(Path(data_root)/'manifest.json'),raw_quote_rows_verified=len(data.checked_bars),raw_objects_verified=len(data.raw_cache),
        counts={k:sum(r['counts'].get(k,0) for r in results) for k in ('fills','buy_fills','sell_fills','odd_lot_sales','position_rows')},
        max_capacity_fraction=max(r['max_capacity_fraction'] for r in results),runs=results)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='.')
    parser.add_argument('--development',default='runs/real_r1_development_v1')
    parser.add_argument('--validation',default='runs/real_r1_validation_v1')
    parser.add_argument('--data',default='data/admitted_r1/phase2_v1')
    parser.add_argument('--output',default='reports/real_data_phase3')
    args=parser.parse_args();repo=Path(args.repo).resolve();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    results=[]
    for period in ('development','validation'):
        results.append(audit_period(period,getattr(args,period),Path(args.data)/period,repo))
        # Expose a partial result after each completed period; never call a
        # two-period result PASS while any period is pending or failed.
        status='FAIL' if any(r['status'].startswith('FAIL') for r in results) else ('PASS' if len(results)==2 and all(r['status']=='PASS' for r in results) else 'PARTIAL')
        report=dict(status=status,review_type='ENGINEERING_REVIEW_BY_EXECUTION_IMPLEMENTER_NOT_INDEPENDENT_STATISTICAL_REVIEW',
            created_at=datetime.now(timezone.utc).isoformat(),reviewed_runs=sum(r['reviewed_runs'] for r in results),expected_runs=448,
            audit_code_sha256=sha(Path(__file__)),periods=results,
            numerical_finding_count=sum(len(run.get('findings',[])) for result in results for run in result.get('runs',[])),
            checks=['frozen table/source/policy hashes','raw vendor unadjusted OHLC/volume/amount/status equality','dated limit rules and decimal rounding',
                    'daily tradability and adverse-limit blocker','entry permission under hypothetical ordinary ETF account','100-unit buys/full-position odd-lot sales',
                    'T+1 mature inventory at each sale','raw close valuation with BOD/EOD split carry','known historical 20-session amount and shared daily 1pct capacity',
                    '3bp/minimum CNY5 per actual order with registered cost and slippage multipliers','immutable quantity and cash reservation ceiling'],
            limitations=['DAILY_SCREEN_ONLY; daily open and OHLC do not prove 09:35-10:00 availability, queue priority or executable minute volume.',
                         'Capacity is 1% of historical daily amount, not observed available liquidity.',
                         'Account permission and commission are frozen research scenarios; no actual broker permission, invoice or fill is observed.',
                         'T+1 verification uses ordinary t_plus=1 inventory boundaries; separate reviewer audits full entitlement/share allocation.',
                         'No strategy rerun, parameter adjustment, performance selection or final holdout inspection.'])
        (out/'execution_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        lines=['# 成交与执行工程复核','',f"状态：**{status}**；已实际复核 {report['reviewed_runs']}/448 条运行。",'',
               '本复核由执行实现者完成，属于工程复核；独立统计和库存审查另行出具。仅读取冻结数据及已有运行文件，没有产生新回测或修改策略。', '',
               '| 期间 | 状态 | 已审核运行 | 成交笔数 | 日持仓记录 | 最大模型容量占比 |','|---|---|---:|---:|---:|---:|']
        for r in results:
            lines.append(f"| {r['period']} | {r['status']} | {r['reviewed_runs']} | {r.get('counts',{}).get('fills','—')} | {r.get('counts',{}).get('position_rows','—')} | {r.get('max_capacity_fraction','—')} |")
        lines+=['','最大模型容量占比的分母是该笔订单所允许的历史20日日均成交金额的1%；不是占真实分钟可成交量的比例。', '',
                '核验逐笔未复权原始报价及来源哈希、开市/停牌/涨跌停、最小价格变动、权限情景、100份买入及整仓零股卖出、T+1成熟持仓、已知ADV20及同日共享容量、冻结佣金/滑点情景、不可增大的订单数量和现金预留。日持仓价格另与原始收盘价及有证据的份额转换作比较；没有用总回报指数当作货币估值。', '',
                '日频开盘及OHLC不能证明09:35–10:00真实可成交量、队列位置或排队成交。账户权限与3bp/最低5元佣金是研究情景，均不声称观察到真实券商授权、收费或个人成交。股息与完整份额分配由其他审查者复核。本报告不构成投资结论、收益确认或实盘许可。', '',
                f"复核脚本SHA256：`{report['audit_code_sha256']}`。各运行与表哈希、逐期间计数和失败详情见 `execution_review.json`。",'']
        (out/'EXECUTION_REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(status=status,reviewed_runs=report['reviewed_runs'])),flush=True)
    return 1 if status=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
