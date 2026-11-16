"""Independent M8 synthetic execution evidence; no market-data acquisition.

The fixture and Decimal expectations are reviewer-owned, not imported from
implementation tests. The immutable Git baseline is loaded without checkout.
"""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import argparse
import copy
import hashlib
import json
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd

BASE = "3df2391dc646ab98122ac6b029d0ef7a5cef2b32"
D = Decimal


def fixture(amount=10000000):
    days = pd.bdate_range("2020-01-02", periods=35).strftime("%Y-%m-%d").tolist()
    master = dict(instrument_id="REVIEW_SYNTHETIC", asset_type="ETF", board="ETF",
        listed_on="2010-01-01", delisted_on=None,
        available_at="2010-01-01T00:00:00+08:00", account_verified=True,
        benchmark_id="SYNTHETIC_INDEX", industry="SYNTHETIC", lot_size=100,
        tick_size=.001, t_plus=1, status="NORMAL", is_st=False)
    rows = [dict(date=day, instrument_id=master["instrument_id"], open=10.,
        high=10.01, low=9.99, close=10., volume=1000000., amount=float(amount),
        upper_limit=11., lower_limit=9., suspended=False,
        available_at=day + "T16:00:00+08:00") for day in days]
    return dict(calendar=days, instruments=pd.DataFrame([master]),
        bars=pd.DataFrame(rows), actions=pd.DataFrame())


def decision(data, at=20, execution=21, weight=.3, adv=10000000):
    sid = "REVIEW_SYNTHETIC"
    return dict(decision_date=data["calendar"][at], execution_date=data["calendar"][execution],
        weights={sid: weight}, reference_prices={sid: 10.}, adv20={sid: float(adv)})


def market(data, at, volume=None, amount=None):
    mask = data["bars"].date == data["calendar"][at]
    if volume is not None:
        data["bars"].loc[mask, "volume"] = volume
    if amount is not None:
        data["bars"].loc[mask, "amount"] = amount


def load_baseline():
    source = subprocess.check_output(["git", "show", BASE + ":src/quant_research/execution.py"], cwd=ROOT)
    module = types.ModuleType("quant_research._m8_independent_baseline")
    module.__package__ = "quant_research"
    sys.modules[module.__name__] = module
    exec(compile(source, "baseline_execution.py", "exec"), module.__dict__)
    return module.run_backtest, hashlib.sha256(source).hexdigest()


