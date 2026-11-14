"""Summarize the complete synthetic matrix; independently reconstruct its ledger.

Run after matrix completion: .venv/Scripts/python.exe scripts/summarize_runs.py
No strategy selection or statistical confirmation is performed here.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd


CAPITALS = (10000, 100000, 500000, 1000000)
VARIANTS = ("E0", "R0", "E1", "R1")
PATHS = ((1, 1, 1), (2, 2, 1), (3, 3, 1), (1, 0, 1), (1, 1, 2))
LABELS = {PATHS[0]: "base", PATHS[1]: "cost2_slip2", PATHS[2]: "cost3_slip3",
          PATHS[3]: "slip0", PATHS[4]: "delay2"}
NOTICE = ("SYNTHETIC_ENGINEERING_ONLY: invented prices and a weekday calendar; "
          "not real-market evidence, not out-of-sample validation, and not an Alpha claim.")
TOLERANCE = 1e-6


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def key(config):
    return (config["initial_cash"], config["variant"], config["risk_scaling"],
            config["cost_multiplier"], config["slippage_multiplier"], config["execution_delay"])


def grouped(table, dates, column, mask=None):
    if table.empty:
        return pd.Series(0., index=dates)
    if mask is not None:
        table = table.loc[mask]
    return table.groupby("date")[column].sum().reindex(dates, fill_value=0.).astype(float)


def reconcile(tables, initial_cash):
    """Rebuild cash, receivables and marked holdings from separate event tables."""
    nav, positions, events, fills = (tables[n] for n in ("nav", "positions", "cash_events", "fills"))
    dates = pd.Index(nav.date, name="date")
    if dates.has_duplicates or not dates.is_monotonic_increasing or len(dates) == 0:
        raise ValueError("NAV dates must be unique, chronological and nonempty")
    for name, table in tables.items():
        if "date" in table and not set(table.date).issubset(set(dates)):
            raise ValueError(f"{name}: events outside NAV dates")
    allowed = {"BUY", "SELL", "DIVIDEND_RECEIVABLE", "DIVIDEND_PAID",
               "LIQUIDATION_RIGHT_RECOGNIZED", "LIQUIDATION_RECEIVABLE", "LIQUIDATION_PAID"}
    if not events.empty and not set(events.event).issubset(allowed):
        raise ValueError("Unknown cash event; reconciliation cannot infer its meaning")
    cash = pd.Series(float(initial_cash), index=dates)
    receivables = pd.Series(0., index=dates)
    event_trades = pd.Series(0., index=dates)
    if not events.empty:
        cash += grouped(events, dates, "amount", events.event.isin(["BUY", "SELL", "DIVIDEND_PAID", "LIQUIDATION_PAID"])).cumsum()
        receivables = (grouped(events, dates, "amount", events.event.isin(["DIVIDEND_RECEIVABLE", "LIQUIDATION_RECEIVABLE"]))
                       - grouped(events, dates, "amount", events.event.isin(["DIVIDEND_PAID", "LIQUIDATION_PAID"]))).cumsum()
        recognition = events.loc[events.event.eq("LIQUIDATION_RIGHT_RECOGNIZED"), "amount"]
        if recognition.ne(0).any():
            raise ValueError("Right recognition cannot create cash or receivable amounts")
        event_trades = grouped(events, dates, "amount", events.event.isin(["BUY", "SELL"]))
    marked = positions.copy()
    if not marked.empty:
        if marked.duplicated(["date", "instrument_id"]).any() or (marked.quantity < 0).any():
            raise ValueError("Duplicate or negative position")
        marked["reconstructed_value"] = marked.quantity * marked.price
    holdings = grouped(marked, dates, "reconstructed_value")
    fill_cash = fills.copy()
    if not fills.empty:
        if fills.order_id.duplicated().any() or not set(fills.side).issubset({"BUY", "SELL"}):
            raise ValueError("Unexpected multiple daily fills or side")
        fill_cash["reconstructed_cash"] = np.where(fills.side.eq("BUY"), -fills.notional, fills.notional) - fills.fees
    fill_trades = grouped(fill_cash, dates, "reconstructed_cash")
    differences = {
        "cash": cash.to_numpy() - nav.cash_total.to_numpy(),
        "holdings": holdings.to_numpy() - nav.holdings_value.to_numpy(),
        "receivables": receivables.to_numpy() - nav.receivables.to_numpy(),
        "nav": (cash + holdings + receivables).to_numpy() - nav.nav.to_numpy(),
        "cash_partition": (nav.cash_available + nav.cash_reserved - nav.cash_total).to_numpy(),
        "trade_cash": (fill_trades - event_trades).to_numpy(),
        "costs": (grouped(tables["costs"], dates, "total_cost") - grouped(fills, dates, "fees")).to_numpy(),
    }
    if not fills.empty:
        rounded_notional = (fills.quantity * fills.price).map(
            lambda value: float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
        differences["fill_notional"] = (rounded_notional - fills.notional).to_numpy()
        differences["fee_components"] = (fills.commission + fills.stamp_duty + fills.transfer_fee - fills.fees).to_numpy()
    if not positions.empty:
        differences["position_values"] = (marked.reconstructed_value - marked.market_value).to_numpy()
    maxima = {}
    for name, values in differences.items():
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite ledger values: {name}")
        maxima[name] = float(np.abs(values).max(initial=0))
    bad = {name: amount for name, amount in maxima.items() if amount > TOLERANCE}
    if bad or (nav.cash_available < -TOLERANCE).any() or (nav.cash_withdrawable < -TOLERANCE).any() or (nav.cash_withdrawable > nav.cash_total + TOLERANCE).any():
        raise ValueError(f"Ledger reconciliation failed: {bad}")
    return {"status": "PASS", "tolerance_cny": TOLERANCE, "maximum_absolute_errors_cny": maxima,
            "scope": "Independent cash-event and quantity-times-price arithmetic; not independent market-price verification."}


def summarize_run(directory, expected_config):
    config, metrics = read_json(directory / "config.json"), read_json(directory / "metrics.json")
    provenance = read_json(directory / "provenance.json")
    if config != expected_config or config.get("sample") != "synthetic" or metrics.get("status") != "SYNTHETIC_ENGINEERING_ONLY":
        raise ValueError(f"Config mismatch or non-synthetic input: {directory.name}")
    hashes = read_json(directory / "table_hashes.json")
    tables = {}
    for name in ("nav", "positions", "fills", "orders", "costs", "rejected_orders", "cash_events"):
        payload = (directory / f"{name}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != hashes[name]:
            raise ValueError(f"Hash mismatch: {directory.name}/{name}")
        tables[name] = pd.DataFrame(json.loads(payload))
    check = reconcile(tables, config["initial_cash"])
    nav, fills, rejections = tables["nav"], tables["fills"], tables["rejected_orders"]
    dates = pd.Index(nav.date, name="date")
    equity = pd.Series(nav.nav.to_numpy(), index=dates)
    prior = equity.shift(1).fillna(config["initial_cash"])
    returns = equity / prior - 1
    if abs(float(equity.iloc[-1] / config["initial_cash"] - 1) - metrics["total_return"]) > 1e-10:
        raise ValueError(f"Metric total return disagrees with NAV: {directory.name}")
    turnover = .5 * grouped(fills, dates, "notional") / prior
    fees = grouped(fills, dates, "fees")
    year_rows = []
    for year in sorted({d[:4] for d in dates}):
        mask = dates.str.startswith(year)
        pnl = float((equity - prior).loc[mask].sum())
        year_rows.append({"year": int(year), "pnl_cny": pnl,
            "additive_return_contribution_initial_capital": pnl / config["initial_cash"],
            "year_return": float((1 + returns.loc[mask]).prod() - 1),
            "fees_cny": float(fees.loc[mask].sum()), "one_way_turnover": float(turnover.loc[mask].sum()),
            "mean_cash_weight": float((nav.loc[mask, "cash_total"] / nav.loc[mask, "nav"]).mean())})
    core_files = {name: value for name, value in provenance["source_files"].items()
                  if name.startswith("src/") or name.startswith("docs/") or name in ("requirements.lock", "pyproject.toml")}
    core_hash = hashlib.sha256(json.dumps(core_files, sort_keys=True).encode()).hexdigest()
    result = {"directory": directory.name, "config": config, "metrics": metrics,
        "provenance": {"source_hash": provenance["source_hash"], "core_source_hash": core_hash,
                       "data_hash": provenance["data_hash"], "git_commit": provenance["git_commit"]},
        "path": LABELS[tuple(key(config)[3:])], "ledger_reconciliation": check,
        "fills": len(fills), "order_intents": len(tables["orders"]),
        "rejection_events": len(rejections), "rejected_order_ids": int(rejections.order_id.nunique()) if not rejections.empty else 0,
        "rejection_reasons": {str(k): int(v) for k, v in rejections.reason.value_counts().items()} if not rejections.empty else {},
        "fees_cny": float(fees.sum()), "commission_cny": float(fills.commission.sum()) if not fills.empty else 0.,
        "stamp_duty_cny": float(fills.stamp_duty.sum()) if not fills.empty else 0.,
        "transfer_fee_cny": float(fills.transfer_fee.sum()) if not fills.empty else 0.,
        "slippage_cny": float(fills.slippage_cost.sum()) if not fills.empty else 0.,
        "traded_notional_cny": float(fills.notional.sum()) if not fills.empty else 0.,
        "one_way_turnover": float(turnover.sum()), "annualized_one_way_turnover_252": float(turnover.sum() * 252 / len(dates)),
        "mean_cash_weight": float((nav.cash_total / nav.nav).mean()), "ending_cash_weight": float(nav.cash_total.iloc[-1] / nav.nav.iloc[-1]),
        "ending_receivables_cny": float(nav.receivables.iloc[-1]), "year_contributions": year_rows,
        "uncertainty": {"status": "NOT_APPLICABLE_SYNTHETIC", "economic_confirmation": "BLOCKED_HURDLE" if config.get("annual_incremental_cost") is None else "NOT_APPLICABLE_SYNTHETIC", "p_value": None, "confidence_interval": None}}
    return result, returns


def summarize(matrix_root, output_root):
    entries = read_json(matrix_root / "matrix_summary.json")
    expected = {(capital, variant, scaling, *path) for capital, variant, scaling, path in
                itertools.product(CAPITALS, VARIANTS, (False, True), PATHS)}
    observed = [key(entry["config"]) for entry in entries]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError(f"Require all 160 unique configurations; got {len(observed)}, missing {len(expected - set(observed))}")
    results, series = {}, {}
    for entry in entries:
        name = entry["directory"]
        if Path(name).name != name:
            raise ValueError("Run directory must be a direct child of matrix root")
        run_key = key(entry["config"])
        results[run_key], series[run_key] = summarize_run(matrix_root / name, entry["config"])
    ordered = [results[(capital, variant, scaling, *path)] for capital, variant, scaling, path in
               itertools.product(CAPITALS, VARIANTS, (False, True), PATHS)]
    contrasts = []
    for capital, scaling, path in itertools.product(CAPITALS, (False, True), PATHS):
        for effect, candidate, baseline in (("rank_without_trend", "R0", "E0"), ("rank_with_trend", "R1", "E1"),
                                           ("trend_equal_weight", "E1", "E0"), ("trend_ranked", "R1", "R0")):
            a, b = (capital, candidate, scaling, *path), (capital, baseline, scaling, *path)
            if not series[a].index.equals(series[b].index):
                raise ValueError("Paired comparison dates differ")
            for field in ("core_source_hash", "data_hash"):
                if results[a]["provenance"][field] != results[b]["provenance"][field]:
                    raise ValueError(f"Paired comparison {field} differs")
            delta = series[a] - series[b]
            year_a = {r["year"]: r for r in results[a]["year_contributions"]}
            year_b = {r["year"]: r for r in results[b]["year_contributions"]}
            contrasts.append({"effect": effect, "candidate": candidate, "baseline": baseline,
                "initial_cash": capital, "risk_scaling": scaling, "path": LABELS[path], "n_dates": len(delta),
                "mean_daily_return_difference_bp": float(delta.mean() * 10000),
                "terminal_return_difference": results[a]["metrics"]["total_return"] - results[b]["metrics"]["total_return"],
                "fee_difference_cny": results[a]["fees_cny"] - results[b]["fees_cny"],
                "one_way_turnover_difference": results[a]["one_way_turnover"] - results[b]["one_way_turnover"],
                "annual_differences": [{"year": year, "pnl_difference_cny": year_a[year]["pnl_cny"] - year_b[year]["pnl_cny"],
                    "additive_return_contribution_difference": year_a[year]["additive_return_contribution_initial_capital"] - year_b[year]["additive_return_contribution_initial_capital"],
                    "mean_daily_return_difference_bp": float(delta.loc[delta.index.str.startswith(str(year))].mean() * 10000)} for year in year_a],
                "uncertainty": "NOT_APPLICABLE_SYNTHETIC", "economic_confirmation": "BLOCKED_HURDLE"})
    report = {"status": "SYNTHETIC_ENGINEERING_ONLY", "notice": NOTICE, "run_count": len(ordered),
        "provenance": {"matrix_manifest_sha256": hashlib.sha256((matrix_root / "matrix_summary.json").read_bytes()).hexdigest(),
                       "summary_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "source_hashes": sorted({row["provenance"]["source_hash"] for row in ordered}),
                       "core_source_hashes": sorted({row["provenance"]["core_source_hash"] for row in ordered}),
                       "data_hashes": sorted({row["provenance"]["data_hash"] for row in ordered})},
        "grid": {"capitals": CAPITALS, "variants": VARIANTS, "risk_scaling": [False, True],
                 "paths": [{"label": LABELS[p], "commission_multiplier": p[0], "slippage_multiplier": p[1], "execution_delay": p[2]} for p in PATHS]},
        "method": {"turnover": "0.5 * daily absolute traded notional / previous NAV, summed; annualized by 252/sessions",
                   "annual_contribution": "Each year's CNY NAV change / initial capital; sums to full-period return. Year returns compound and are not additive.",
                   "costs": "Fees debit cash; slippage is embedded in fill prices and must not be subtracted again.",
                   "rejections": "Event count includes partial unfilled quantities and retry alarms; not a rejection probability.",
                   "paired_effects": "Same-date arithmetic daily return differences; descriptive only. No winner selection or hypothesis test."},
        "ledger_reconciliation": {"status": "ALL_PASS", "runs_checked": len(ordered), "tolerance_cny": TOLERANCE},
        "runs": ordered, "paired_effects": contrasts}
    lines = ["# 合成数据工程实验汇总", "", f"**{NOTICE}**", "",
        "完整覆盖160配置：4档本金 × E0/R0/E1/R1 × 波动缩放开/关 × 5条预设成本/滑点/延迟路径。未选择优胜配置。",
        "所有160次运行均从现金事件、应收股息及股数×估值价重新构造NAV，通过1e-6元误差门槛；这是独立账簿算术检查，不是独立行情核验。", "",
        "JSON保留全部逐年损益贡献、费用、拒单原因与160组同日配对差异：R0−E0、R1−E1、E1−E0、R1−R0。"
        "年度贡献按年度损益/初始本金相加；年度收益率不能直接相加。", "",
        "统计推断为 `NOT_APPLICABLE_SYNTHETIC`；实际增量运行成本尚未知，经济确认保持 `BLOCKED_HURDLE`。"
        "合成日期不构成真实历史留出或样本外证据；本汇总不改变2025年以来最终留出锁定状态。", "",
        "路径：base=(佣金1×,滑点1×,延迟1日)，cost2_slip2=(2×,2×,1日)，cost3_slip3=(3×,3×,1日)，slip0=(1×,0×,1日)，delay2=(1×,1×,2日)。法定税费不倍增。", "",
        "换手=各日绝对成交额/前日NAV的一半之和。滑点已含在成交价，未重复扣除。拒单列计事件，包括部分成交余额与重试警报。", "",
        "| 本金 | 变体 | 缩放 | 路径 | 合成总收益 | 费用元 | 换手 | 成交数 | 拒单事件 | 平均现金 |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in ordered:
        c = row["config"]
        lines.append(f"| {c['initial_cash']} | {c['variant']} | {'开' if c['risk_scaling'] else '关'} | {row['path']} | "
            f"{row['metrics']['total_return']:.2%} | {row['fees_cny']:.2f} | {row['one_way_turnover']:.2f} | "
            f"{row['fills']} | {row['rejection_events']} | {row['mean_cash_weight']:.1%} |")
    lines += ["", "完整机器可读记录：[SYNTHETIC_EXPERIMENTS.json](SYNTHETIC_EXPERIMENTS.json)。"]
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "SYNTHETIC_EXPERIMENTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output_root / "SYNTHETIC_EXPERIMENTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=Path("runs/matrix"))
    parser.add_argument("--output", type=Path, default=Path("reports/m0_m1"))
    args = parser.parse_args()
    report = summarize(args.matrix, args.output)
    print(f"SYNTHETIC_ENGINEERING_ONLY: {report['run_count']} runs, all ledgers reconciled; {args.output}")
