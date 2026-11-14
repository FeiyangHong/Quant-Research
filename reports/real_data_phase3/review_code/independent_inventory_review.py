"""Independent, read-only calendar and ETF inventory review; no return metrics.

Run only after both registered matrices are complete and the reviewer releases
result access.  This scratch reviewer imports no execution/strategy code and
does not modify frozen source, datasets, runs or registries.

python work/independent_inventory_review.py --selfcheck
python work/independent_inventory_review.py --run-dir RUN --dataset DATA \
    --funded-start 2022-01-01

For a matrix, build_dataset_context(DATA) once and pass context= to audit_run.
The returned dictionary contains checks/counts/hashes, never NAV or returns.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path


PERIODS = {"development": ("2016-01-01", "2021-12-31"),
           "validation": ("2022-01-01", "2024-12-31")}
REVIEW_TABLES = ("nav", "positions", "fills", "share_events", "rights", "cash_events")


class ReviewFailure(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReviewFailure(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ReviewFailure("Nonfinite JSON constant: " + value)))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer(value, label):
    number = Decimal(str(value))
    require(number.is_finite() and number >= 0 and number == number.to_integral_value(),
            label + ": nonnegative integer required")
    return int(number)


def day_of(value):
    require(isinstance(value, str) and len(value) == 10, "Invalid ISO session date")
    require(date.fromisoformat(value).isoformat() == value, "Invalid ISO session date")
    return value


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "Action timestamp lacks timezone")
    return result


def action_cutoff(action):
    phase = action.get("effective_phase") or "BOD"
    require(phase in ("BOD", "EOD"), "Unknown action phase")
    clock = "15:00:00" if phase == "EOD" else "09:30:00"
    return timestamp(action["ex_date"] + "T" + clock + "+08:00")


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_dataset_context(dataset_directory):
    """Hash admitted input files once; cache calendar/actions/master, not prices.

    Pandas is used only to reproduce the runner's documented data identity
    serialization.  Inventory and money arithmetic below uses independent
    standard-library code, without importing the engine or its helpers.
    """
    import pandas as pd

    directory = Path(dataset_directory).resolve()
    manifest = read_json(directory / "manifest.json")
    objects, checked = {}, {}
    for name in ("calendar", "instruments", "bars", "actions", "benchmark"):
        path = directory / (name + ".json")
        actual = sha256(path)
        require(actual == manifest["file_sha256"].get(path.name),
                "Admitted dataset hash mismatch: " + path.name)
        checked[path.name] = actual
        objects[name] = read_json(path)
    calendar = [day_of(day) for day in objects["calendar"]]
    require(calendar == sorted(set(calendar)) and bool(calendar), "Invalid admitted calendar")
    require(calendar[-1] < "2025-01-01", "Final holdout calendar is locked")
    content = {"calendar": calendar, "manifest": manifest}
    for name in ("instruments", "bars", "actions", "benchmark"):
        obj = objects[name]
        content[name] = json.loads(pd.DataFrame(obj["records"], columns=obj["columns"])
                                  .to_json(orient="records", date_format="iso", double_precision=15))
    return {"directory": str(directory), "calendar": calendar,
            "actions": objects["actions"]["records"],
            "instruments": objects["instruments"]["records"],
            "data_hash": digest(content), "manifest_sha256": sha256(directory / "manifest.json"),
            "input_file_sha256": checked}


def resolve_actions(source, calendar, start, end):
    """Resolve dated terms independently, retaining late unowned share events."""
    grouped = defaultdict(list)
    for action in source:
        grouped[action["action_id"]].append(action)
    resolved = {}
    for identity, versions in grouped.items():
        active = [a for a in versions if calendar[0] <= a["ex_date"] <= end]
        if not active:
            continue
        known = [a for a in active if timestamp(a["available_at"]) <= action_cutoff(a)]
        if known:
            candidate = max(known, key=lambda a: timestamp(a["available_at"]))
        elif all(a["action_type"] == "SPLIT" for a in active):
            candidate = min(active, key=lambda a: timestamp(a["available_at"]))
        elif all(a["ex_date"] < start for a in active):
            candidate = min(active, key=lambda a: timestamp(a["available_at"]))
        else:
            raise ReviewFailure("Action unavailable at effective time: " + identity)
        resolved[identity] = candidate
    return resolved


def dividend_key(row):
    return (row["date"], row["event"], row["instrument_id"], str(money(row["amount"])),
            row.get("settlement_mode"), row.get("actual_pay_date"),
            row.get("scheduled_pay_date"), row.get("modeled_pay_date"))


def audit_records(tables, context, config, funded_start):
    """Replay anonymous records; also used by the invented-data selfcheck."""
    start, end = PERIODS[config["sample"]]
    require(funded_start == start, "Funded start differs from registered sample")
    calendar = context["calendar"]
    expected_dates = [d for d in calendar if start <= d <= end]
    require(bool(expected_dates), "No funded exchange sessions")
    dates = [day_of(row["date"]) for row in tables["nav"]]
    require(dates == expected_dates,
            "NAV session list differs from admitted funded calendar: "
            + str({"missing": sorted(set(expected_dates) - set(dates))[:10],
                   "extra": sorted(set(dates) - set(expected_dates))[:10],
                   "expected_count": len(expected_dates), "observed_count": len(dates)}))
    date_set = set(dates)
    actions = resolve_actions(context["actions"], calendar, start, end)
    all_source_ids = {a["action_id"] for a in context["actions"]}
    masters = defaultdict(list)
    for row in context["instruments"]:
        masters[row["instrument_id"]].append(row)
    rows_by_day = {name: defaultdict(list) for name in REVIEW_TABLES if name != "nav"}
    warmup_count = 0
    for name, by_day in rows_by_day.items():
        for row in tables[name]:
            day = day_of(row["date"])
            if name == "share_events" and day < start:
                require(row["action_id"] in all_source_ids
                        and row.get("status") == "UNOWNED_PRE_ACCOUNT_EVENT"
                        and integer(row["old_quantity"], "warmup old") == 0
                        and integer(row["new_quantity"], "warmup new") == 0,
                        "Pre-account share metadata mutated units or lacks a source")
                matching = [a for a in context["actions"] if a["action_id"] == row["action_id"]]
                require(any(a["ex_date"] == day and a["instrument_id"] == row["instrument_id"]
                            and a["action_type"] in ("SPLIT", "CASH_DIVIDEND") for a in matching),
                        "Pre-account share metadata does not match dated source")
                warmup_count += 1
                continue
            require(day in date_set, name + ": row outside funded calendar")
            by_day[day].append(row)
    actions_by_day = defaultdict(list)
    for action in actions.values():
        if start <= action["ex_date"] <= end:
            require(action["ex_date"] in date_set, "Corporate action outside exchange calendar")
            actions_by_day[action["ex_date"]].append(action)

    holdings, snapshots, rights = defaultdict(int), {}, {}
    fill_ids, share_ids = set(), set()
    expected_dividends, actual_dividends = Counter(), Counter()
    pending = []
    share_details = []
    count_positions = count_fills = count_rights = count_dividends = 0
    stress = config.get("cash_delay_sessions", 0)
    require(type(stress) is int and stress in (0, 1, 3), "Invalid cash delay stress")

    def apply_split(action, event):
        sid, identity = action["instrument_id"], action["action_id"]
        require(identity not in share_ids, "Duplicate share application: " + identity)
        share_ids.add(identity)
        require(event["instrument_id"] == sid and event["date"] == action["ex_date"]
                and event.get("effective_phase") == (action.get("effective_phase") or "BOD"),
                "Share event identity/phase differs from admitted source: " + identity)
        old = holdings[sid]
        require(integer(event["old_quantity"], "split old") == old,
                "Share event old units differ from independent inventory: " + identity)
        status = event["status"]
        late = timestamp(action["available_at"]) > action_cutoff(action)
        if action.get("action_usage_scope") == "PRE_LISTING_METADATA_ONLY":
            require(status == "PRE_LISTING_METADATA_ONLY" and old == 0
                    and all(action["ex_date"] < row["listed_on"] for row in masters[sid]),
                    "Invalid pre-listing metadata: " + identity)
            new = old
        elif late:
            require(status == "UNOWNED_TERMS_PENDING" and old == 0,
                    "Late ratio applied to owned units: " + identity)
            new = old
        elif (action.get("action_status") or "CONFIRMED") == "CANCELLED":
            require(status == "CANCELLED_NO_MUTATION", "Canceled action applied: " + identity)
            new = old
        else:
            require(status == "APPLIED" and (action.get("action_status") or "CONFIRMED") == "CONFIRMED",
                    "Unconfirmed or missing share application: " + identity)
            factor = Decimal(str(action["share_factor"]))
            require(factor.is_finite() and factor > 0, "Invalid admitted split factor")
            require(Decimal(str(event["share_factor"])) == factor, "Output split factor differs from source")
            exact = Decimal(old) * factor
            rounding = action.get("rounding_policy") or "EXACT"
            require(event.get("rounding_policy") == rounding, "Output rounding policy differs from source")
            if rounding == "EXACT":
                require(exact == exact.to_integral_value(), "Fractional EXACT entitlement")
                new = int(exact)
            else:
                require(rounding in ("FLOOR", "CEIL"), "Unknown rounding policy")
                new = int(exact.to_integral_value(rounding=ROUND_FLOOR if rounding == "FLOOR" else ROUND_CEILING))
                index = calendar.index(action["ex_date"])
                record = action["ex_date"] if action.get("effective_phase") == "EOD" else calendar[index - 1]
                require(action.get("record_date") == record, "Split ownership boundary differs from source")
            require(abs(Decimal(str(event["rounding_share_delta"])) - (Decimal(new) - exact)) <= Decimal("1e-8"),
                    "Wrong aggregate rounding residue: " + identity)
            share_details.append({"action_id": identity, "instrument_id": sid,
                                  "date": action["ex_date"], "phase": action.get("effective_phase") or "BOD",
                                  "old_quantity": old, "new_quantity": new,
                                  "rounding_policy": rounding})
        require(integer(event["new_quantity"], "split new") == new,
                "Share event violates source aggregate rounding: " + identity)
        holdings[sid] = new

    for day in dates:
        source_today = sorted(actions_by_day[day], key=lambda a: a["action_id"])
        split_today = {a["action_id"]: a for a in source_today if a["action_type"] == "SPLIT"}
        output_today = rows_by_day["share_events"][day]
        require(Counter(e["action_id"] for e in output_today) == Counter(list(split_today)),
                "Missing, duplicate or extra source share event on " + day)
        output_map = {e["action_id"]: e for e in output_today}
        for action in split_today.values():
            if (action.get("effective_phase") or "BOD") == "BOD":
                apply_split(action, output_map[action["action_id"]])
        for action in source_today:
            sid, kind = action["instrument_id"], action["action_type"]
            if kind == "LIQUIDATION":
                entitled = snapshots.get(action["record_date"], {}).get(sid, 0)
                rights[action["action_id"]] = {"instrument_id": sid, "entitled_quantity": entitled,
                    "retired_quantity": holdings[sid], "record_date": action["record_date"], "retirement_date": day}
                holdings[sid] = 0
            elif kind == "CASH_DIVIDEND":
                require(action["record_date"] < day, "Dividend record date is not prior to ex date")
                entitled = snapshots.get(action["record_date"], {}).get(sid, 0)
                amount = money(Decimal(entitled) * Decimal(str(action["cash_per_share"])))
                if not amount:
                    continue
                modeled = action.get("settlement_mode") == "RULE_BASED_SIMULATION"
                base_date = action["pay_date"]
                if modeled and action.get("settlement_rule_credit_basis") == "NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER":
                    base_date = action["modeled_cash_date"]
                    transfer = action["participant_transfer_date"]
                    ti = bisect_left(calendar, transfer)
                    require(ti == len(calendar) or calendar[ti] == transfer, "Transfer date is not an exchange session")
                    require(ti + 1 >= len(calendar) or calendar[ti + 1] == base_date,
                            "Modeled cash date does not follow participant transfer")
                pay_index = bisect_left(calendar, base_date) + (stress if modeled else 0)
                payment = calendar[pay_index] if pay_index < len(calendar) else None
                event = {"date": day, "event": "DIVIDEND_RECEIVABLE", "instrument_id": sid,
                         "amount": str(amount), "settlement_mode": "RULE_BASED_SIMULATION" if modeled else "SCHEDULED",
                         "actual_pay_date": None if modeled else action["pay_date"],
                         "scheduled_pay_date": action["pay_date"],
                         "modeled_pay_date": payment if modeled else None}
                expected_dividends[dividend_key(event)] += 1
                pending.append((payment, event))
                count_dividends += 1
        for pay_date, event in list(pending):
            if pay_date is not None and pay_date <= day:
                paid = dict(event, date=day, event="DIVIDEND_PAID")
                expected_dividends[dividend_key(paid)] += 1
                pending.remove((pay_date, event))
        for fill in rows_by_day["fills"][day]:
            sid, identity = fill["instrument_id"], fill["order_id"]
            require(identity not in fill_ids, "Duplicate fill order ID")
            fill_ids.add(identity)
            require(masters[sid] and all(row["asset_type"] == "ETF" for row in masters[sid]),
                    "Inventory review supports admitted ETFs only")
            quantity = integer(fill["quantity"], "fill quantity")
            require(quantity > 0 and fill["side"] in ("BUY", "SELL"), "Invalid fill side/units")
            if fill["side"] == "BUY":
                require(quantity % 100 == 0, "Buy violates 100-unit lot")
                holdings[sid] += quantity
            else:
                require(holdings[sid] >= quantity, "Sale exceeds reconstructed inventory")
                holdings[sid] -= quantity
            count_fills += 1
        for action in split_today.values():
            if action.get("effective_phase") == "EOD":
                apply_split(action, output_map[action["action_id"]])
        positions = rows_by_day["positions"][day]
        require(len(positions) == len({p["instrument_id"] for p in positions}), "Duplicate EOD instrument position")
        observed = {}
        for position in positions:
            sid = position["instrument_id"]
            quantity = integer(position["quantity"], "position quantity")
            observed[sid] = quantity
            require(integer(position["sellable_quantity"], "sellable units")
                    + integer(position["locked_quantity"], "locked units") == quantity,
                    "Sellable plus locked units differs from total units")
            require(quantity == holdings[sid], "EOD inventory mismatch: " + day + "/" + sid)
            count_positions += 1
        require({s: q for s, q in observed.items() if q} == {s: q for s, q in holdings.items() if q},
                "Reconstructed holding missing from EOD positions on " + day)
        expected_rights = {identity: right for identity, right in rights.items()
                           if right["entitled_quantity"] or right["retired_quantity"]}
        actual_rights = rows_by_day["rights"][day]
        require(Counter(r["entitlement_action_id"] for r in actual_rights) == Counter(list(expected_rights)),
                "Missing, extra or duplicate liquidation right on " + day)
        for right in actual_rights:
            expected = expected_rights[right["entitlement_action_id"]]
            require(all(right[k] == v for k, v in expected.items()), "Liquidation quantity/record-date mismatch")
            count_rights += 1
        for event in rows_by_day["cash_events"][day]:
            if event["event"] in ("DIVIDEND_RECEIVABLE", "DIVIDEND_PAID"):
                actual_dividends[dividend_key(event)] += 1
        snapshots[day] = dict(holdings)
    require(actual_dividends == expected_dividends,
            "Dividend entitlement, rounding, settlement date or duplicate payment mismatch: "
            + str({"missing_count": sum((expected_dividends - actual_dividends).values()),
                   "extra_count": sum((actual_dividends - expected_dividends).values())}))
    return {"status": "PASS", "calendar": "EXACT_ADMITTED_FUNDED_EXCHANGE_SESSIONS",
            "sessions_checked": len(dates), "funded_start": start, "funded_end": end,
            "positions_checked": count_positions, "fills_checked": count_fills,
            "source_share_events_checked": len(share_ids), "pre_account_metadata_checked": warmup_count,
            "applied_share_events": share_details, "liquidation_right_snapshots_checked": count_rights,
            "dividend_entitlements_checked": count_dividends,
            "dividend_cash_events_checked": sum(actual_dividends.values()),
            "dividend_receivables_unpaid_at_end": len(pending),
            "scope": "Independent source-bound aggregate units, share rounding, EOD positions, calendar, dividend entitlements and modeled cash dates.",
            "limitations": ["No return metrics or prices are computed or verified.",
                "T+1 lot allocation and order sizing are not independently replayed; sellable+locked identity is checked.",
                "Liquidation retirement/entitlement quantities are replayed; installment cash valuation is not independently verified.",
                "Cash dates are checks of the declared model, not evidence of actual broker receipts."]}


def audit_run(run_directory, dataset_directory, funded_start, *, context=None):
    directory = Path(run_directory).resolve()
    context = build_dataset_context(dataset_directory) if context is None else context
    require(context["directory"] == str(Path(dataset_directory).resolve()), "Cached dataset path mismatch")
    config, provenance = read_json(directory / "config.json"), read_json(directory / "provenance.json")
    require(config["sample"] in PERIODS and config.get("live_enabled") is False, "Unsupported run sample or live mode")
    require(provenance["config_hash"] == digest(config), "Run configuration hash mismatch")
    require(provenance["data_hash"] == context["data_hash"], "Run does not bind supplied admitted dataset")
    require(provenance["run_id"] == directory.name, "Run directory/provenance identity mismatch")
    hashes = read_json(directory / "table_hashes.json")
    tables = {}
    for name in REVIEW_TABLES:
        path = directory / (name + ".json")
        require(sha256(path) == hashes.get(name), "Run inventory table hash mismatch: " + name)
        tables[name] = read_json(path)
        require(isinstance(tables[name], list), "Run table is not a record list")
    result = audit_records(tables, context, config, funded_start)
    result.update(run_id=directory.name, dataset_directory=context["directory"],
                  dataset_manifest_sha256=context["manifest_sha256"], data_hash=context["data_hash"],
                  config_hash=provenance["config_hash"], review_script_sha256=sha256(__file__),
                  checked_table_sha256={name: hashes[name] for name in REVIEW_TABLES})
    return result


def selfcheck():
    """Invented three-session split/odd-lot/dividend fixture; no actual run I/O."""
    dates = ["2022-01-04", "2022-01-05", "2022-01-06"]
    sid = "sh.INVENTED"
    split = {"action_id": "invented_split", "instrument_id": sid, "action_type": "SPLIT",
             "ex_date": dates[1], "record_date": dates[1], "effective_phase": "EOD",
             "available_at": "2022-01-03T21:00:00+08:00", "share_factor": 1.005,
             "rounding_policy": "CEIL", "action_status": "CONFIRMED"}
    dividend = {"action_id": "invented_div", "instrument_id": sid, "action_type": "CASH_DIVIDEND",
                "ex_date": dates[2], "record_date": dates[1], "pay_date": dates[2],
                "available_at": "2022-01-03T21:00:00+08:00", "cash_per_share": .01,
                "settlement_mode": "RULE_BASED_SIMULATION"}
    context = {"calendar": dates, "actions": [split, dividend],
               "instruments": [{"instrument_id": sid, "asset_type": "ETF", "listed_on": "2020-01-01"}]}
    tables = {name: [] for name in REVIEW_TABLES}
    tables["nav"] = [{"date": d} for d in dates]
    tables["positions"] = [{"date": d, "instrument_id": sid, "quantity": q,
                             "sellable_quantity": q, "locked_quantity": 0}
                            for d, q in zip(dates, (100, 201, 0))]
    tables["fills"] = [{"date": d, "instrument_id": sid, "side": side, "quantity": q, "order_id": str(i)}
                       for i, (d, side, q) in enumerate(zip(dates, ("BUY", "BUY", "SELL"), (100, 100, 201)))]
    tables["share_events"] = [{"date": dates[1], "action_id": "invented_split", "instrument_id": sid,
        "effective_phase": "EOD", "status": "APPLIED", "old_quantity": 200, "new_quantity": 201,
        "share_factor": 1.005, "rounding_policy": "CEIL", "rounding_share_delta": 0}]
    tables["cash_events"] = [{"date": dates[2], "event": event, "instrument_id": sid, "amount": 2.01,
        "settlement_mode": "RULE_BASED_SIMULATION", "actual_pay_date": None,
        "scheduled_pay_date": dates[2], "modeled_pay_date": dates[2]}
        for event in ("DIVIDEND_RECEIVABLE", "DIVIDEND_PAID")]
    config = {"sample": "validation", "cash_delay_sessions": 0}
    audit_records(tables, context, config, "2022-01-01")
    rejected = []
    for label in ("missing_session", "phantom_position", "wrong_split_rounding", "wrong_phase",
                  "missing_split", "sale_exceeds_units", "duplicate_dividend", "wrong_dividend_record_units"):
        bad = deepcopy(tables)
        if label == "missing_session": bad["nav"].pop(1)
        elif label == "phantom_position":
            bad["positions"][0]["quantity"] += 100
            bad["positions"][0]["sellable_quantity"] += 100
        elif label == "wrong_split_rounding": bad["share_events"][0]["new_quantity"] += 1
        elif label == "wrong_phase": bad["share_events"][0]["effective_phase"] = "BOD"
        elif label == "missing_split": bad["share_events"].clear()
        elif label == "sale_exceeds_units": bad["fills"][-1]["quantity"] += 1
        elif label == "duplicate_dividend": bad["cash_events"].append(deepcopy(bad["cash_events"][1]))
        elif label == "wrong_dividend_record_units":
            for row in bad["cash_events"]: row["amount"] = 1.0
        try:
            audit_records(bad, context, config, "2022-01-01")
        except ReviewFailure:
            rejected.append(label)
        else:
            raise ReviewFailure("Selfcheck failed to reject " + label)
    # BOD conversion must use prior holdings before today's new buy.
    bod = deepcopy(tables)
    bod_context = deepcopy(context)
    bod_context["actions"][0].update(effective_phase="BOD", record_date=dates[0])
    bod["share_events"][0].update(effective_phase="BOD", old_quantity=100, new_quantity=101,
                                   rounding_share_delta=.5)
    audit_records(bod, bod_context, config, "2022-01-01")
    # A delayed payment beyond the last admitted session stays unpaid.
    delayed = deepcopy(tables)
    delayed["cash_events"] = [dict(delayed["cash_events"][0], modeled_pay_date=None)]
    audit_records(delayed, context, dict(config, cash_delay_sessions=1), "2022-01-01")
    # Account FLOOR and a canceled plan must not be mistaken for a CEIL event.
    floor = deepcopy(tables)
    floor_context = deepcopy(context)
    floor_context["actions"][0].update(share_factor=1.003, rounding_policy="FLOOR")
    floor["share_events"][0].update(share_factor=1.003, rounding_policy="FLOOR",
                                     new_quantity=200, rounding_share_delta=-.6)
    floor["positions"][1].update(quantity=200, sellable_quantity=200)
    floor["fills"][-1]["quantity"] = 200
    for row in floor["cash_events"]:
        row["amount"] = 2.0
    audit_records(floor, floor_context, config, "2022-01-01")
    cancelled = deepcopy(floor)
    cancelled_context = deepcopy(floor_context)
    cancelled_context["actions"][0]["action_status"] = "CANCELLED"
    cancelled["share_events"][0]["status"] = "CANCELLED_NO_MUTATION"
    audit_records(cancelled, cancelled_context, config, "2022-01-01")
    return {"status": "PASS", "invented_positive_cases": 5, "invented_mutations_rejected": rejected,
            "actual_run_results_read": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--funded-start", choices=("2016-01-01", "2022-01-01"))
    args = parser.parse_args()
    if args.selfcheck:
        result = selfcheck()
    else:
        if not all((args.run_dir, args.dataset, args.funded_start)):
            parser.error("--run-dir, --dataset and --funded-start are required")
        result = audit_run(args.run_dir, args.dataset, args.funded_start)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
