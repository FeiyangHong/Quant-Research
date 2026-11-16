"""Independent statistics from reconstructed ledgers; descriptive, not fee imputation."""
from collections import defaultdict
from datetime import date
import csv
import json
from pathlib import Path
import numpy as np
from independent_accounts import ROOT,D,read,sha,close


def hac(values,lag):
    values=np.atleast_2d(values)
    length=values.shape[1]
    centered=values-values.mean(axis=1)[:,None]
    long_variance=np.einsum("ij,ij->i",centered,centered)/length
    for distance in range(1,lag+1):
        covariance=np.einsum("ij,ij->i",centered[:,distance:],centered[:,:-distance])/length
        long_variance+=2*(1-distance/(lag+1))*covariance
    return np.sqrt(np.maximum(0,long_variance)/length)


def intervals(values,block):
    values=np.asarray(values,dtype=float)
    count=len(values)
    lag=max(1,int(4*(count/100)**(2/9)))
    se=hac(values,lag)[0]
    rng=np.random.Generator(np.random.PCG64(20261114))
    starts=rng.integers(0,count,size=(5000,(count+block-1)//block))
    centered=values-values.mean()
    studentized=[]
    for start in range(0,5000,100):
        indices=(starts[start:start+100,:,None]+np.arange(block))%count
        draw=centered[indices.reshape(len(indices),-1)[:,:count]]
        standard_error=hac(draw,lag)
        assert np.all(standard_error>1e-15)
        studentized.extend(draw.mean(axis=1)/standard_error)
    low,high=np.quantile(studentized,[.025,.975])
    return dict(hac_lag=lag,hac_se=float(se),ci95=[float(values.mean()-high*se),float(values.mean()-low*se)])


def concentration(contributions):
    positive=sorted(((key,value) for key,value in contributions.items() if value>0),key=lambda kv:(-kv[1],kv[0]))
    total_positive=sum(value for key,value in positive)
    magnitude=sum(abs(value) for value in contributions.values())
    top=sorted(contributions.items(),key=lambda kv:(-abs(kv[1]),kv[0]))
    return dict(total_signed=float(sum(contributions.values())),total_positive=float(total_positive),total_absolute=float(magnitude),
        largest_absolute=[dict(key=key,value=float(value)) for key,value in top[:5]],
        largest_positive_share=float(positive[0][1]/total_positive) if total_positive else None,
        top3_positive_share=float(sum(value for key,value in positive[:3])/total_positive) if total_positive else None)


def main():
    records=read(ROOT/"reports/m8_rotation/ACCOUNT_PATHS.json")
    assert len(records)==32 and all(r["status"]=="COMPLETED" for r in records)
    paired=read(ROOT/"reports/m8_rotation/PAIRED_EVALUATION.json")
    series,ledgers={},{}
    per_account=[]
    for record in records:
        key=(record["period"],record["path"],record["variant"])
        path=ROOT/"reports/m8_review/independent_ledgers"/(record["trial_id"]+".json")
        ledger=read(path)
        prior=D(100000)
        returns=[]
        peak=D(100000);drawdown=[]
        for row in ledger:
            nav=D(row["nav"]);returns.append(nav/prior-1);prior=nav
            peak=max(peak,nav);drawdown.append(nav/peak-1)
        series[key]=dict(zip([r["date"] for r in ledger],returns));ledgers[key]=ledger
        close(record["metrics"]["total_return"],prior/100000-1,"full calendar total return",D("1e-11"))
        close(record["metrics"]["max_drawdown"],min(drawdown),"drawdown with initial cash",D("1e-11"))
        span=(date.fromisoformat(ledger[-1]["date"])-date.fromisoformat(ledger[0]["date"])).days+1
        cagr=(float(prior)/100000)**(365.25/span)-1
        close(record["metrics"]["cagr"],D(str(cagr)),"calendar CAGR",D("1e-11"))
        per_account.append(dict(trial_id=record["trial_id"],sessions=len(returns),independent_ledger_sha256=sha(path),final_nav=str(prior)))
    checks=[]
    mapping=[("R0-E0",{"R0":1,"E0":-1}),("R1-E1",{"R1":1,"E1":-1}),
        ("E1-E0",{"E1":1,"E0":-1}),("R1-R0",{"R1":1,"R0":-1}),("R1-R0-E1+E0",{"R1":1,"R0":-1,"E1":-1,"E0":1})]
    primary_concentration={}
    for entry in paired:
        period,pressure,label=entry["period"],entry["path"],entry["pair"]
        coefficients=dict(mapping)[label]
        dates=list(series[period,pressure,"E0"])
        assert all(list(series[period,pressure,v])==dates for v in coefficients)
        delta=[sum(D(coef)*series[period,pressure,v][day] for v,coef in coefficients.items()) for day in dates]
        average=sum(delta)/len(delta)
        assert len(delta)==entry["n_dates"]
        close(entry["mean_daily_net_increment"],average,"paired mean",D("1e-12"))
        close(entry["signed_annual_fixed_cost_capacity_cny"],average*252*100000,"signed arithmetic capacity",D("1e-5"))
        assert entry["annual_incremental_cost"] is None and entry["economic_status"]=="BLOCKED_HURDLE"
        intervals_checked=[]
        if pressure=="base":
            assert [r["block_length"] for r in entry["descriptive_intervals"]]==[60,20,120]
            for interval in entry["descriptive_intervals"]:
                assert interval["p_net"] is None and interval["p_hac"] is None
                assert interval["daily_hurdle"] is None and interval["annual_incremental_cost"] is None
                assert interval["seed"]==20261114 and interval["repetitions"]==5000
                if label=="R0-E0":
                    expected=intervals(delta,interval["block_length"])
                    assert interval["hac_lag"]==expected["hac_lag"]
                    close(interval["hac_se"],D(str(expected["hac_se"])),"independent HAC",D("1e-12"))
                    for actual,value in zip(interval["ci95"],expected["ci95"]): close(actual,D(str(value)),"independent bootstrap-t CI",D("1e-12"))
                    intervals_checked.append(dict(block_length=interval["block_length"],**expected))
        else: assert "descriptive_intervals" not in entry
        checks.append(dict(period=period,path=pressure,pair=label,n_dates=len(delta),mean=str(average),independent_intervals=intervals_checked))
        if period=="validation" and pressure=="base" and label=="R0-E0":
            monthly,yearly=defaultdict(lambda:D(0)),defaultdict(lambda:D(0))
            for day,value in zip(dates,delta):monthly[day[:7]]+=value;yearly[day[:4]]+=value
            primary_concentration=dict(monthly_paired_return_differences=concentration(monthly),yearly_paired_return_differences=concentration(yearly),
                annual_signed_sums={k:str(v) for k,v in yearly.items()},interpretation="Sums of paired daily return differences, not compounded wealth differences")
    assert len(checks)==40
    # Independent per-product cash-PnL accounting from source-verified fills and
    # reconstructed holdings. This is a separate cash attribution measure.
    product_cash={}
    product_return_daily={}
    product_cash_daily={}
    for variant in ("R0","E0"):
        record=next(r for r in records if r["period"]=="validation" and r["path"]=="base" and r["variant"]==variant)
        path=ROOT/record["artifact_directory"]
        flows=defaultdict(lambda:D(0))
        day_flows=defaultdict(lambda:defaultdict(lambda:D(0)))
        for fill in read(path/"fills.json"):
            cash_flow=(D(str(fill["notional"])) if fill["side"]=="SELL" else -D(str(fill["notional"])))-D(str(fill["fees"]))
            flows[fill["instrument_id"]]+=cash_flow
            day_flows[fill["date"]][fill["instrument_id"]]+=cash_flow
        for event in read(path/"cash_events.json"):
            if event["event"]=="DIVIDEND_RECEIVABLE":
                flows[event["instrument_id"]]+=D(str(event["amount"]))
                day_flows[event["date"]][event["instrument_id"]]+=D(str(event["amount"]))
        last=ledgers["validation","base",variant][-1]["date"]
        position_values=defaultdict(dict)
        for position in read(path/"positions.json"):
            position_values[position["date"]][position["instrument_id"]]=D(str(position["market_value"]))
            if position["date"]==last: flows[position["instrument_id"]]+=D(str(position["market_value"]))
        close(sum(flows.values()),D(ledgers["validation","base",variant][-1]["nav"])-100000,"product cash PnL",D("1e-6"))
        product_cash[variant]=flows
        prior_values={};prior_nav=D(100000)
        product_return_daily[variant]={};product_cash_daily[variant]={}
        for ledger_day in ledgers["validation","base",variant]:
            day=ledger_day["date"]
            current=position_values[day]
            pnls={sid:current.get(sid,D(0))-prior_values.get(sid,D(0))+day_flows[day].get(sid,D(0))
                for sid in set(current)|set(prior_values)|set(day_flows[day])}
            close(sum(pnls.values()),D(ledger_day["nav"])-prior_nav,"independent daily cash attribution",D("1e-6"))
            product_return_daily[variant][day]={sid:pnl/prior_nav for sid,pnl in pnls.items()}
            product_cash_daily[variant][day]=pnls
            prior_values=current;prior_nav=D(ledger_day["nav"])
    members=set(product_cash["R0"])|set(product_cash["E0"])
    increments={sid:product_cash["R0"][sid]-product_cash["E0"][sid] for sid in members}
    primary_concentration["product_cash_pnl_difference"]=concentration(increments)
    primary_concentration["product_cash_pnl_values"]={sid:str(increments[sid]) for sid in sorted(increments)}
    return_buckets=defaultdict(lambda:D(0));cash_buckets=defaultdict(lambda:D(0));return_totals=defaultdict(lambda:D(0))
    all_members=read(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")["selected_instruments"]
    for day in product_return_daily["R0"]:
        for sid in all_members:
            delta=product_return_daily["R0"][day].get(sid,D(0))-product_return_daily["E0"][day].get(sid,D(0))
            cash_delta=product_cash_daily["R0"][day].get(sid,D(0))-product_cash_daily["E0"][day].get(sid,D(0))
            return_totals[sid]+=delta
            for width in (4,7):
                return_buckets[day[:width],sid]+=delta
                cash_buckets[day[:width],sid]+=cash_delta
    attribution_checks=0
    with (ROOT/"reports/m8_rotation/paired_product_contributions.csv").open(encoding="utf-8",newline="") as stream:
        for row in csv.DictReader(stream):
            if (row["period"],row["path"],row["pair"])!=("validation","base","R0-E0"):continue
            key=(row["bucket"],row["instrument_id"])
            close(row["sum_paired_daily_return_contribution"],return_buckets[key],"product paired return contribution",D("1e-11"))
            close(row["difference_in_cash_pnl_cny"],cash_buckets[key],"product cash contribution",D("1e-6"))
            attribution_checks+=1
    assert attribution_checks==390
    primary_concentration["product_paired_daily_return_contributions"]=concentration(return_totals)
    primary_concentration["independently_checked_product_buckets"]=attribution_checks
    out=dict(decision="PASS_INDEPENDENT_FULL_CALENDAR_EVALUATION",author_role="INDEPENDENT_REVIEWER",accounts=per_account,
        paired_checks=checks,primary_validation_concentration=primary_concentration,
        limits=["Own bootstrap-t/HAC numerically replicated primary R0-E0 in both physically separate periods, all3 registered block lengths; auxiliary comparisons audited pointwise and configuration only.",
            "Unknown annual incremental fixed cost stays null; no economic pvalue or actionable uplift conclusion. Descriptive intervals are marginal, not a new significance search.",
            "Product cash attribution and sums of paired daily-return differences use different units; concentration is reported separately."])
    (ROOT/"reports/m8_review/independent_evaluation.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(out["decision"],len(per_account),len(checks))


if __name__=="__main__":main()