def decimal_money(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def baseline_probe():
    run, digest = load_baseline()
    normal = fixture()
    tiny = fixture()
    market(tiny, 21, 1000., 10000.)
    a = run(normal, [decision(normal)], 100000)
    b = run(tiny, [decision(tiny)], 100000)
    assert list(a["orders"].quantity) == list(b["orders"].quantity) == [3000]
    assert list(b["fills"].quantity) == [3000]
    assert D(str(b["fills"].iloc[0].price)) == D("10.003")
    assert D(str(b["fills"].iloc[0].notional)) == D("30009")
    return dict(status="REPRODUCED", baseline=BASE, source_sha256=digest,
        synthetic=True, order_quantity_normal=3000, order_quantity_low_volume=3000,
        actual_market_quantity=1000, actual_market_amount=10000,
        fill_quantity=3000, fill_price="10.003", fill_notional="30009",
        reviewer_expected_repaired_fill_quantity=0,
        explanation="One percent of 1000 shares is 10 shares, below the 100-share buy lot.")


def repaired_probe():
    from quant_research.execution import run_backtest
    checks = []
    # Independent arithmetic: q*10.003 rounded cents, max(5, 3bp*q*price),
    # cash=100000-notional-fee; marked equity is cash+q*10.
    cases = [("normal", 10000000, 1000000, 10000000, 3000),
        ("old_counterexample", 10000000, 1000, 10000, 0),
        ("actual_amount_binds", 10000000, 1000000, 250000, 200),
        ("actual_shares_binds", 10000000, 25000, 10000000, 200),
        ("historical_adv_binds", 250000, 1000000, 10000000, 200)]
    for label, adv, volume, amount, expected_q in cases:
        data = fixture(adv)
        market(data, 21, volume, amount)
        intent = decision(data, adv=adv)
        saved = copy.deepcopy(intent)
        result = run_backtest(data, [intent], 100000)
        assert intent == saved
        assert list(result["orders"].quantity) == [3000]
        observed = int(result["fills"].quantity.sum())
        assert observed == expected_q, (label, observed, expected_q)
        notional = decimal_money(D(expected_q) * D("10.003"))
        fee = decimal_money(max(D(5), notional * D(".0003"))) if expected_q else D(0)
        cash = D(100000) - notional - fee
        nav = cash + D(expected_q) * D(10)
        final = result["nav"].iloc[-1]
        assert abs(D(str(final.cash_total)) - cash) < D(".0000001")
        assert abs(D(str(final.nav)) - nav) < D(".0000001")
        checks.append(dict(case=label, order_quantity=3000, fill_quantity=expected_q,
            expected_cash=str(cash), expected_nav=str(nav), expected_commission=str(fee)))
    # Two independent past decisions both queue a buy before either executes.
    data = fixture()
    market(data, 23, 1000000, 3000000)
    result = run_backtest(data, [decision(data, 20, 23), decision(data, 21, 23)], 100000)
    assert list(result["orders"].quantity) == [3000, 3000]
    assert list(result["fills"].quantity) == [2900]
    checks.append(dict(case="two_buys_share_actual_amount", orders=[3000, 3000],
        expected_fills=[2900], expected_notional="29008.70", amount_cap="30000"))
    # Queue small buy first, then full sell, same later date; sales execute first.
    # A 3050-share actual cap permits 3000 sell, leaving 50 < one buy lot.
    data = fixture()
    market(data, 25, 305000, 10000000)
    result = run_backtest(data, [decision(data), decision(data, 22, 25, .35),
        decision(data, 23, 25, 0)], 100000)
    same_day = result["fills"].loc[result["fills"].date == data["calendar"][25]]
    assert list(result["orders"].quantity) == [3000, 400, 3000]
    assert list(same_day.side) == ["SELL"] and list(same_day.quantity) == [3000]
    expected_cash = D(100000) - D("30009") - D("9") + D("29991") - D("9")
    assert abs(D(str(result["nav"].iloc[-1].cash_total)) - expected_cash) < D(".0000001")
    checks.append(dict(case="buy_sell_share_actual_quantity", orders=[3000,400,3000],
        expected_same_day_sides=["SELL"], expected_same_day_fills=[3000],
        expected_final_cash=str(expected_cash), share_cap=3050))
    for field in ("volume", "amount"):
        for invalid in (0., -1., float("nan"), float("inf")):
            data = fixture()
            data["bars"].loc[data["bars"].date == data["calendar"][21], field] = invalid
            result = run_backtest(data, [decision(data)], 100000)
            assert list(result["orders"].quantity) == [3000]
            assert result["fills"].empty
            assert result["nav"].iloc[-1].cash_total == 100000
            checks.append(dict(case="invalid_actual_" + field, value=str(invalid), expected_fills=0))
    return dict(status="PASS", synthetic=True, checks=checks,
        source_sha256=hashlib.sha256((ROOT / "src/quant_research/execution.py").read_bytes()).hexdigest(),
        limitations=["Daily aggregate synthetic checks do not establish intraday queue liquidity.",
            "No inference is made about counts of affected old historical fills."])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("baseline", "repaired"), required=True)
    args = parser.parse_args()
    result = baseline_probe() if args.phase == "baseline" else repaired_probe()
    target = ROOT / "reports/m8_review" / ("independent_capacity_" + args.phase + ".json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "path": str(target)}))
