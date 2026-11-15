"""Descriptive year-deletion and primary-capital P&L attribution; no new tests."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/real_data_phase3/independent_year_attribution.json"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def calculate():
    main_path = ROOT / "reports/real_data_phase3/results_summary.json"
    main = read(main_path)
    runs = {(r["period"], r["config"]["initial_cash"], r["config"]["variant"],
             r["config"]["risk_scaling"], r["path"]): r for r in main["runs"]}
    counts = {}
    for period, start in (("development", "2016-01-01"), ("validation", "2022-01-01")):
        calendar = read(ROOT / "data/admitted_r1/phase2_v1" / period / "calendar.json")
        counts[period] = Counter(d[:4] for d in calendar if d >= start)
    deletion = []
    for row in main["paired_effects"]:
        period = row["period"]
        candidate = runs[(period, row["initial_cash"], row["candidate"], row["risk_scaling"], row["path"])]
        annual = {str(y["year"]): y for y in row["annual_differences"]}
        candidate_years = {str(y["year"]): y for y in candidate["year_contributions"]}
        rules = {
            "candidate_best_year_return": max(sorted(annual), key=lambda y: candidate_years[y]["year_return"]),
            "maximum_paired_annual_pnl_increment": max(sorted(annual), key=lambda y: annual[y]["pnl_difference_cny"]),
            "maximum_annual_mean_daily_increment": max(sorted(annual), key=lambda y: annual[y]["mean_daily_net_increment"]),
        }
        for rule, removed in rules.items():
            remaining = sum(counts[period][y] for y in annual if y != removed)
            mean = sum(annual[y]["mean_daily_net_increment"] * counts[period][y]
                       for y in annual if y != removed) / remaining
            deletion.append({k: row[k] for k in
                ("period", "initial_cash", "candidate", "baseline", "risk_scaling", "path")} | {
                "rule": rule, "removed_year": int(removed), "remaining_sessions": remaining,
                "remaining_mean_daily_net_increment": mean,
                "original_mean_daily_net_increment": row["mean_daily_net_increment"],
                "candidate_year_returns": {y: candidate_years[y]["year_return"] for y in annual},
                "original_annual_paired_differences": row["annual_differences"],
                "p_value": None, "interpretation": "Descriptive sensitivity only. Delete the same dates from candidate and baseline; do not refit or rerun portfolios. Ties choose the earliest year."})
    attribution = []
    for row in main["runs"]:
        config = row["config"]
        if config["initial_cash"] != 100000 or row["path"] != "base":
            continue
        directory = Path(main["provenance"]["matrix_roots"][row["period"]]) / row["directory"]
        tables = {}
        for name in ("nav", "positions", "fills", "cash_events"):
            path = directory / (name + ".json")
            assert sha(path) == row["table_hashes"][name]
            tables[name] = read(path)
        pnl, activity = defaultdict(float), Counter()
        final = tables["nav"][-1]["date"]
        for p in tables["positions"]:
            if p["date"] == final:
                pnl[p["instrument_id"]] += p["market_value"]
        for fill in tables["fills"]:
            sid = fill["instrument_id"]
            pnl[sid] += (fill["notional"] if fill["side"] == "SELL" else -fill["notional"]) - fill["fees"]
            activity[sid] += 1
        for event in tables["cash_events"]:
            assert not event["event"].startswith("LIQUIDATION"), "Liquidation attribution requires a separate model"
            if event["event"] == "DIVIDEND_RECEIVABLE":
                pnl[event["instrument_id"]] += event["amount"]
        total = tables["nav"][-1]["nav"] - config["initial_cash"]
        error = abs(sum(pnl.values()) - total)
        assert error <= 1e-6, "Instrument cash-flow attribution does not reconcile"
        previous, daily = config["initial_cash"], []
        for n in tables["nav"]:
            daily.append((n["date"], n["nav"] - previous))
            previous = n["nav"]
        positive = sorted((v for v in pnl.values() if v > 0), reverse=True)
        positive_days = sorted(((d, v) for d, v in daily if v > 0), key=lambda x: x[1], reverse=True)
        gross_positive = sum(positive)
        gross_positive_days = sum(v for d, v in positive_days)
        attribution.append({"period": row["period"], "variant": config["variant"], "risk_scaling": config["risk_scaling"],
            "initial_cash": 100000, "path": "base", "run_id": row["directory"],
            "net_pnl_cny": total, "reconciliation_error_cny": error,
            "instrument_pnl_cny": dict(sorted(pnl.items())), "fill_counts_by_instrument": dict(activity),
            "largest_positive_instrument_share_of_gross_positive_pnl": positive[0] / gross_positive if positive else None,
            "top3_positive_instrument_share_of_gross_positive_pnl": sum(positive[:3]) / gross_positive if positive else None,
            "top5_positive_days_share_of_gross_positive_daily_pnl": sum(v for d, v in positive_days[:5]) / gross_positive_days if positive_days else None,
            "top5_positive_pnl_days": [{"date": d, "pnl_cny": v} for d, v in positive_days[:5]],
            "scope": "Per-instrument ending marked value + net sale proceeds - purchases - all fees + recognized dividends. Initial holdings zero. Payout of an already recognized dividend is not income twice. This is not FIFO round-trip trade P&L or causal factor attribution."})
    return {"schema_version": 1, "status": "DESCRIPTIVE_SENSITIVITY_AND_ATTRIBUTION",
        "reviewed_at": datetime.now(timezone.utc).isoformat(), "reviewer": "/root/independent_admission",
        "main_results_sha256": sha(main_path), "review_script_sha256": sha(__file__),
        "year_deletion_rows": deletion, "primary_base_instrument_attribution": attribution,
        "qualifications": ["The two requested profitability definitions are both shown, never selected by favorable output.",
            "The initially stated best-mean-d definition is also retained. For all8 primary base pairs it selects the same year as maximum annual paired CNY contribution.",
            "No new p-values, strategy variants, refitting, sample windows or deployment recommendations.",
            "Instrument/day concentration is not the profit concentration of individually matched buy/sell round trips; the latter is not independently reconstructed."]}


if __name__ == "__main__":
    result = calculate()
    with OUT.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "year_deletion_rows": len(result["year_deletion_rows"]),
                      "primary_accounts": len(result["primary_base_instrument_attribution"]), "sha256": sha(OUT)}))
