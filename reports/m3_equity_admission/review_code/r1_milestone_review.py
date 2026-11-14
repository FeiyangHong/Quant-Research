"""Read-only R1 milestone arithmetic and decision review; never runs a strategy.

Reconstructs returns from 112 frozen 100k NAV tables (all seven paths), reproduces
the existing 24 exploratory bootstrap diagnostics with an independent local
implementation, and converts endpoints/intervals to signed annual fixed-cost
equivalents. Does not open market data, holdout, broker connections, or network.
Writes only the two R1 review deliverables beside this review_code directory.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "reports/real_data_phase3"
OUT = Path(__file__).resolve().parents[1]
CAPITAL, ANNUALIZER, SEED, DRAWS = 100000, 252, 20261114, 5000
FACTOR = CAPITAL * ANNUALIZER
EXPECTED_SUMMARY = "c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb"
BOUNDS = {"development": ("2016-01-01", "2021-12-31", 1461),
          "validation": ("2022-01-01", "2024-12-31", 726)}
INPUTS: dict[str, str] = {}
ERRORS: dict[str, float] = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    INPUTS[path.relative_to(ROOT).as_posix()] = sha(path)
    return json.loads(path.read_text(encoding="utf-8"))


def close(a, b, label, tol=1e-12):
    error = abs(float(a) - float(b))
    ERRORS[label] = max(ERRORS.get(label, 0.), error)
    assert math.isfinite(error) and error <= tol, (label, a, b, error)


def hac_se(samples, lag):
    values = np.atleast_2d(samples)
    n = values.shape[1]
    z = values - values.mean(axis=1, keepdims=True)
    variance = np.sum(z * z, axis=1) / n
    for k in range(1, lag + 1):
        variance += 2 * (1 - k / (lag + 1)) * np.sum(z[:, k:] * z[:, :-k], axis=1) / n
    return np.sqrt(np.maximum(variance, 0.) / n)


def reproduce_inference(d, expected):
    """Reproduce frozen definitions; no new comparisons or significance claims."""
    n, block, mean = len(d), expected["block_length"], float(np.mean(d))
    lag = max(1, math.floor(4 * (n / 100) ** (2 / 9)))
    se = float(hac_se(d, lag)[0])
    assert n >= max(120, 2 * block) and se > 1e-15
    rng = np.random.default_rng(SEED)
    nblocks = math.ceil(n / block)
    null = d - mean
    values, degenerate = [], 0
    for start in range(0, DRAWS, 250):
        size = min(250, DRAWS - start)
        starts = rng.integers(0, n, size=(size, nblocks))
        indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(size, -1)[:, :n]
        x = null[indices]
        ses = hac_se(x, lag)
        bad = ses <= 1e-15
        degenerate += int(np.sum(bad))
        values.extend(np.divide(x.mean(axis=1), ses, out=np.full(size, np.nan), where=~bad))
    if degenerate:
        assert expected["status"] == "INCONCLUSIVE_DEGENERATE_BOOTSTRAP"
        assert expected["ci95"] is None and expected["p_net"] is None
        return {"block_length": block, "status": expected["status"],
                "degenerate_replicates": degenerate, "ci95": None,
                "capacity_ci95_cny_per_year": None, "p_net_exploratory": None,
                "p_hac_exploratory": None, "hac_se": None}
    t = np.asarray(values)
    qlo, qhi = np.quantile(t, [.025, .975])
    ci = [float(mean - qhi * se), float(mean - qlo * se)]
    p = (1 + int(np.sum(t >= mean / se))) / (DRAWS + 1)
    phac = .5 * math.erfc(mean / se / math.sqrt(2))
    mde = (NormalDist().inv_cdf(.95) + NormalDist().inv_cdf(.8)) * se
    assert expected["status"] == "DESCRIPTIVE_INFERENCE"
    for a, b in zip(ci, expected["ci95"]):
        close(a, b, "bootstrap_ci")
    close(p, expected["p_net"], "bootstrap_p")
    close(phac, expected["p_hac"], "hac_p")
    close(se, expected["hac_se"], "hac_se")
    close(mde, expected["minimum_detectable_daily_effect_80pct"], "mde")
    return {"block_length": block, "status": expected["status"], "degenerate_replicates": 0,
            "ci95": ci, "capacity_ci95_cny_per_year": [v * FACTOR for v in ci],
            "p_net_exploratory": p, "p_hac_exploratory": phac, "hac_se": se,
            "hac_lag": lag, "minimum_detectable_daily_effect_80pct": mde}


def run_key(r):
    return r["period"], r["config"]["variant"], r["config"]["risk_scaling"], r["path"]


def calculate():
    assert sha(OLD / "results_summary.json") == EXPECTED_SUMMARY
    summary = read(OLD / "results_summary.json")
    review = read(OLD / "statistical_review.json")
    diagnostics = read(OLD / "independent_statistical_diagnostics_v2.json")
    years = read(OLD / "independent_year_attribution.json")
    for rel in ("docs/STRATEGY_SPEC.md", "docs/EXPERIMENT_PLAN.md", "docs/RISK_POLICY.md",
                "docs/IMPLEMENTATION_STATUS.md", "docs/DECISION_LOG.md",
                "reports/real_data_phase3/REVIEW_PACKET.md"):
        INPUTS[rel] = sha(ROOT / rel)
    assert summary["run_count"] == len(summary["runs"]) == 448
    assert summary["primary_capital_cny"] == CAPITAL
    assert summary["annual_incremental_cost_cny"] is None
    assert summary["economic_confirmation"] == "BLOCKED_HURDLE"
    assert not summary["final_holdout_accessed"]
    for obj in (diagnostics, years):
        assert obj["main_results_sha256"] == EXPECTED_SUMMARY
    selected = [r for r in summary["runs"] if r["config"]["initial_cash"] == CAPITAL]
    assert len(selected) == 112
    data = {}
    accounts = []
    for r in selected:
        key = run_key(r)
        assert key not in data
        lo, hi, count = BOUNDS[r["period"]]
        directory = ROOT / "runs" / ("real_r1_" + r["period"] + "_v2") / r["directory"]
        path = directory / "nav.json"
        assert sha(path) == r["table_hashes"]["nav"]
        nav = read(path)
        dates = [x["date"] for x in nav]
        assert len(dates) == count and dates == sorted(set(dates))
        assert all(lo <= d <= hi for d in dates)
        values = np.array([x["nav"] for x in nav], dtype=float)
        previous = np.r_[CAPITAL, values[:-1]]
        returns = values / previous - 1
        cash = np.array([x["cash_total"] / x["nav"] for x in nav])
        exposure = np.array([x["holdings_value"] / x["nav"] for x in nav])
        receivable = np.array([x["receivables"] / x["nav"] for x in nav])
        assert np.allclose(cash + exposure + receivable, 1, rtol=0, atol=1e-12)
        dd = values / np.maximum.accumulate(np.r_[CAPITAL, values])[1:] - 1
        close(float(dd.min()), r["metrics"]["max_drawdown"], "drawdown")
        close(float(cash.mean()), r["mean_cash_weight"], "cash_weight")
        close(float(exposure.mean()), r["mean_gross_exposure"], "gross_exposure")
        close(float(values[-1] / CAPITAL - 1), r["metrics"]["total_return"], "total_return")
        data[key] = {"source": r, "dates": dates, "years": np.array([int(x[:4]) for x in dates]),
                     "nav": values, "returns": returns, "daily_pnl": values - previous,
                     "cash": cash, "exposure": exposure, "drawdown": dd}
        if r["path"] == "base":
            accounts.append({"period": r["period"], "variant": r["config"]["variant"],
                "risk_scaling": r["config"]["risk_scaling"], "total_return": r["metrics"]["total_return"],
                "max_drawdown": float(dd.min()), "mean_cash_weight": float(cash.mean()),
                "mean_gross_exposure": float(exposure.mean()),
                "annual_volatility": r["metrics"]["annual_volatility"],
                "first_8pct_drawdown_date": next((d for d, v in zip(dates, dd) if v <= -.08), None),
                "first_12pct_drawdown_date": next((d for d, v in zip(dates, dd) if v <= -.12), None),
                "sessions_at_or_below_8pct_drawdown": int(np.sum(dd <= -.08)),
                "sessions_at_or_below_12pct_drawdown": int(np.sum(dd <= -.12))})

    def diff(period, candidate, baseline, scaling, path="base"):
        c, b = data[(period, candidate, scaling, path)], data[(period, baseline, scaling, path)]
        assert c["dates"] == b["dates"]
        return c, b, c["returns"] - b["returns"]

    stresses = []
    for row in review["all_primary_capital_stress_rank_contrasts"]:
        c, b, d = diff(row["period"], row["candidate"], row["baseline"], row["risk_scaling"], row["path"])
        mean = float(d.mean())
        close(mean, row["mean_daily_net_increment"], "all56_rank_means")
        stresses.append({k: row[k] for k in ("period", "candidate", "baseline", "risk_scaling", "path")} |
                        {"mean_daily_net_increment": mean, "bp_per_day": mean * 10000,
                         "signed_annual_fixed_cost_capacity_cny": mean * FACTOR})
    assert len(stresses) == 56
    main = []
    for row in review["primary_rank_contrasts_all8"]:
        c, b, d = diff(row["period"], row["candidate"], row["baseline"], row["risk_scaling"])
        mean = float(d.mean())
        inference = [reproduce_inference(d, e) for e in row["uncertainty"]["exploratory_zero_hurdle"]["blocks"]]
        annual = []
        for yr in sorted(set(c["years"])):
            mask = c["years"] == yr
            item = {"year": int(yr), "sessions": int(mask.sum()),
                    "mean_daily_net_increment": float(d[mask].mean()),
                    "pnl_difference_cny": float((c["daily_pnl"] - b["daily_pnl"])[mask].sum()),
                    "candidate_year_return": float(np.prod(1 + c["returns"][mask]) - 1)}
            expected = next(x for x in row["annual_differences"] if x["year"] == yr)
            close(item["mean_daily_net_increment"], expected["mean_daily_net_increment"], "annual_mean")
            close(item["pnl_difference_cny"], expected["pnl_difference_cny"], "annual_pnl_cny", 1e-6)
            annual.append(item)
        deletion = []
        for rule, field in (("candidate_best_year_return", "candidate_year_return"),
                            ("maximum_paired_annual_pnl_increment", "pnl_difference_cny"),
                            ("maximum_annual_mean_daily_increment", "mean_daily_net_increment")):
            removed = max(annual, key=lambda x: x[field])["year"]
            mask = c["years"] != removed
            remaining = float(d[mask].mean())
            existing = next(x for x in years["year_deletion_rows"] if x["period"] == row["period"]
                            and x["candidate"] == row["candidate"] and x["risk_scaling"] == row["risk_scaling"]
                            and x["initial_cash"] == CAPITAL and x["path"] == "base" and x["rule"] == rule)
            assert existing["removed_year"] == removed and existing["remaining_sessions"] == int(mask.sum())
            close(remaining, existing["remaining_mean_daily_net_increment"], "year_deletion_mean")
            deletion.append({"rule": rule, "removed_year": removed, "remaining_sessions": int(mask.sum()),
                             "remaining_mean_daily_net_increment": remaining,
                             "signed_annual_fixed_cost_capacity_cny": remaining * FACTOR})
        main.append({k: row[k] for k in ("period", "candidate", "baseline", "risk_scaling", "n_dates")} |
                    {"mean_daily_net_increment": mean, "bp_per_day": mean * 10000,
                     "signed_annual_fixed_cost_capacity_cny": mean * FACTOR,
                     "inference": inference, "year_deletion": deletion, "annual": annual,
                     "capacity_is_committable_budget": False})

    contrasts = []
    for row in review["primary_four_contrasts"]:
        c, b, d = diff(row["period"], row["candidate"], row["baseline"], row["risk_scaling"])
        mean = float(d.mean())
        close(mean, row["mean_daily_difference"], "four_contrast_means")
        close(float((c["exposure"] - b["exposure"]).mean()), row["mean_exposure_difference"], "contrast_exposure")
        contrasts.append({k: row[k] for k in ("period", "candidate", "baseline", "risk_scaling", "effect")} |
                         {"bp_per_day": mean * 10000,
                          "cash_difference_percentage_points": float((c["cash"] - b["cash"]).mean()) * 100,
                          "exposure_difference_percentage_points": float((c["exposure"] - b["exposure"]).mean()) * 100,
                          "drawdown_improvement_percentage_points": float(c["drawdown"].min() - b["drawdown"].min()) * 100})
    scaling = []
    for row in review["primary_scaling_effects"]:
        on = data[(row["period"], row["variant"], True, "base")]
        off = data[(row["period"], row["variant"], False, "base")]
        assert on["dates"] == off["dates"]
        mean = float((on["returns"] - off["returns"]).mean())
        close(mean, row["mean_daily_difference"], "scaling_means")
        scaling.append({"period": row["period"], "variant": row["variant"], "bp_per_day": mean * 10000,
                        "cash_difference_percentage_points": float((on["cash"] - off["cash"]).mean()) * 100,
                        "exposure_difference_percentage_points": float((on["exposure"] - off["exposure"]).mean()) * 100,
                        "drawdown_improvement_percentage_points": float(on["drawdown"].min() - off["drawdown"].min()) * 100})
    for row in review["primary_trend_ranking_interactions"]:
        _, _, ranked = diff(row["period"], "R1", "R0", row["risk_scaling"])
        _, _, equal = diff(row["period"], "E1", "E0", row["risk_scaling"])
        close(float((ranked - equal).mean()), row["mean_daily_difference"], "interaction_means")
    return {
        "schema_version": "r1-milestone-decision-1.0", "review_date": "2026-11-15",
        "reviewer": "/root/r1_milestone_review", "status": "REVIEW_COMPLETE",
        "milestone_decision": "ARCHIVE_CURRENT_CONFIGURATION",
        "etf_parameter_search": "STOP_ETF_PARAMETER_SEARCH",
        "formal_economic_status": "BLOCKED_HURDLE", "evidence_status": "DESCRIPTIVE_VALIDATION_ONLY",
        "economic_conclusion": "NO_CONFIRMED_ECONOMIC_INCREMENT", "factor_alpha_claimed": False,
        "formal_primary_p_value": None, "multiplicity_confirmed": False,
        "parameters_frozen": True, "new_r1_experiments": 0, "new_r1_proposals": [],
        "new_search_budget_consumed": 0, "final_candidate_selected": False,
        "holdout_accessed": False, "paper_started": False, "live_enabled": False,
        "r2_r3_research_requires_positive_r1_return": False,
        "r2_r3_next_step": "SEPARATE_DATA_AND_ENGINE_ADMISSION_UNDER_PHASE1_PLAN",
        "claim_of_permanent_absence_of_alpha": False,
        "scope": {"valid_runs": 448, "runs_per_period": 224, "primary_capital_cny": CAPITAL,
                  "other_capitals_cny": [10000, 500000, 1000000], "primary_nav_tables_recomputed": 112,
                  "periods": BOUNDS, "invalidated_v1_attempts_preserved": 353,
                  "all_attempts_preserved": 801, "daily_screen_only": True,
                  "r1i_evaluated": False},
        "fixed_cost": {"actual_annual_incremental_cost_cny": None,
                       "formula": "mean_daily_net_increment * 252 * 100000",
                       "one_bp_per_day_equivalent_cny_per_year": 2520,
                       "negative_means_no_sample_mean_advantage_even_at_zero_extra_cost": True,
                       "positive_point_estimate_is_committable_budget": False,
                       "shared_costs_must_not_be_double_counted": True,
                       "not_cagr_or_cash_payment_schedule": True},
        "inference_reproduction": {"blocks": [60, 20, 120], "main_block": 60,
                                   "draws_per_diagnostic": DRAWS, "seed": SEED,
                                   "interval": "marginal_95_percent",
                                   "boundary_null_incremental_fixed_cost_cny": 0,
                                   "boundary_null_is_actual_cost_assumption": False,
                                   "method": "circular_block_bootstrap_t_HAC"},
        "runtime": {"python": sys.version, "numpy": np.__version__},
        "module_decisions": [
            {"module": "ranking", "action": "ARCHIVE_CURRENT_CONFIGURATION",
             "reason": "R1-E1 changes sign across periods; unscaled validation pairs fail maximum-increment-year deletion; scaled evidence remains exploratory.",
             "stop_condition": "No further window, universe, rank-count, or filter search to rescue the observed results."},
            {"module": "trend", "action": "ARCHIVE_CURRENT_CONFIGURATION_AND_REINTERPRET_AS_EXPOSURE_CONTROL",
             "reason": "All eight main trend increments are negative; lower drawdown accompanies much larger cash allocations; no matched-cash-budget timing-alpha evidence.",
             "stop_condition": "Do not optimize the moving-average window or add hindsight regimes or drawdown stops."},
            {"module": "risk_scaling", "action": "ARCHIVE_CURRENT_R1_GENERATION_RETAIN_SHARED_RISK_CONTROL_INTERPRETATION",
             "reason": "Scaling lowers drawdown but reduces development returns, improves validation returns, and leaves all16 base drawdowns above12%.",
             "stop_condition": "Do not select a volatility target from observed profits; 10% target is not a realized-risk guarantee."}],
        "primary_rank_pairs_all8": main, "primary_stress_rank_pairs_all56": stresses,
        "primary_rank_trend_contrasts_all16": contrasts, "primary_scaling_contrasts_all8": scaling,
        "primary_accounts_all16": accounts,
        "all_capital_base_rank_contrasts_retained_from_frozen_review": review["all_capital_base_rank_contrasts"],
        "independent_checks": {"result": "PASS", "bootstrap_diagnostics_reproduced": 24,
                               "regular_diagnostics": 22, "degenerate_diagnostics_retained": 2,
                               "year_deletions_recomputed": 24, "maximum_absolute_errors": ERRORS,
                               "ci_transform_is_positive_linear_map": True,
                               "production_evaluator_imported": False},
        "limitations": ["Existing exploratory marginal intervals are not simultaneous or Holm confirmation.",
                        "HAC and block bootstrap require approximate dependence regularity; short/nonstationary samples remain uncertain.",
                        "Two development R1 block120 diagnostics remain degenerate, with null CI/p values.",
                        "448 paths and overlapping rolling windows share shocks and are not independent replications.",
                        "Annual fixed-cost equivalents are signed arithmetic endpoint conversions, not sustainable cash budgets.",
                        "Current corrected historical vintage, modeled publication/receipt clocks and daily fills retain prior data limitations.",
                        "No intraday queue validation, complete historical ETF look-through, or factor-alpha regression.",
                        "8%/12% governance reference lines are not historical exits or guarantees."],
        "input_sha256": dict(sorted(INPUTS.items())), "review_script_sha256": sha(__file__)}


def render(result):
    p = {"development": "开发", "validation": "验证"}
    s = lambda x: "开" if x else "关"
    ci = lambda vals: "未定义（退化）" if vals is None else f"[{vals[0]:,.2f}, {vals[1]:,.2f}]"
    label = lambda row: f"{p[row['period']]} / {row['candidate']}−{row['baseline']} / {s(row['risk_scaling'])}"
    lines = [
        "# R1里程碑决策审查", "",
        "2026-11-15。**归档当前R1B配置代际（ARCHIVE_CURRENT_CONFIGURATION），停止ETF参数搜索（STOP_ETF_PARAMETER_SEARCH）。** 原参数、448条有效结果和353条失效尝试均保留；本轮不运行新R1实验，不从缩放后的R0最好一行挑出赢家，不开启最终留出、paper或live。R2/R3按阶段一计划进入各自数据与工程准入，不以R1盈利为前提。",
        "",
        "停止依据：R1−E1开发为负、验证为正，尚无跨期一致优势；未缩放验证的两个排名配对删除最大增量年后转负；趋势的八个主要消融均为负；降回撤伴随现金与暴露变化，不能认定择时能力；16个10万元base账户的最大回撤均越过12%参考线。费用报价未知，正式经济确认仍为 **BLOCKED_HURDLE**。这些证据足以停止当前配置的继续投入，不能证明ETF排名或Alpha永远不存在，也不把统计不确定性改写成充分证伪。",
        "",
        "范围：开发2016—2021（1,461日）、验证2022—2024（726日），两段账户分别注资。448=两时期×四组合×两缩放×四本金×七路径，每时期224。主本金100,000元，10,000/500,000/1,000,000元仅作稳健性。2025—2026最终集保持锁定。验证是已查看的候选比较集，不是最终独立检验；R1I未获本轮实证结论。",
        "",
        "**年度增量固定费用容量：保留符号，不当作预算。** 主端点为同日净收益差的算术均值；净收益已扣模拟交易费和滑点，尚未扣未知增量固定费。下表严格用 `C*=mean_daily_net_increment×252×100000`，1bp/日等于2,520元/年；区间两端用同一正系数变换。这不是CAGR、期末利润差或真实逐日支付费用后的账户轨迹。负数表示零额外成本也无样本均值优势；正点估计及正区间下界均不是可承诺费用预算。实际ΔC未知，不能默认0、采购或据此确认；共享费用不重复扣，账户全部固定成本负担另属实际报价后的情景。",
        "",
        "| 期间 / 配对 / 缩放 | 日均增量bp | C*元/年 | 主60日块95%容量区间（元/年） |",
        "|---|---:|---:|---:|",
    ]
    for row in result["primary_rank_pairs_all8"]:
        block = next(x for x in row["inference"] if x["block_length"] == 60)
        lines.append(f"| {label(row)} | {row['bp_per_day']:.6f} | {row['signed_annual_fixed_cost_capacity_cny']:,.2f} | {ci(block['capacity_ci95_cny_per_year'])} |")
    lines += ["", "R1−E1缩放开启的验证容量点估计2,096.61元/年，开发为−237.87元/年。验证主60区间虽为正，也不覆盖跨期差异、未知费用、最终候选未冻结与多重比较限制。正式p值保持空；四族未就绪p=1只是占位，不能用探索性最小p替换。",
              "", "固定20/120日块敏感性全部展示；HAC列为原零门槛单侧诊断p，不是费用确认。主60、敏感性20/120均为5,000次、种子20261114、零假设中心化和HAC学生化的循环块bootstrap。区间是边际95%，不能当同时区间；短样本、非平稳及长期全现金/相同持仓区段使有效信息少于名义日数。", "",
              "| 期间 / 配对 / 缩放 | 20日块容量区间元/年 | 120日块容量区间元/年 | HAC探索p |",
              "|---|---:|---:|---:|"]
    for row in result["primary_rank_pairs_all8"]:
        bs = {x["block_length"]: x for x in row["inference"]}
        lines.append(f"| {label(row)} | {ci(bs[20]['capacity_ci95_cny_per_year'])} | {ci(bs[120]['capacity_ci95_cny_per_year'])} | {bs[60]['p_hac_exploratory']:.6f} |")
    lines += ["", "开发R1−E1两种缩放的120日块各有1次退化重抽样，维持INCONCLUSIVE_DEGENERATE_BOOTSTRAP及空区间/p，未丢弃后重抽。验证R0缩放开启的60日区间跨零、120日区间为正；HAC p约0.073，显示方法敏感性。不能选择块长证明优势。", "",
              "**费用压力及删最佳年。** 2×/3×为已冻结的费用/滑点路径，保留真实法定税制；成交、现金和整手非线性使结果可非单调。下表同时保留A=候选最高年度复合收益、B=最大配对年度人民币贡献，两边删除同年日期，不重跑或重新复利拼接。第三规则（最大年度日均增量）在这8组与B同年，机器文件保留全部24条。压力为bp/日，删除列为年/剩余bp/日。", "",
              "| 期间 / 配对 / 缩放 | 2× | 3× | A：删候选最佳年 | B：删最大增量年 |",
              "|---|---:|---:|---:|---:|"]
    for row in result["primary_rank_pairs_all8"]:
        matching = [x for x in result["primary_stress_rank_pairs_all56"] if all(x[k] == row[k] for k in ("period", "candidate", "risk_scaling"))]
        stress = {x["path"]: x for x in matching}
        a, b = row["year_deletion"][:2]
        lines.append(f"| {label(row)} | {stress['cost2_slip2']['bp_per_day']:.6f} | {stress['cost3_slip3']['bp_per_day']:.6f} | {a['removed_year']} / {a['remaining_mean_daily_net_increment']*10000:.6f} | {b['removed_year']} / {b['remaining_mean_daily_net_increment']*10000:.6f} |")
    lines += ["", "未缩放验证R0−E0在3×压力转负；未缩放验证R0−E0、R1−E1删除B年均转负。缩放验证两配对压力和删年仍为正的有利证据保留，但开发缩放R0删除最佳年转负、R1本就为负。2016—2017排名差为零、验证E1/R1在2022全年现金且排名差为零，不能把这些共同路径计作独立机制验证。其余零滑点、执行延迟和现金延迟全部56条主本金配对及32条四本金base配对均保留在机器文件，并引用原448全矩阵。", "",
              "**排名、趋势与风险缩放分别解释。** 排名比较固定趋势/缩放规则：R0−E0或R1−E1。相同风险规则不等于实现敞口、波动、风格完全相同；开缩放后每条组合用自身协方差与权重，排名增量含选择和其风险/执行联动。下表补充排名比较的现金、暴露和回撤差；回撤改善是候选最大回撤减基线最大回撤，正数表示回撤较浅，不是逐日收益归因。现金与总敞口之和可能略低于100%，差额为已登记应收权益。", "",
              "| 期间 / 排名配对 / 缩放 | 现金差百分点 | 总敞口差百分点 | 最大回撤改善百分点 |",
              "|---|---:|---:|---:|"]
    for row in result["primary_rank_trend_contrasts_all16"]:
        if row["effect"].startswith("rank"):
            lines.append(f"| {label(row)} | {row['cash_difference_percentage_points']:.2f} | {row['exposure_difference_percentage_points']:.2f} | {row['drawdown_improvement_percentage_points']:.2f} |")
    lines += ["", "趋势比较E1−E0、R1−R0；下表列出8项全部趋势增量及现金/敞口/回撤差。", "",
              "| 期间 / 趋势配对 / 缩放 | 日均增量bp | 现金差百分点 | 总敞口差百分点 | 最大回撤改善百分点 |",
              "|---|---:|---:|---:|---:|"]
    for row in result["primary_rank_trend_contrasts_all16"]:
        if row["effect"].startswith("trend"):
            lines.append(f"| {label(row)} | {row['bp_per_day']:.6f} | {row['cash_difference_percentage_points']:.2f} | {row['exposure_difference_percentage_points']:.2f} | {row['drawdown_improvement_percentage_points']:.2f} |")
    lines += ["", "八项趋势增量全负；验证R1缩放开启只约19.49%平均总敞口、80.51%现金。开发72次月度决策关闭趋势26次，验证36次中关闭25次。降回撤是可观测风险配置结果，尚无同现金/同风险预算对照证明时点预测；不把高现金、零现金收益基线或事后波动匹配变成择时Alpha。", "",
              "缩放的定义为同变体“开−关”，所有8项保留：", "",
              "| 期间 / 变体 | 日均增量bp | 现金差百分点 | 总敞口差百分点 | 最大回撤改善百分点 |",
              "|---|---:|---:|---:|---:|"]
    for row in result["primary_scaling_contrasts_all8"]:
        lines.append(f"| {p[row['period']]} / {row['variant']} | {row['bp_per_day']:.6f} | {row['cash_difference_percentage_points']:.2f} | {row['exposure_difference_percentage_points']:.2f} | {row['drawdown_improvement_percentage_points']:.2f} |")
    lines += ["", "缩放在开发付出收益、在验证减少损失，同时增加现金并降低回撤；10%是目标而非实现波动或回撤保证。排名、趋势、缩放、年份与ETF持仓解释高度重叠，不能把这些表的增量求和称为总Alpha。日收益恒等式`(R1−E1)−(R0−E0)=(R1−R0)−(E1−E0)`中的交互项已有非零值；本轮没有独立因子Alpha回归，也缺完整历史成分穿透。", "",
              "**8%/12%风险治理参考线与真实路径。** 下表为主要本金base的16条实际历史模拟路径，回撤保留负号。所有16条均曾低于−12%；验证回撤绝对值20.05%—41.71%，R1开/关为20.05%/29.97%。8%用于研究预警，12%是将来paper暂停新增风险并复核的参考线，不是历史止损或最大损失承诺；本轮没有据此修改历史路径，也未启动paper。首次越线日期和处于越线区间日数见JSON。", "",
              "| 期间 / 变体 / 缩放 | 累计净收益 | 平均总敞口 | 平均现金 | 实现年化波动 | 最大回撤 |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in result["primary_accounts_all16"]:
        lines.append(f"| {p[row['period']]} / {row['variant']} / {s(row['risk_scaling'])} | {row['total_return']:.2%} | {row['mean_gross_exposure']:.2%} | {row['mean_cash_weight']:.2%} | {row['annual_volatility']:.2%} | {row['max_drawdown']:.2%} |")
    lines += ["", "**模块处置与停止条件。**", "",
              "| 模块 | 本轮处置 | 不能继续用什么方式挽救 |",
              "|---|---|---|",
              "| 排名 | 归档当前配置；保留缩放验证的正结果和开发/删年负结果 | 不扫描动量窗、top-k、产品池或新过滤器；不将R0缩放最好一行升级为已确认候选 |",
              "| 趋势 | 归档当前配置；解释收窄为伴随现金的风险配置 | 不调均线窗、追加事后牛熊条件或回撤停开以救收益；暂无独立择时证据 |",
              "| 风险缩放 | 归档R1当前代际；固定规则作为风控设计记录保留 | 不优化目标波动、协方差或风险阈值；不把降险视作因子Alpha或12%可守住的证据 |",
              "",
              "本轮无新R1实验提案、无新增搜索额度消耗。未来若有独立、明确、可证伪的机制证据，须先提出有限设计；凡依据已看验证结果形成的新方案，只能标POST_VALIDATION_EXPLORATORY_PROPOSAL，另行登记审查，不能重标为事前方案或自动执行。当前没有充分新增依据，优先把资源移至原计划R2/R3。归档是停止当前配置的资源决策；正式BLOCKED_HURDLE与统计不确定性仍分别保留。", "",
              "**独立复算与复现。** 本脚本不导入生产评估器，从112份10万元冻结NAV重建全部56个排名压力配对，复核16账户现金/敞口/回撤、8组主排名、16项排名/趋势对照、8项缩放、4项交互与24个删年结果。24项原bootstrap诊断复现（22正常、2退化），容量是相同端点和区间的正线性换算，不是新假设检验。表内四舍五入仅用于展示，JSON保留完整精度、输入/脚本SHA256及最大数值误差。", "",
              "在仓库根目录执行：", "", "```powershell",
              ".venv\\Scripts\\python.exe reports/m3_equity_admission/review_code/r1_milestone_review.py", "```", "",
              "只读取固定2016—2024账户表与既有报告，写本目录的两个R1产物，不运行策略或访问网络。输入哈希绑定审查时字节；根状态/日志后续追加可能改变其文档哈希，冻结结果主摘要必须保持原值。原报告、账簿、失败历史、参数与生产代码均不改动。", "",
              f"- 冻结448结果摘要SHA256：`{EXPECTED_SUMMARY}`。",
              f"- 本复算脚本SHA256：`{result['review_script_sha256']}`。",
              "- 全部输入、结果精度及判定字段：[r1_milestone_review.json](r1_milestone_review.json)。",
              "- 原冻结审查：[REVIEW_PACKET.md](../real_data_phase3/REVIEW_PACKET.md)、[STATISTICAL_REVIEW.md](../real_data_phase3/STATISTICAL_REVIEW.md)。",
              "",
              "数据边界仍为ADMIT_DAILY_SCREEN：历史当前修订版、重建公开时钟、模型分红到账和研究费率不等于真实首见、个人流水或可执行分钟成交。已有技术审查通过不能替代费用、尾部、执行和经济证据。"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    result = calculate()
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "r1_milestone_review.json"
    md_path = OUT / "R1_MILESTONE_REVIEW.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(render(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "decision": result["milestone_decision"],
                      "checks": result["independent_checks"], "json_sha256": sha(json_path),
                      "markdown_sha256": sha(md_path)}, ensure_ascii=True))
