"""Independent descriptive supplement, fixed before inspecting real run results.

Consumes completed registered artifacts only. Does not call strategy/execution or
produce new hypothesis tests. The frozen evaluator's exploratory p-values remain
separate from this supplement.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PERIODS = {"development": ("2016-01-01", "2021-12-31"),
           "validation": ("2022-01-01", "2024-12-31")}
CAPITALS = (10000, 100000, 500000, 1000000)
VARIANTS = ("E0", "R0", "E1", "R1")
PATHS = ("base", "cost2_slip2", "cost3_slip3", "slip0", "delay2", "cash_delay1", "cash_delay3")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def close(a, b, label, tolerance=1e-9):
    need(math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, abs_tol=tolerance,
                                                             rel_tol=tolerance), label)


def diagnostics(returns, dates, cagr, drawdown):
    """Definitions fixed before any actual returns were inspected."""
    n = len(returns)
    mean = float(np.mean(returns))
    centered = returns - mean
    lag = max(1, int(4 * (n / 100) ** (2 / 9)))
    lrv = float(np.dot(centered, centered) / n)
    for k in range(1, min(lag + 1, n)):
        lrv += 2 * (1 - k / (lag + 1)) * float(np.dot(centered[k:], centered[:-k])) / n
    downside = float(np.mean(np.minimum(returns, 0) ** 2))
    by_month = defaultdict(list)
    for date, value in zip(dates, returns):
        by_month[date[:7]].append(value)
    monthly = {month: float(np.prod(1 + np.asarray(values)) - 1) for month, values in by_month.items()}
    tail_n = max(1, math.ceil(.05 * n))
    denom = float(np.dot(centered, centered))
    return {
        "sortino_zero_cash_252": math.sqrt(252) * mean / math.sqrt(downside) if downside > 0 else None,
        "calmar_sample_cagr_over_abs_max_drawdown": cagr / abs(drawdown) if drawdown < 0 else None,
        "daily_lower_tail_5pct_mean_return": float(np.sort(returns)[:tail_n].mean()),
        "daily_lower_tail_observations": tail_n,
        "worst_calendar_month": min(monthly, key=monthly.get),
        "worst_calendar_month_return": min(monthly.values()),
        "calendar_month_returns": monthly,
        "return_autocorrelation_lag1_centered_full_denominator":
            float(np.dot(centered[1:], centered[:-1]) / denom) if denom > 0 else None,
        "hac_lag": lag,
        "hac_long_run_variance": max(lrv, 0.),
        "hac_long_run_variance_sharpe_252": math.sqrt(252) * mean / math.sqrt(lrv) if lrv > 0 else None,
        "serial_correlation_caveat": "HAC Sharpe is an approximate weak-stationarity diagnostic, not a factor-adjusted alpha or exact annual-horizon Sharpe."
    }


def describe_difference(values, dates):
    n = len(values)
    rolling = np.convolve(values, np.ones(252) / 252, mode="valid") if n >= 252 else np.array([])
    return {
        "n_dates": n, "mean_daily_difference": float(values.mean()),
        "year_mean_daily_differences": {year: float(values[np.array([d[:4] == year for d in dates])].mean())
                                         for year in sorted({d[:4] for d in dates})},
        "rolling_252_session_windows": len(rolling),
        "rolling_252_min_mean": float(rolling.min()) if len(rolling) else None,
        "rolling_252_max_mean": float(rolling.max()) if len(rolling) else None,
        "rolling_252_fraction_positive": float((rolling > 0).mean()) if len(rolling) else None,
        "rolling_warning": "Overlapping windows are descriptive and not independent observations.",
        "p_value": None,
        "status": "AUXILIARY_DESCRIPTIVE_ONLY"
    }


def summarize_decisions(decisions, config, calendar):
    indices = {date: i for i, date in enumerate(calendar)}
    status, exclusions, eligible, trend, years = Counter(), Counter(), Counter(), Counter(), {}
    gross, risk_multipliers, too_few_risk, top3 = [], [], 0, 0
    for row in decisions:
        diagnostics = row["diagnostics"]
        anchor, day, execution = diagnostics["signal_anchor_date"], row["decision_date"], row["execution_date"]
        need(indices[day] == indices[anchor] + 1, "Decision violates D039 source release")
        need(indices[execution] == indices[day] + config["execution_delay"], "Execution delay mismatch")
        need(diagnostics["order_reference_date"] == day, "Order reference date is not decision date")
        need(diagnostics["signal_release_delay"] == 1, "Signal release diagnostics mismatch")
        weights = list(row["weights"].values())
        need(all(0 <= w <= .35 + 1e-10 for w in weights) and sum(weights) <= 1 + 1e-10,
             "Invalid target weights")
        close(sum(weights), diagnostics["target_gross_weight"], "Target gross diagnostics mismatch")
        status[row["status"]] += 1
        exclusions.update(diagnostics["exclusions"].values())
        eligible[len(diagnostics["eligible"])]+=1
        top3 += not diagnostics["top3_comparable"]
        value = diagnostics.get("trend", "NOT_EVALUATED")
        trend["ON" if value is True else "OFF" if value is False else "UNAVAILABLE" if value is None else "NOT_EVALUATED"] += 1
        gross.append(float(sum(weights)))
        if "risk_multiplier" in diagnostics:
            risk_multipliers.append(diagnostics["risk_multiplier"])
            too_few_risk += diagnostics["complete_risk_sessions"] < 45
        y = years.setdefault(execution[:4], {"decisions": 0, "status_counts": Counter(), "exclusion_reason_counts": Counter()})
        y["decisions"] += 1
        y["status_counts"][row["status"]] += 1
        y["exclusion_reason_counts"].update(diagnostics["exclusions"].values())
    return {"decisions": len(decisions), "status_counts": dict(status), "exclusion_reason_counts": dict(exclusions),
            "eligible_count_distribution": {str(k): v for k, v in sorted(eligible.items())},
            "top3_not_comparable_decisions": top3, "trend_evaluation_counts": dict(trend),
            "mean_monthly_target_gross": float(np.mean(gross)) if gross else None,
            "zero_target_decisions": sum(v == 0 for v in gross),
            "partial_positive_target_decisions": sum(0 < v < 1 - 1e-10 for v in gross),
            "risk_multiplier_evaluations": len(risk_multipliers), "risk_history_below_45_decisions": too_few_risk,
            "mean_evaluated_risk_multiplier": float(np.mean(risk_multipliers)) if risk_multipliers else None,
            "by_execution_year": years,
            "count_scope": "Monthly target decisions; exclusion counts are instrument-decision occurrences. Counts are not independent trials or daily cash-duration estimates. Trend is not evaluated when prior eligibility already blocks a portfolio."}


def review(summary_path):
    report = read(summary_path)
    plan_path = ROOT / "reports/real_data_phase3/registered_plan.json"
    plan = read(plan_path)
    need(report["run_count"] == 448 and len(report["runs"]) == 448, "Incomplete completed matrix")
    need(report["economic_confirmation"] == "BLOCKED_HURDLE", "Unknown hurdle relabeled")
    need(report["final_holdout_accessed"] is False and report["factor_alpha"] is None, "Unsupported claim")
    registered = {row["config_hash"]: row["config"] for row in plan["trials"]}
    need(len(registered) == 448, "Incomplete preregistration")
    observed, series, dates_by_period, rows_by_key, extra = set(), {}, {}, {}, []
    expected_calendars, full_calendars, dataset_checks = {}, {}, {}
    decision_rows, target_hash_groups, qualification_groups = [], defaultdict(set), defaultdict(set)
    for period, bounds in PERIODS.items():
        descriptor = plan["samples"][period]
        manifest = ROOT / descriptor["manifest_path"]
        need(sha(manifest) == descriptor["manifest_sha256"], "Admitted manifest changed")
        m = read(manifest)
        for file, expected in m["file_sha256"].items():
            need(sha(manifest.parent / file) == expected, "Admitted table changed: " + file)
        calendar = read(manifest.parent / "calendar.json")
        full_calendars[period] = calendar
        expected_calendars[period] = [d for d in calendar if bounds[0] <= d <= bounds[1]]
        dataset_checks[period] = {"manifest_sha256": sha(manifest),
                                  "expected_funded_sessions": len(expected_calendars[period])}
    for row in report["runs"]:
        period, config = row["period"], row["config"]
        config_hash = digest(config)
        need(config_hash in registered and registered[config_hash] == config, "Configuration absent from preregistration")
        need(config_hash not in observed, "Duplicate configuration")
        observed.add(config_hash)
        need(row["provenance"]["source_hash"] == plan["source_hash"], "Source differs from preregistration")
        directory = Path(report["provenance"]["matrix_roots"][period]) / row["directory"]
        need(sha(directory / "decisions.json") == row["artifact_hashes"]["decisions.json"], "Decision artifact hash mismatch")
        decisions = read(directory / "decisions.json")
        target_hash_groups[(period, config["variant"], config["risk_scaling"], config["execution_delay"])].add(digest(decisions))
        for decision in decisions:
            d = decision["diagnostics"]
            qualification_groups[(period, config["execution_delay"], d["signal_anchor_date"])].add(digest(
                {k: d[k] for k in ("representatives", "eligible", "exclusions", "representative_at")}))
        decision_rows.append({"directory": row["directory"], "period": period, "initial_cash": config["initial_cash"],
                              "variant": config["variant"], "risk_scaling": config["risk_scaling"], "path": row["path"],
                              **summarize_decisions(decisions, config, full_calendars[period])})
        need(sha(directory / "nav.json") == row["table_hashes"]["nav"], "NAV hash mismatch")
        nav = read(directory / "nav.json")
        dates = [r["date"] for r in nav]
        need(dates == expected_calendars[period], "Missing or extra funded exchange session: " + row["directory"])
        dates_by_period[period] = dates
        equity = np.array([r["nav"] for r in nav], dtype=float)
        need(np.isfinite(equity).all() and (equity > 0).all(), "Invalid NAV")
        prior = np.r_[config["initial_cash"], equity[:-1]]
        returns = equity / prior - 1
        total = float(equity[-1] / config["initial_cash"] - 1)
        close(total, row["metrics"]["total_return"], "Terminal return mismatch")
        close(float(np.prod(1 + returns) - 1), total, "Daily compounding mismatch")
        close(sum(y["additive_return_contribution_initial_capital"] for y in row["year_contributions"]),
              total, "Annual contribution sum mismatch")
        close(math.prod(1 + y["year_return"] for y in row["year_contributions"]) - 1,
              total, "Annual compounding mismatch")
        peak = np.maximum.accumulate(np.r_[config["initial_cash"], equity])[1:]
        drawdown = float(np.min(equity / peak - 1))
        close(drawdown, row["metrics"]["max_drawdown"], "Initial-cash drawdown mismatch")
        key = (period, config["initial_cash"], config["variant"], config["risk_scaling"], row["path"])
        series[key], rows_by_key[key] = returns, row
        extra.append({"directory": row["directory"], "period": period, "initial_cash": config["initial_cash"],
                      "variant": config["variant"], "risk_scaling": config["risk_scaling"], "path": row["path"],
                      **diagnostics(returns, dates, row["metrics"]["cagr"], drawdown)})
    need(observed == set(registered), "Completed inventory differs from preregistration")
    need(all(len(values) == 1 for values in target_hash_groups.values()), "Capital/cost/cash stress changed precomputed targets")
    need(all(len(values) == 1 for values in qualification_groups.values()), "Variant/scaling changed anchor eligibility or representatives")
    contrasts, scaling_effects, interactions = [], [], []
    for period, capital, scaling, path in itertools.product(PERIODS, CAPITALS, (False, True), PATHS):
        dates = dates_by_period[period]
        for effect, a, b in (("rank_without_trend", "R0", "E0"), ("rank_with_trend", "R1", "E1"),
                             ("trend_equal_weight", "E1", "E0"), ("trend_ranked", "R1", "R0")):
            ka, kb = (period, capital, a, scaling, path), (period, capital, b, scaling, path)
            values = series[ka] - series[kb]
            contrasts.append({"period": period, "initial_cash": capital, "risk_scaling": scaling, "path": path,
                "effect": effect, "candidate": a, "baseline": b,
                "mean_exposure_difference": rows_by_key[ka]["mean_gross_exposure"] - rows_by_key[kb]["mean_gross_exposure"],
                "terminal_return_difference": rows_by_key[ka]["metrics"]["total_return"] - rows_by_key[kb]["metrics"]["total_return"],
                "endpoint_equivalent_annual_increment_cny": float(capital * 252 * values.mean()),
                "cost_sensitivity_warning": "Signed arithmetic endpoint equivalent only; no actual cost quote, profit promise or economic confirmation.",
                **describe_difference(values, dates)})
        interaction = (series[(period, capital, "R1", scaling, path)] - series[(period, capital, "R0", scaling, path)]
                       - series[(period, capital, "E1", scaling, path)] + series[(period, capital, "E0", scaling, path)])
        interactions.append({"period": period, "initial_cash": capital, "risk_scaling": scaling, "path": path,
                             "formula": "(R1-R0)-(E1-E0)", **describe_difference(interaction, dates)})
    for period, capital, variant, path in itertools.product(PERIODS, CAPITALS, VARIANTS, PATHS):
        values = series[(period, capital, variant, True, path)] - series[(period, capital, variant, False, path)]
        scaling_effects.append({"period": period, "initial_cash": capital, "variant": variant, "path": path,
                               "formula": "scaling_on - scaling_off", **describe_difference(values, dates_by_period[period])})
    chronology = {}
    for period, root in report["provenance"]["matrix_roots"].items():
        records = [json.loads(line) for line in (Path(root) / "trial_registry.jsonl").read_text().splitlines() if line.strip()]
        first = min(datetime.fromisoformat(r["recorded_at"]) for r in records if r["event"] == "REGISTERED")
        need(first > datetime.fromisoformat(plan["registered_at"]), "Run preceded local preregistration")
        chronology[period] = {"first_registered_at": first.isoformat(), "preregistered_at": plan["registered_at"],
                              "scope": "Local recorded chronology only, not externally authenticated timestamp."}
    return {"schema_version": 1, "status": "INDEPENDENT_DESCRIPTIVE_SUPPLEMENT",
            "reviewed_at": datetime.now(timezone.utc).isoformat(), "reviewer": "/root/independent_admission",
            "main_results_sha256": sha(summary_path), "registered_plan_sha256": sha(plan_path),
            "pre_results_plan_sha256": sha(ROOT / "work/independent_statistical_review_plan.json"),
            "review_script_sha256": sha(__file__), "run_count": len(extra), "dataset_checks": dataset_checks,
            "local_chronology": chronology, "all_registered_configs_and_funded_sessions_verified": True,
            "annual_and_daily_compounding_verified": True, "formal_economic_status": "BLOCKED_HURDLE",
            "new_p_values": None, "new_strategy_or_holdout_access": False,
            "decision_d039_and_cross_variant_qualification_checks": "PASS",
            "target_identity_groups_checked": len(target_hash_groups), "qualification_anchor_groups_checked": len(qualification_groups),
            "decision_diagnostics": decision_rows,
            "run_tail_and_dependence_diagnostics": extra, "four_contrasts": contrasts,
            "scaling_effects": scaling_effects, "trend_ranking_interactions": interactions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.summary)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run_count": result["run_count"],
                      "output_sha256": sha(args.output)}, ensure_ascii=False))
