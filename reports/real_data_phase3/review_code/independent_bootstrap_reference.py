"""Independent numerical reference for the 24 released rank-contrast diagnostics.

No production evaluator is imported.  Read 16 primary-capital/base-path NAVs,
reconstruct same-session net returns, then independently calculate Bartlett HAC
and 5000 null-centered circular block-bootstrap-t draws in batches of 250.
Any degenerate resample makes that diagnostic inconclusive; none is discarded.
This reproduces existing exploratory diagnostics, not a new hypothesis test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import NormalDist
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "reports/real_data_phase3/results_summary.json"
PLAN = ROOT / "reports/real_data_phase3/registered_plan_v2.json"
EXPECTED_SUMMARY = "c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb"
EXPECTED_PLAN = "bcb82aba5cc05300cc9ec5603933c5d03b4903712823b658f43ecd44976217e3"
EXPECTED_SOURCE = "d8d265eed26337ba8a58e2dff809af3acc71550232ecbddaa2b94a7a3da6ba7a"
PERIODS = {"development": ("2016-01-01", "2021-12-31"), "validation": ("2022-01-01", "2024-12-31")}
BLOCKS = (60, 20, 120)
SEED, DRAWS, BATCH, CAPITAL = 20261114, 5000, 250, 100000
EPSILON = 1e-15
NUMERIC_FIELDS = ("mean_net_increment", "daily_hurdle", "hac_se", "p_hac",
                  "minimum_detectable_daily_effect_80pct")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def hac_reference(samples, lag):
    """HAC SE of means: covariance denominator n at every lag, Bartlett taper.

    Form the complete covariance vector with independent einsum inner products,
    then contract it once with its taper.  No production helper or covariance
    normalization is reused.
    """
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    n = values.shape[1]
    deviations = values - values.mean(axis=1, keepdims=True)
    covariance = np.empty((len(values), lag + 1), dtype=np.float64)
    covariance[:, 0] = np.einsum("ij,ij->i", deviations, deviations) / n
    for offset in range(1, lag + 1):
        covariance[:, offset] = np.einsum("ij,ij->i", deviations[:, :-offset], deviations[:, offset:]) / n
    taper = np.concatenate(([1.0], 2.0 * (1.0 - np.arange(1, lag + 1) / (lag + 1))))
    long_run_variance = np.einsum("ij,j->i", covariance, taper)
    return np.sqrt(np.clip(long_run_variance, 0.0, None) / n)


def circular_indices(starts, width, count):
    offsets = np.arange(width, dtype=np.int64)
    expanded = (starts[:, :, None] + offsets[None, None, :]) % count
    return expanded.reshape(len(starts), -1)[:, :count]


def linear_quantile(sorted_values, probability):
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    fraction = position - lower
    return float(sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower]))


def bootstrap_reference(differences, block, *, draws=DRAWS, seed=SEED):
    values = np.asarray(differences, dtype=np.float64)
    need(values.ndim == 1 and np.isfinite(values).all(), "Invalid paired return vector")
    n = len(values)
    average = float(values.mean()) if n else None
    result = {"n_dates": n, "block_length": block, "repetitions": draws, "seed": seed,
              "mean_net_increment": average, "daily_hurdle": 0.0,
              "interval_type": "marginal_95_percent", "method": "circular_block_bootstrap_t_HAC"}
    diagnostic = {"reference_batch_size": BATCH, "draws_generated": 0,
                  "degenerate_replicates": 0, "first_degenerate_replica_zero_based": None}
    if n < max(120, 2 * block):
        return dict(result, status="INCONCLUSIVE_SHORT_SAMPLE", p_net=None, ci95=None), diagnostic
    lag = max(1, math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    standard_error = float(hac_reference(values, lag)[0])
    diagnostic.update(observed_hac_lag=lag, observed_hac_se=standard_error)
    if standard_error <= EPSILON:
        return dict(result, status="INCONCLUSIVE_DEGENERATE", p_net=None, ci95=None), diagnostic
    # Boundary-null observations have mean zero.  Bootstrap samples are then
    # independently re-centered only for their own HAC covariance estimate.
    null_observations = values - average
    generator = np.random.default_rng(seed)
    t_values = np.empty(draws, dtype=np.float64)
    nblocks = (n + block - 1) // block
    for first in range(0, draws, BATCH):
        size = min(BATCH, draws - first)
        starts = generator.integers(low=0, high=n, size=(size, nblocks))
        resamples = null_observations[circular_indices(starts, block, n)]
        resampled_se = hac_reference(resamples, lag)
        degenerate = resampled_se <= EPSILON
        diagnostic["degenerate_replicates"] += int(np.count_nonzero(degenerate))
        if degenerate.any() and diagnostic["first_degenerate_replica_zero_based"] is None:
            diagnostic["first_degenerate_replica_zero_based"] = first + int(np.flatnonzero(degenerate)[0])
        # NaN is an internal placeholder, never a repaired/dropped replicate.
        # Any such draw makes the complete published diagnostic inconclusive.
        t_values[first:first + size] = np.divide(
            resamples.mean(axis=1), resampled_se,
            out=np.full(size, np.nan), where=~degenerate)
    diagnostic["draws_generated"] = draws
    if diagnostic["degenerate_replicates"]:
        return dict(result, status="INCONCLUSIVE_DEGENERATE_BOOTSTRAP", p_net=None, ci95=None), diagnostic
    need(np.isfinite(t_values).all(), "Nonfinite studentized bootstrap statistic")
    observed_t = average / standard_error
    ordered_t = np.sort(t_values)
    lo_t, hi_t = linear_quantile(ordered_t, .025), linear_quantile(ordered_t, .975)
    p_boot = (1 + int(np.count_nonzero(t_values >= observed_t))) / (draws + 1)
    # erfc and stdlib NormalDist provide a reference independent of scipy.stats.
    p_normal = .5 * math.erfc(observed_t / math.sqrt(2.0))
    detectability = (NormalDist().inv_cdf(.95) + NormalDist().inv_cdf(.8)) * standard_error
    return dict(result, status="DESCRIPTIVE_INFERENCE", hac_lag=lag, hac_se=standard_error,
                p_net=p_boot, p_hac=p_normal,
                ci95=[average - hi_t * standard_error, average - lo_t * standard_error],
                minimum_detectable_daily_effect_80pct=detectability), diagnostic


def compare(expected, actual, label):
    exact = ("status", "n_dates", "block_length", "repetitions", "seed", "interval_type", "method", "p_net")
    for field in exact:
        need(expected.get(field) == actual.get(field), label + ": exact mismatch in " + field)
    need(expected.get("hac_lag") == actual.get("hac_lag"), label + ": HAC lag mismatch")
    errors = {}
    for field in NUMERIC_FIELDS:
        left, right = expected.get(field), actual.get(field)
        if left is None or right is None:
            need(left is None and right is None, label + ": null/numeric mismatch in " + field)
        else:
            difference = abs(float(left) - float(right))
            errors[field] = difference
            need(difference <= 1e-12, label + ": numerical mismatch in " + field + " (absolute error " + str(difference) + ")")
    if expected.get("ci95") is None or actual.get("ci95") is None:
        need(expected.get("ci95") is None and actual.get("ci95") is None, label + ": CI null mismatch")
    else:
        errors["ci95"] = max(abs(a - b) for a, b in zip(expected["ci95"], actual["ci95"]))
        need(len(expected["ci95"]) == len(actual["ci95"]) == 2 and errors["ci95"] <= 1e-12,
             label + ": confidence interval mismatch")
    errors["p_net"] = 0.0
    return errors


def base_path(config):
    return (config.get("cost_multiplier", 1), config.get("slippage_multiplier", 1),
            config.get("execution_delay", 1), config.get("cash_delay_sessions", 0)) == (1, 1, 1, 0)


def review():
    script_hash = sha(__file__)
    need(sha(SUMMARY) == EXPECTED_SUMMARY and sha(PLAN) == EXPECTED_PLAN, "Released summary/registration changed")
    report, plan = read(SUMMARY), read(PLAN)
    need(report["run_count"] == 448 and len(report["runs"]) == 448, "Incomplete official matrix")
    need(report["provenance"]["source_hash"] == plan["source_hash"] == EXPECTED_SOURCE, "Execution source mismatch")
    need(report["economic_confirmation"] == "BLOCKED_HURDLE" and report["final_holdout_accessed"] is False,
         "Official interpretation changed")
    trials = {row["config_hash"]: row["config"] for row in plan["trials"]}
    selected = [row for row in report["runs"] if row["config"]["initial_cash"] == CAPITAL and base_path(row["config"])]
    need(len(selected) == 16, "Require exactly 16 primary-capital/base NAVs")
    expected_keys = set(itertools.product(PERIODS, ("E0", "R0", "E1", "R1"), (False, True)))
    expected_calendars, bound_files = {}, {str(SUMMARY): EXPECTED_SUMMARY, str(PLAN): EXPECTED_PLAN}
    for period, (start, end) in PERIODS.items():
        manifest = ROOT / plan["samples"][period]["manifest_path"]
        expected_hash = plan["samples"][period]["manifest_sha256"]
        need(sha(manifest) == expected_hash, "Dataset manifest mismatch")
        calendar_path = manifest.parent / "calendar.json"
        calendar_hash = read(manifest)["file_sha256"]["calendar.json"]
        need(sha(calendar_path) == calendar_hash, "Dataset calendar mismatch")
        expected_calendars[period] = [day for day in read(calendar_path) if start <= day <= end]
        bound_files[str(manifest)], bound_files[str(calendar_path)] = expected_hash, calendar_hash
    returns, sources = {}, []
    for row in selected:
        config, period = row["config"], row["period"]
        key = (period, config["variant"], config["risk_scaling"])
        need(key in expected_keys and key not in returns, "Unexpected/duplicate NAV configuration")
        config_hash = digest(config)
        need(trials.get(config_hash) == config and config["sample"] == period, "Unregistered reference input")
        need(config.get("signal_release_delay") == 1 and config.get("live_enabled") is False,
             "Reference input protocol mismatch")
        matrix_root = Path(report["provenance"]["matrix_roots"][period]).resolve()
        directory = (matrix_root / row["directory"]).resolve()
        need(matrix_root.name.endswith(period + "_v2") and directory.parent == matrix_root, "Invalid NAV directory")
        for name in ("config.json", "provenance.json", "table_hashes.json"):
            file_path = directory / name
            expected_hash = row["artifact_hashes"][name]
            need(sha(file_path) == expected_hash, "Run artifact changed: " + name)
            bound_files[str(file_path)] = expected_hash
        need(read(directory / "config.json") == config, "Run config differs from summary")
        provenance = read(directory / "provenance.json")
        need(provenance["source_hash"] == EXPECTED_SOURCE and provenance["config_hash"] == config_hash
             and provenance["run_id"] == directory.name, "Run provenance identity mismatch")
        need(all(provenance[field] == row["provenance"][field] for field in ("source_hash", "config_hash", "data_hash")),
             "Summary/run identity mismatch")
        nav_path = directory / "nav.json"
        nav_hash = row["table_hashes"]["nav"]
        need(read(directory / "table_hashes.json")["nav"] == nav_hash and sha(nav_path) == nav_hash,
             "NAV hash differs from official summary")
        bound_files[str(nav_path)] = nav_hash
        nav = read(nav_path)
        dates = [item["date"] for item in nav]
        need(dates == expected_calendars[period], "NAV session calendar incomplete")
        amounts = np.asarray([item["nav"] for item in nav], dtype=np.float64)
        need(np.isfinite(amounts).all() and (amounts > 0).all(), "Invalid NAV value")
        prior = np.empty(len(amounts), dtype=np.float64)
        prior[0], prior[1:] = CAPITAL, amounts[:-1]
        returns[key] = amounts / prior - 1.0
        sources.append({"period": period, "variant": config["variant"], "risk_scaling": config["risk_scaling"],
                        "run_id": directory.name, "config_hash": config_hash, "nav_sha256": nav_hash,
                        "n_dates": len(dates), "dates_sha256": digest(dates),
                        "reconstructed_returns_sha256": digest(returns[key].tolist())})
    need(set(returns) == expected_keys, "Incomplete primary NAV selection")
    paired = [row for row in report["paired_effects"] if row["initial_cash"] == CAPITAL and row["path"] == "base"]
    need(len(paired) == 8, "Require eight existing rank contrasts")
    seen, checks, max_errors, statuses = set(), [], {}, Counter()
    for row in paired:
        period, candidate, baseline, scaling = row["period"], row["candidate"], row["baseline"], row["risk_scaling"]
        key = (period, candidate, baseline, scaling)
        need((candidate, baseline) in (("R0", "E0"), ("R1", "E1")) and key not in seen, "Unexpected rank contrast")
        seen.add(key)
        difference = returns[(period, candidate, scaling)] - returns[(period, baseline, scaling)]
        need(abs(float(difference.mean()) - row["mean_daily_net_increment"]) <= 1e-14,
             "Reconstructed paired mean mismatch")
        formal = row["uncertainty"]["formal"]
        need(formal["status"] == "BLOCKED_HURDLE" and formal["p_net"] is None and formal["ci95"] is None,
             "Formal unknown-cost status was changed")
        exploratory = row["uncertainty"]["exploratory_zero_hurdle"]
        need(exploratory["annual_incremental_cost_assumed_cny"] == 0 and exploratory["multiplicity_confirmed"] is False
             and exploratory["factor_alpha"] is False, "Exploratory scope was changed")
        need([block["block_length"] for block in exploratory["blocks"]] == list(BLOCKS), "Block diagnostic grid changed")
        for expected in exploratory["blocks"]:
            block = expected["block_length"]
            actual, diagnostic = bootstrap_reference(difference, block)
            label = str(key) + "/block" + str(block)
            errors = compare(expected, actual, label)
            for field, error in errors.items():
                max_errors[field] = max(max_errors.get(field, 0.0), error)
            statuses[actual["status"]] += 1
            checks.append({"period": period, "candidate": candidate, "baseline": baseline, "risk_scaling": scaling,
                           "block_length": block, "comparison_status": "MATCH", "absolute_errors": errors,
                           "reference": actual, "reference_diagnostics": diagnostic})
            print("Bootstrap reference matched " + str(len(checks)) + "/24: " + label + " " + actual["status"],
                  file=sys.stderr, flush=True)
    expected_pairs = set(itertools.product(PERIODS, (("R0", "E0"), ("R1", "E1")), (False, True)))
    need({(p, (c, b), s) for p, c, b, s in seen} == expected_pairs and len(checks) == 24, "Incomplete contrast review")
    inconclusive = {(r["period"], r["candidate"], r["baseline"], r["risk_scaling"], r["block_length"])
                    for r in checks if r["reference"]["status"] == "INCONCLUSIVE_DEGENERATE_BOOTSTRAP"}
    need(inconclusive == {("development", "R1", "E1", scaling, 120) for scaling in (False, True)},
         "Registered degenerate-bootstrap outcomes changed")
    for path, expected_hash in bound_files.items():
        need(sha(path) == expected_hash, "Input changed during independent reference: " + path)
    need(sha(__file__) == script_hash, "Reference code changed during calculation")
    return {"schema_version": "independent-bootstrap-reference-1.0", "status": "ALL_24_MATCH",
            "summary_sha256": EXPECTED_SUMMARY, "registered_plan_sha256": EXPECTED_PLAN,
            "execution_source_hash": EXPECTED_SOURCE, "reference_script_sha256": script_hash,
            "primary_capital_cny": CAPITAL, "nav_inputs": sources, "bound_input_sha256": bound_files,
            "contrast_count": 8, "diagnostic_count": 24, "status_counts": dict(statuses),
            "maximum_absolute_errors": max_errors, "absolute_tolerance": 1e-12,
            "p_net_and_discrete_fields_require_exact_equality": True,
            "reference_method": {"bootstrap_draws": DRAWS, "seed": SEED, "batch_size": BATCH,
                "block_lengths": BLOCKS, "centering": "difference minus observed mean; boundary hurdle zero",
                "hac": "Bartlett taper; lag=max(1,floor(4*(n/100)^(2/9))); every autocovariance denominator n",
                "confidence_interval": "Marginal bootstrap-t, linear 2.5/97.5 percentiles, inverted with observed HAC SE",
                "normal_tail_and_mde": "stdlib erfc and NormalDist; no production/scipy evaluator imported",
                "degenerate_policy": "All5000 reference draws retained; any SE<=1e-15 makes p/CI null and the whole diagnostic inconclusive"},
            "runtime": {"python": sys.version, "numpy": np.__version__},
            "scope": "Numerical reproduction of eight pre-existing exploratory rank contrasts only; no new hypotheses, winner selection, economic confirmation or stationarity validation.",
            "formal_economic_status": "BLOCKED_HURDLE", "checks": checks}


def selfcheck():
    sequence = np.asarray([.03, -.01, .04, -.02, .01, .02, -.04])
    lag, n = 2, len(sequence)
    mean = math.fsum(sequence) / n
    deviations = [float(value) - mean for value in sequence]
    variance = math.fsum(value * value for value in deviations) / n
    for offset in range(1, lag + 1):
        covariance = math.fsum(deviations[i] * deviations[i - offset] for i in range(offset, n)) / n
        variance += 2 * (1 - offset / (lag + 1)) * covariance
    need(abs(float(hac_reference(sequence, lag)[0]) - math.sqrt(variance / n)) < 1e-16,
         "Independent scalar HAC fixture mismatch")
    need(circular_indices(np.array([[3, 1]]), 3, 5).tolist() == [[3, 4, 0, 1, 2]], "Circular block indexing mismatch")
    need(abs(linear_quantile(np.array([0., 10., 20., 30.]), .25) - 7.5) < 1e-15, "Quantile interpolation mismatch")
    constant, _ = bootstrap_reference(np.ones(240) * .001, 120, draws=200)
    need(constant["status"] == "INCONCLUSIVE_DEGENERATE", "Constant sample was not inconclusive")
    sparse = np.zeros(240)
    sparse[0] = 1.0
    degenerate, details = bootstrap_reference(sparse, 120, draws=200)
    need(degenerate["status"] == "INCONCLUSIVE_DEGENERATE_BOOTSTRAP" and details["draws_generated"] == 200
         and details["degenerate_replicates"] > 0 and degenerate["ci95"] is None and degenerate["p_net"] is None,
         "Degenerate bootstrap replicates were repaired or dropped")
    compile(Path(__file__).read_text(encoding="utf-8"), str(__file__), "exec")
    return {"status": "PASS", "invented_checks": 5, "actual_navs_read": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/real_data_phase3/independent_bootstrap_reference.json")
    args = parser.parse_args()
    try:
        if args.selfcheck:
            print(json.dumps(selfcheck(), indent=2))
            return
        need(not args.output.exists(), "Refusing to overwrite existing reference report")
        result = review()
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        print(json.dumps({"status": result["status"], "status_counts": result["status_counts"],
                          "maximum_absolute_errors": result["maximum_absolute_errors"],
                          "output": str(args.output.resolve()), "output_sha256": sha(args.output)}, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "REFERENCE_MISMATCH_NO_PASS_REPORT", "reason": str(error)}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
