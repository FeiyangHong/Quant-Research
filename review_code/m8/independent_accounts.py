"""Independent Decimal account reconstruction; no production engine imports.

Actual fills are assertions to audit against admitted source bars and immutable
intent, then inputs to an independently maintained share/cash/receivable ledger.
No actual NAV is used to generate any expected account value or order quantity.
"""
import argparse
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = Decimal
ZERO = D(0)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_float=D)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def money(value):
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def close(actual, expected, label, tolerance=D("0.000001")):
    assert abs(D(str(actual))-expected) <= tolerance, (label, str(actual), str(expected))


def load_stage(path):
    result = {name:read(path/(name+".json"))["records"] for name in ("bars","instruments","actions","benchmark")}
    raw = read(path/"calendar.json")
    result["calendar"] = raw if isinstance(raw,list) else raw.get("sessions",raw.get("calendar"))
    assert result["calendar"], raw
    return result


def review_account(record, source):
    path = ROOT/record["artifact_directory"]
    for name,digest in record["exported_tables"].items():
        assert sha(path/name) == digest, (path,name)
    actual = {name:read(path/(name+".json")) for name in ("nav","positions","fills","orders","decisions","cash_events","share_events","order_events","config")}
    calendar = source["calendar"]
    index = {day:i for i,day in enumerate(calendar)}
    start,end = ("2020-01-01","2021-12-31") if record["period"] == "development" else ("2022-01-01","2024-12-31")
    funded = [d for d in calendar if start <= d <= end]
    assert [r["date"] for r in actual["nav"]] == funded
    assert actual["config"]["initial_cash"] == 100000
    for field in ("variant","cost_multiplier","slippage_multiplier","execution_delay","risk_scaling","signal_release_delay","seed","annual_incremental_cost"):
        assert actual["config"][field] == record[field], (record["trial_id"],field)
    assert actual["config"]["sample"] == record["period"]
    assert actual["config"]["annual_incremental_cost"] is None
    bars = {(r["date"],r["instrument_id"]):r for r in source["bars"]}
    masters = defaultdict(list)
    for r in source["instruments"]:
        masters[r["instrument_id"]].append(r)
    def master(sid,day):
        choices = [r for r in masters[sid] if r["available_at"] <= day+"T09:30:00+08:00"]
        assert choices
        return sorted(choices,key=lambda r:r["available_at"])[-1]
    def adv(sid,day):
        days = calendar[index[day]-19:index[day]+1]
        assert len(days) == 20
        return sum(D(str(bars[d,sid]["amount"])) for d in days)/20
    orders = {r["order_id"]:r for r in actual["orders"]}
    by_fill,by_order,by_position,by_event = (defaultdict(list) for _ in range(4))
    for r in actual["fills"]: by_fill[r["date"]].append(r)
    for r in actual["orders"]: by_order[r["decision_date"]].append(r)
    for r in actual["positions"]: by_position[r["date"]].append(r)
    for r in source["actions"]:
        if start <= r["ex_date"] <= end:
            assert r["action_type"] in ("CASH_DIVIDEND","SPLIT"), r
            by_event[r["ex_date"]].append(r)
    decisions = {r["decision_at"][:10]:r for r in actual["decisions"]}
    cash,positions,marks = D(100000),defaultdict(int),{}
    lots,record_quantity,receivables = defaultdict(list),{},[]
    max_residual,expected_cash_events,expected_share_events = ZERO,[],[]
    daily,fill_checks,intent_checks,capacity_checks = [],0,0,0
    maximum_participation = dict(shares=ZERO,amount=ZERO,historical=ZERO)
    def split(action,day):
        sid = action["instrument_id"]
        if action.get("action_status") == "CANCELLED": return
        factor = D(str(action["share_factor"]))
        total = D(positions[sid])*factor
        policy = action.get("rounding_policy") or "EXACT"
        rounding = {"FLOOR":ROUND_FLOOR,"CEIL":ROUND_CEILING,"EXACT":ROUND_FLOOR}[policy]
        new = int(total.to_integral_value(rounding=rounding))
        if policy == "EXACT": assert D(new) == total
        # Allocate integer rounding to the latest-locked lots; source policy is
        # account-total rounding, not independently rounded per acquisition.
        converted = [[int((D(q)*factor).to_integral_value(rounding=ROUND_FLOOR)),lock] for q,lock in lots[sid]]
        remainder = new-sum(q for q,lock in converted)
        fractional = [j for j,(q,lock) in enumerate(lots[sid]) if D(q)*factor != converted[j][0]]
        for j in sorted(fractional,key=lambda j:(converted[j][1],j),reverse=True):
            if remainder <= 0: break
            converted[j][0] += 1
            remainder -= 1
        assert remainder == 0
        old = positions[sid]
        positions[sid],lots[sid] = new,converted
        if sid in marks: marks[sid] /= factor
        expected_share_events.append(dict(date=day,instrument_id=sid,old_quantity=old,new_quantity=new,share_factor=str(factor)))
    for day,observed in zip(funded,actual["nav"]):
        withdrawable = cash
        for action in by_event[day]:
            sid = action["instrument_id"]
            if action["action_type"] == "SPLIT":
                if action.get("effective_phase","BOD") == "BOD": split(action,day)
                continue
            entitled = record_quantity.get((action["record_date"],sid),0)
            amount = money(D(entitled)*D(str(action["cash_per_share"])))
            pay = action["pay_date"]
            if action.get("settlement_mode") == "RULE_BASED_SIMULATION" and action.get("settlement_rule_credit_basis") == "NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER":
                pay = calendar[index[action["participant_transfer_date"]]+1]
                assert action["modeled_cash_date"] == pay
            if amount:
                receivables.append((pay,amount,sid))
                expected_cash_events.append(dict(date=day,event="DIVIDEND_RECEIVABLE",instrument_id=sid,amount=str(amount)))
            if sid in marks: marks[sid] = max(ZERO,marks[sid]-D(str(action["cash_per_share"])))
        for item in list(receivables):
            pay,amount,sid = item
            if pay <= day:
                cash += amount
                withdrawable += amount
                receivables.remove(item)
                expected_cash_events.append(dict(date=day,event="DIVIDEND_PAID",instrument_id=sid,amount=str(amount)))
        capacity = defaultdict(lambda:[ZERO,ZERO,ZERO])
        daily_limits = {}
        for r in actual["orders"]:
            if r["execution_date"] == day and r.get("adv20") is not None:
                lim = D(str(r["adv20"]))*D("0.01")
                daily_limits[r["instrument_id"]] = min(daily_limits.get(r["instrument_id"],lim),lim)
        for fill in by_fill[day]:
            sid,q = fill["instrument_id"],fill["quantity"]
            order = orders[fill["order_id"]]
            raw = bars[day,sid]
            assert order["execution_date"] == day and order["decision_date"] < day
            assert sid == order["instrument_id"] and fill["side"] == order["side"]
            assert 0 < q <= order["quantity"] == order["qty_requested"]
            assert not raw["suspended"] and D(str(raw["amount"])) > 0 and D(str(raw["volume"])) > 0
            buy = fill["side"] == "BUY"
            meta = master(sid,day)
            tick = D(str(meta["tick_size"]))
            slip = D("0.0003")*record["slippage_multiplier"]
            raw_open = D(str(raw["open"]))
            adverse = raw_open*(1+slip if buy else 1-slip)
            price = (adverse/tick).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*tick
            close(fill["price"],price,"fill price")
            assert D(str(raw["low"])) <= price <= D(str(raw["high"]))
            assert D(str(raw["lower_limit"])) <= price <= D(str(raw["upper_limit"]))
            assert raw_open < D(str(raw["upper_limit"])) if buy else raw_open > D(str(raw["lower_limit"]))
            nominal = money(D(q)*price)
            fee = money(max(D(5),nominal*D("0.0003"))*record["cost_multiplier"])
            for field,value in (("notional",nominal),("commission",fee),("fees",fee),("stamp_duty",ZERO),("transfer_fee",ZERO),
                ("slippage_cost",money(D(q)*abs(price-raw_open)))):
                close(fill[field],value,field)
            used = capacity[sid]
            used[0] += D(q)
            used[1] += max(D(q)*price,nominal)
            used[2] += D(q)*max(price,D(str(order["reference_price"])))
            limits = [D(str(raw["volume"]))*D("0.01"),D(str(raw["amount"]))*D("0.01"),daily_limits[sid]]
            for k,key in enumerate(("shares","amount","historical")):
                assert used[k] <= limits[k]+D("0.0000001"), (day,sid,key,used[k],limits[k])
                maximum_participation[key] = max(maximum_participation[key],used[k]/(limits[k]*100))
            capacity_checks += 1
            if buy:
                assert q % 100 == 0
                cash -= nominal+fee
                withdrawable = max(ZERO,withdrawable-nominal-fee)
                lots[sid].append([q,index[day]+int(meta["t_plus"])])
                positions[sid] += q
            else:
                assert q <= sum(lot[0] for lot in lots[sid] if lot[1] <= index[day])
                remaining = q
                for lot in lots[sid]:
                    if lot[1] <= index[day]:
                        remove = min(remaining,lot[0]); lot[0] -= remove; remaining -= remove
                assert remaining == 0
                lots[sid] = [lot for lot in lots[sid] if lot[0]]
                positions[sid] -= q
                cash += nominal-fee
            assert cash >= 0 and positions[sid] >= 0
            fill_checks += 1
        for sid,q in positions.items():
            raw = bars.get((day,sid))
            if raw and not raw["suspended"] and D(str(raw["volume"])) > 0:
                marks[sid] = D(str(raw["close"]))
        for action in by_event[day]:
            if action["action_type"] == "SPLIT" and action.get("effective_phase","BOD") == "EOD": split(action,day)
        holding = sum(D(q)*marks.get(sid,ZERO) for sid,q in positions.items())
        owing = sum((r[1] for r in receivables),ZERO)
        nav = cash+holding+owing
        for field,value in (("cash_total",cash),("cash",cash),("cash_available",cash),("cash_withdrawable",min(withdrawable,cash)),
                            ("cash_reserved",ZERO),("dividend_tax_payable",ZERO),("holdings_value",holding),("receivables",owing),("nav",nav)):
            close(observed[field],value,(day,field))
        max_residual = max(max_residual,abs(D(str(observed["nav"]))-nav))
        assert not observed["valuation_uncertainty"]
        expected_pos = {sid:q for sid,q in positions.items() if q}
        assert {p["instrument_id"]:p["quantity"] for p in by_position[day]} == expected_pos
        for p in by_position[day]:
            sid = p["instrument_id"]
            close(p["price"],marks[sid],"position raw mark")
            close(p["market_value"],D(p["quantity"])*marks[sid],"position value")
            assert p["sellable_quantity"] == sum(q for q,lock in lots[sid] if lock <= index[day])
            assert p["locked_quantity"] == positions[sid]-p["sellable_quantity"]
        for sid,q in positions.items(): record_quantity[day,sid] = q
        if day in decisions:
            decision = decisions[day]
            for order in by_order[day]:
                if order["parent_order_id"] is not None or order["intent_type"] != "REBALANCE": continue
                sid = order["instrument_id"]
                reference = D(str(bars[day,sid]["close"]))
                close(order["source_reference_price"],reference,"intent source reference")
                if order["reference_basis"] == "POST_EOD_ADJUSTED":
                    factor = next(D(str(a["share_factor"])) for a in by_event[day] if a["instrument_id"] == sid and a["action_type"] == "SPLIT")
                    reference /= factor
                close(order["reference_price"],reference,"immutable reference")
                close(order["adv20"],adv(sid,day),"historical ADV",D("0.00001"))
                weight = D(str(decision["weights"].get(sid,0)))
                target = int(nav*weight/reference)//100*100
                delta = target-positions[sid]
                assert order["quantity"] == abs(delta), (day,sid,order["quantity"],abs(delta))
                assert order["side"] == ("BUY" if delta>0 else "SELL")
                intent_checks += 1
        daily.append(dict(date=day,cash=str(cash),holding_value=str(holding),receivables=str(owing),nav=str(nav),positions=dict(expected_pos)))
    actual_dividends = [r for r in actual["cash_events"] if r["event"] in ("DIVIDEND_RECEIVABLE","DIVIDEND_PAID")]
    assert len(actual_dividends) == len(expected_cash_events)
    for expected,observed in zip(expected_cash_events,actual_dividends):
        for field in ("date","event","instrument_id"): assert expected[field] == observed[field]
        close(observed["amount"],D(expected["amount"]),"dividend source entitlement")
    for expected in expected_share_events:
        hits = [r for r in actual["share_events"] if r["date"] == expected["date"] and r["instrument_id"] == expected["instrument_id"]]
        assert len(hits) == 1
        for field in ("old_quantity","new_quantity"): assert hits[0][field] == expected[field]
    output = ROOT/"reports/m8_review/independent_ledgers"/(record["trial_id"]+".json")
    output.parent.mkdir(exist_ok=True)
    payload = (json.dumps(daily,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    if output.exists():
        # The first exploratory ledger used Windows text-mode CRLF. Retain
        # those exact bytes; either serialization must have identical facts.
        assert output.read_bytes() in (payload,payload.replace(b"\n",b"\r\n")), (record["trial_id"],"independent ledger changed; retain and register correction")
    else:
        output.write_bytes(payload)
    return dict(trial_id=record["trial_id"],sessions=len(funded),fill_checks=fill_checks,original_intent_checks=intent_checks,
        capacity_checks=capacity_checks,dividend_cash_events=len(expected_cash_events),share_events=len(expected_share_events),
        maximum_nav_difference_cny=str(max_residual),maximum_participation={k:str(v) for k,v in maximum_participation.items()},
        independent_ledger_sha256=sha(output),independent_ledger_path=output.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage",type=Path,required=True)
    parser.add_argument("--phase",choices=["base","all"],required=True)
    args = parser.parse_args()
    records = read(ROOT/"reports/m8_rotation/ACCOUNT_PATHS.json")
    wanted = [r for r in records if args.phase == "all" or r["path"] == "base"]
    assert len(wanted) == (8 if args.phase == "base" else 32)
    admission = read(ROOT/"reports/m8_review/HOLDING_ADMISSION.json")
    assert admission["decision"] == "ADMIT_DAILY_SCREEN" and admission["admission_scope"] == "FULL_HOLDING_DEPENDENCIES"
    assert admission["stage_manifest_sha256"] == sha(args.stage/"manifest.json")
    signal_review = read(ROOT/"reports/m8_review"/("independent_signals_"+args.phase+".json"))
    assert signal_review["decision"] == "PASS_INDEPENDENT_MONTHLY_SIGNALS"
    assert signal_review["stage_manifest_sha256"] == sha(args.stage/"manifest.json")
    source = load_stage(args.stage)
    reviews = [review_account(r,source) for r in wanted]
    result = dict(decision="PASS_DATA_AND_ACCOUNTING",author_role="INDEPENDENT_REVIEWER",reviewer="/root/m8_independent",
        reviewed_at=datetime.now(timezone.utc).isoformat(),base_account_hashes={r["trial_id"]:r["exported_tables"] for r in wanted if r["path"] == "base"},
        accounts=reviews,stage_manifest_sha256=sha(args.stage/"manifest.json"),
        source_admission_sha256=sha(ROOT/"reports/m8_review/HOLDING_ADMISSION.json"),
        independent_signal_review_sha256=sha(ROOT/"reports/m8_review"/("independent_signals_"+args.phase+".json")),
        method="Independent Decimal from100k cash/zero positions, source action entitlements and audited fills. Raw-source equality and signals checked separately. Actual NAV never generates expected NAV or immutable intent.",
        profitability_is_not_a_gate=True)
    name = "BASE_INDEPENDENT_REVIEW.json" if args.phase == "base" else "ALL_ACCOUNT_INDEPENDENT_REVIEW.json"
    (ROOT/"reports/m8_review"/name).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(name,len(reviews))


if __name__ == "__main__": main()
