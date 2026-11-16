"""Fixed M9 evaluation of immutable accounts; no collection or strategy runs."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.evaluation import paired_inference, nav_metrics
from quant_research.risk_evaluation import quadratic_utility, utility_inference, classify_utility, account_risk_descriptions
from quant_research.provenance import write_json
from m8_evaluate import reconcile

REPORT = ROOT / "reports/m9_risk"
VARIANTS = ("VE", "CE", "VR")
PRESSURES = ("base", "cost_2x", "cost_3x", "delay_1_session")


def read(path):
    return json.loads(Path(path).read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts-root", type=Path, default=ROOT / "runs/m9_real")
    args = parser.parse_args()
    paths, registry = read(REPORT / "ACCOUNT_PATHS.json"), read(REPORT / "EXPERIMENT_REGISTRY.json")
    if len(paths) != 24 or {r["trial_id"] for r in paths} != {r["trial_id"] for r in registry["trials"]}:
        raise ValueError("The fixed24 paths must all be accounted for")
    if any(r["status"] != "COMPLETED" for r in paths):
        raise ValueError("Failed/not-run accounts must not become zero returns")
    members = [r["instrument_id"] for r in read(ROOT / "reports/m8_public/COHORT_SUMMARY.json")["members"]]
    returns, all_tables, product_returns, product_cash = {}, {}, {}, {}
    metrics, annual_accounts, annual_products, daily, realized, monthly = [], [], [], [], [], []
    for run in paths:
        folder = args.accounts_root / run["run_id"]
        for name, expected in run["private_table_hashes"].items():
            if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Changed private table: " + str(folder / name))
        tables = {name: read(folder / (name + ".json")) for name in
                  ("nav", "positions", "fills", "cash_events", "orders", "rejected_orders", "decisions", "order_events", "exposure")}
        nav = pd.DataFrame(tables["nav"]).set_index("date")
        ret = nav.nav / nav.nav.shift(1).fillna(100000)
        ret = ret - 1
        key = (run["period"], run["path"], run["variant"])
        returns[key], all_tables[key] = ret, tables
        ident = {k: run[k] for k in ("trial_id", "period", "variant", "path", "run_id")}
        day_pnl, annual, fee_map, error = reconcile(tables, 100000, members)
        cash_pnl = pd.DataFrame(day_pnl).set_index("date")[members]
        product_cash[key] = cash_pnl
        product_returns[key] = cash_pnl.div(nav.nav.shift(1).fillna(100000), axis=0)
        if not np.allclose(product_returns[key].sum(axis=1), ret, rtol=0, atol=1e-12):
            raise ValueError("Product attribution fails account daily returns")
        risk, rolling = account_risk_descriptions(ret)
        metrics.append(dict(ident, **nav_metrics(nav.reset_index(), 100000), **risk,
            final_nav_cny=float(nav.nav.iloc[-1]), mean_cash_weight=float((nav.cash_total/nav.nav).mean()),
            transaction_fees_cny=sum(x["fees"] for x in tables["fills"]),
            embedded_slippage_cny=sum(x["slippage_cost"] for x in tables["fills"]),
            traded_notional_over_mean_nav=sum(x["notional"] for x in tables["fills"])/float(nav.nav.mean()),
            order_count=len(tables["orders"]), fill_count=len(tables["fills"]),
            rejected_order_count=len(tables["rejected_orders"]),
            holding_sessions=len({x["date"] for x in tables["positions"] if x["quantity"] > 0}),
            capacity_truncated_attempts=sum(x.get("event")=="DAILY_CAPACITY" and x.get("capacity_quantity",0)<x.get("quantity_requested",0) for x in tables["order_events"]),
            passive_instrument_breach_sessions=len({x["date"] for x in tables["exposure"] if x["scope"]=="INSTRUMENT" and x["breach"]}),
            passive_gross_breach_sessions=len({x["date"] for x in tables["exposure"] if x["scope"]=="GROSS" and x["breach"]}),
            daily_attribution_max_error_cny=error))
        util = quadratic_utility(ret)
        for date, value in ret.items():
            daily.append(dict(ident, date=date, net_daily_return=float(value), utility_score=float(util.loc[date]),
                              nav_cny=float(nav.loc[date,"nav"]), cash_weight=float(nav.loc[date,"cash_total"]/nav.loc[date,"nav"])))
            if pd.notna(rolling.loc[date]):
                realized.append(dict(ident, date=date, rolling60_annualized_volatility=float(rolling.loc[date]),
                                     above_10pct=bool(rolling.loc[date]>.10)))
        prior = 100000
        for year, group in nav.groupby(nav.index.str[:4]):
            year_ret = ret.loc[group.index]
            yrisk, _ = account_risk_descriptions(year_ret)
            attributed = sum(annual[year].values())
            pnl = float(group.nav.iloc[-1])-prior
            if abs(attributed-pnl)>1e-6:
                raise ValueError("Annual product/account reconciliation fails")
            annual_accounts.append(dict(ident, year=year, **nav_metrics(group.reset_index(), prior), **yrisk,
                                         net_pnl_cny=pnl, product_pnl_cny=attributed, error_cny=attributed-pnl))
            prior = float(group.nav.iloc[-1])
            for sid in members:
                annual_products.append(dict(ident, year=year, instrument_id=sid, net_pnl_cny=annual[year][sid],
                    fees_cny=sum(v.get(sid,0) for d,v in fee_map.items() if d.startswith(year))))
        for d in tables["decisions"]:
            q = d["diagnostics"]
            monthly.append(dict(ident, anchor_date=q["signal_anchor_date"], execution_date=d["execution_date"],
                unscaled_weights=q["unscaled_weights"], risk=q["risk"], alpha_applied=q["alpha_applied"],
                fixed_c=q["fixed_c"], target_weights=d["weights"], target_cash_weight=1-sum(d["weights"].values()),
                actual_execution_close_cash_weight=float(nav.loc[d["execution_date"],"cash_total"]/nav.loc[d["execution_date"],"nav"])))
    pairs, aux, pair_months, pair_products, differences = [], [], [], [], []
    for period in ("development", "validation"):
        for pressure in PRESSURES:
            s = {v: returns[(period,pressure,v)] for v in VARIANTS}
            if any(not value.index.equals(s["VE"].index) for value in s.values()):
                raise ValueError("Complete same-date pairing required")
            du = quadratic_utility(s["VE"])-quadratic_utility(s["CE"])
            dr = s["VE"]-s["CE"]
            item = dict(period=period,path=pressure,pair="VE-CE",n_dates=len(du),
                mean_utility_difference=float(du.mean()),annualized_utility_score_difference=float(du.mean()*252),
                mean_net_return_difference=float(dr.mean()),
                absolute_mean_utility={**{v:float(quadratic_utility(x).mean()) for v,x in s.items()},"cash":0.},
                unknown_annual_incremental_fixed_cost=None,economic_confirmation="BLOCKED_HURDLE")
            if pressure == "base":
                item["utility_intervals"] = [utility_inference(s["VE"],s["CE"],block_length=b) for b in (60,20,120)]
                item["net_return_intervals"] = [paired_inference(s["VE"],s["CE"],annual_incremental_cost=None,
                    primary_capital=100000,block_length=b,repetitions=5000,seed=20261114) for b in (60,20,120)]
            pairs.append(item)
            aux.append(dict(period=period,path=pressure,pair="VR-VE",mean_net_return_difference=float((s["VR"]-s["VE"]).mean()),
                            inference="DESCRIPTIVE_ONLY_NO_AUXILIARY_CI"))
            for label,a,b in (("VE-CE","VE","CE"),("VR-VE","VR","VE")):
                delta=s[a]-s[b]
                utility_delta=quadratic_utility(s[a])-quadratic_utility(s[b])
                for month,group in delta.groupby(delta.index.str[:7]):
                    pair_months.append(dict(period=period,path=pressure,pair=label,month=month,
                        sum_net_daily_return_difference=float(group.sum()),sum_daily_utility_difference=float(utility_delta.loc[group.index].sum()),
                        mean_daily_utility_difference=float(utility_delta.loc[group.index].mean()),n_dates=len(group)))
                pdiff=product_returns[(period,pressure,a)]-product_returns[(period,pressure,b)]
                cdiff=product_cash[(period,pressure,a)]-product_cash[(period,pressure,b)]
                for year,group in pdiff.groupby(pdiff.index.str[:4]):
                    for sid in members:
                        pair_products.append(dict(period=period,path=pressure,pair=label,year=year,instrument_id=sid,
                            sum_net_daily_return_contribution=float(group[sid].sum()),cash_pnl_difference_cny=float(cdiff.loc[group.index,sid].sum()),
                            utility_attribution="NOT_ADDITIVE_BY_PRODUCT; quadratic score has cross terms"))
                ta,tb=all_tables[(period,pressure,a)],all_tables[(period,pressure,b)]
                da={d["execution_date"]:d["weights"] for d in ta["decisions"]};db={d["execution_date"]:d["weights"] for d in tb["decisions"]}
                pa={(p["date"],p["instrument_id"]):p["quantity"] for p in ta["positions"]};pb={(p["date"],p["instrument_id"]):p["quantity"] for p in tb["positions"]}
                differences.append(dict(period=period,path=pressure,pair=label,monthly_decisions=len(da),
                    target_vector_difference=sum(da[d]!=db[d] for d in da),
                    actual_position_day_difference=len({k[0] for k in set(pa)|set(pb) if pa.get(k,0)!=pb.get(k,0)})))
    divergences, private_details = [], []
    for period in ("development","validation"):
        for variant in VARIANTS:
            base=all_tables[(period,"base",variant)]
            for pressure in PRESSURES[1:]:
                other=all_tables[(period,pressure,variant)]
                a={r["date"]:r for r in base["nav"]};b={r["date"]:r for r in other["nav"]}
                changed=[d for d in a if abs(a[d]["nav"]-b[d]["nav"])>1e-9]
                pa={(x["date"],x["instrument_id"]):x["quantity"] for x in base["positions"]}
                pb={(x["date"],x["instrument_id"]):x["quantity"] for x in other["positions"]}
                position_dates=sorted({k[0] for k in set(pa)|set(pb) if pa.get(k,0)!=pb.get(k,0)})
                first=changed[0] if changed else None
                info=dict(period=period,variant=variant,path=pressure,first_nav_divergence=first,
                    first_position_divergence=position_dates[0] if position_dates else None,
                    first_day_nav_difference_cny=b[first]["nav"]-a[first]["nav"] if first else 0,
                    unchanged_anchor_targets=[d["weights"] for d in base["decisions"]]==[d["weights"] for d in other["decisions"]],
                    mechanism="EXECUTION_DATE_MOVED_ONLY" if pressure.startswith("delay") else "COMMISSION_MINIMUM_AND_SLIPPAGE_CHANGED; rounding/cash can change subsequent shares",
                    full_account_details="LOCAL_ONLY runs/m9_analysis/FIRST_DIVERGENCE_DETAIL.json")
                divergences.append(info)
                dates={first,info["first_position_divergence"]}
                private_details.append(dict(info,base_fills=[x for x in base["fills"] if x["date"] in dates],
                    pressure_fills=[x for x in other["fills"] if x["date"] in dates]))
    alpha_stats=[]
    for period in ("development","validation"):
        for variant in VARIANTS:
            rows=[x for x in monthly if x["period"]==period and x["variant"]==variant and x["path"]=="base" and x["alpha_applied"] is not None]
            alpha=pd.Series([x["alpha_applied"] for x in rows],dtype=float)
            alpha_stats.append(dict(period=period,variant=variant,nonempty_anchors=len(rows),
                alpha_one_fraction=float(alpha.eq(1).mean()),alpha_mean=float(alpha.mean()),
                alpha_quantiles={str(q):float(alpha.quantile(q)) for q in (0,.25,.5,.75,1)}))
    primary=next(x for x in pairs if x["period"]=="validation" and x["path"]=="base")
    robust=[x for x in pairs if (x["period"]=="development" and x["path"]=="base") or (x["period"]=="validation" and x["path"]!="base")]
    verdict=classify_utility(primary["utility_intervals"][0])
    robust_status="ROBUSTNESS_SIGN_CHECK_PASSED" if all(x["mean_utility_difference"]>0 for x in robust) else "CROSS_PERIOD_OR_EXECUTION_SIGN_NOT_STABLE"
    for name,rows in (("account_metrics",metrics),("annual_account_reconciliation",annual_accounts),
                     ("annual_product_pnl",annual_products),("daily_account_returns",daily),("realized_rolling60_risk",realized),
                     ("paired_month_contributions",pair_months),("paired_product_contributions",pair_products),
                     ("target_and_holdings_differences",differences)):
        pd.DataFrame(rows).to_csv(REPORT/(name+".csv"),index=False,encoding="utf-8",lineterminator="\n")
    write_json(REPORT/"RISK_SIGNALS.json",monthly)
    write_json(REPORT/"ALPHA_DISTRIBUTIONS.json",alpha_stats)
    write_json(REPORT/"EXECUTION_DIVERGENCES.json",divergences)
    write_json(ROOT/"runs/m9_analysis/FIRST_DIVERGENCE_DETAIL.json",private_details)
    write_json(REPORT/"UTILITY_EVALUATION.json",dict(gamma=5,unit="UTILITY_SCORE_PER_DAY",pairs=pairs,auxiliary=aux,
        primary_statistical_state=verdict,robustness_sign_check=robust_status,robustness_inputs=robust,
        score_is_not_return_alpha_or_cash_profit=True,unknown_fixed_fee=None,economic_confirmation="BLOCKED_HURDLE"))
    write_json(REPORT/"RESULTS_SUMMARY.json",dict(actual_accounts=24,failed=0,not_run=0,conclusion=verdict,
        robustness_sign_check=robust_status,primary=primary,total_fills=sum(x["fill_count"] for x in metrics),
        total_account_sessions=sum(x["n_sessions"] for x in metrics),max_attribution_error_cny=max(x["daily_attribution_max_error_cny"] for x in metrics),
        fixed_c=read(REPORT/"INITIAL_RISK_ANCHOR.json")["c"],source_collection_requests=0,
        no_strategy_or_parameter_search=True,no_holdout_access=True))
    print("Evaluated24 fixed accounts; utility, returns and cash units kept separate",verdict,robust_status)


if __name__ == "__main__":
    main()
