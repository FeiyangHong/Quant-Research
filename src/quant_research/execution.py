"""Conservative daily research ledger, never a live execution adapter.

Orders retain decision-day quantities and references. Daily matching is an
explicit DAILY_SCREEN_ONLY assumption, not evidence of an executable queue.
"""
from collections import defaultdict
from bisect import bisect_left
from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from functools import lru_cache
import math

import pandas as pd

from .settlement import RULE_MODE, rule_errors
from .temporal import master_record, TemporalStateError
from .equity_accounting import CashDividendTaxLedger, EquityAccountingBlocked
from .engineering_replay import REPLAY_TAG, validate_replay, verify_daily_limits


class ExecutionBlockedError(ValueError):
    """Accounting or historical rules cannot safely represent this scenario."""


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


@lru_cache(maxsize=32768)
def _cutoff(day, clock="21:00:00"):
    return pd.Timestamp(str(day) + " " + clock, tz="Asia/Shanghai")


def _timestamp(value):
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ExecutionBlockedError("Timezone required for available_at")
    return result


def _valid(value, positive=False):
    try:
        return math.isfinite(float(value)) and (float(value) > 0 if positive else float(value) >= 0)
    except (ValueError, TypeError):
        return False


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _product_money(quantity, price):
    # Convert operands before arithmetic. Converting a binary product after
    # multiplication cannot recover a half-cent (e.g. 373 * 2.695).
    return _money(Decimal(str(quantity)) * Decimal(str(price)))


def _charges(notional, buy, statutory, cost_multiplier):
    value = Decimal(str(notional))
    commission = _money(max(Decimal("5"), value * Decimal("0.0003")) * Decimal(str(cost_multiplier)))
    stamp = _money(Decimal("0") if buy else value * Decimal(str(statutory[0])))
    transfer = _money(value * Decimal(str(statutory[1])))
    return commission, stamp, transfer


def _tick(value, tick, buy):
    units = (Decimal(str(value)) / Decimal(str(tick))).to_integral_value(
        rounding=ROUND_CEILING if buy else ROUND_FLOOR)
    return float(units * Decimal(str(tick)))


def _on_tick(value, tick):
    units = float(value) / float(tick)
    return abs(units - round(units)) < 1e-7


def _action_phase(action):
    value = action.get("effective_phase")
    phase = "BOD" if value is None or pd.isna(value) else value
    if phase not in ("BOD", "EOD"):
        raise ExecutionBlockedError("Unknown corporate action effective_phase")
    if phase == "EOD" and action["action_type"] != "SPLIT":
        raise ExecutionBlockedError("EOD processing currently supports share actions only")
    return phase


def _action_cutoff(action):
    return _cutoff(str(action["ex_date"])[:10], "15:00:00" if _action_phase(action) == "EOD" else "09:30:00")


def _account_split_lots(lots, factor, rounding):
    """Round once per account; conservatively allocate rounding to later locks."""
    ratio = Decimal(str(factor))
    exact = [Decimal(lot["quantity"]) * ratio for lot in lots]
    total = sum(exact, Decimal(0))
    if rounding == "EXACT":
        if total != total.to_integral_value():
            raise ExecutionBlockedError("Fractional split entitlements require verified rounding terms")
        target = int(total)
    elif rounding in ("FLOOR", "CEIL"):
        target = int(total.to_integral_value(rounding=ROUND_FLOOR if rounding == "FLOOR" else ROUND_CEILING))
    else:
        raise ExecutionBlockedError("Unknown account share rounding_policy")
    allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    extras = target - sum(allocated)
    eligible = sorted((i for i, value in enumerate(exact) if value != allocated[i]),
                      key=lambda i: (lots[i]["sellable_index"], lots[i]["acquired_on"], i), reverse=True)
    for i in eligible[:extras]:
        allocated[i] += 1
    if sum(allocated) != target:
        raise ExecutionBlockedError("Account share rounding allocation failure")
    converted = [dict(lot, quantity=qty) for lot, qty in zip(lots, allocated) if qty]
    return converted, target, float(Decimal(target) - total)


def run_backtest(dataset, decisions, initial_cash, cost_multiplier=1,
                 slippage_multiplier=1, max_sell_attempts=5, tax_rules=None,
                 start_date=None, cash_delay_sessions=0, engineering_replay=False):
    """Return auditable DataFrames for a cash-only daily backtest.

    ``decisions`` are dictionaries or TargetDecision objects with ISO
    decision_date/execution_date and weights/reference_prices/adv20 mappings.
    Each desired quantity is fixed at the decision; a gap can only reduce a
    fill. Actual sales precede new-buy risk checks. Buy remainders expire;
    sell remainders retry at most five actual daily orders including the first.

    Optional stock tax_rules must explicitly specify effective_from,
    effective_to, stamp_duty_sell, transfer_fee_both, verified=True and
    source_url. No stock statutory rates are guessed. ETF commission is a
    research scenario: 3bp, minimum CNY5 per actual order, multiplied only by
    cost_multiplier. Statutory charges are never multiplied.
    """
    if not _valid(initial_cash, True):
        raise ValueError("initial_cash must be positive and finite")
    if not _valid(cost_multiplier) or not _valid(slippage_multiplier):
        raise ValueError("Cost/slippage multipliers must be finite and nonnegative")
    if not isinstance(max_sell_attempts, int) or not 1 <= max_sell_attempts <= 5:
        raise ValueError("max_sell_attempts must be in 1..5")
    if type(cash_delay_sessions) is not int or cash_delay_sessions not in (0, 1, 3):
        raise ValueError("Cash settlement stress must be 0, 1 or 3 trading sessions")
    calendar = [str(d)[:10] for d in _get(dataset, "calendar")]
    dividend_tax = None
    if engineering_replay:
        try:
            validate_replay(dataset, calendar)
            dividend_tax = CashDividendTaxLedger("DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE")
        except EquityAccountingBlocked as exc:
            raise ExecutionBlockedError(str(exc)) from exc
    if calendar != sorted(set(calendar)):
        raise ExecutionBlockedError("Calendar must be sorted and unique")
    day_index = {day: i for i, day in enumerate(calendar)}
    start_date = str(start_date)[:10] if start_date is not None else (calendar[0] if calendar else "0001-01-01")
    if not calendar or not any(day >= start_date for day in calendar):
        raise ExecutionBlockedError("No account sessions on or after start_date")
    masters = _get(dataset, "instruments").copy()
    source_bars = _get(dataset, "bars")
    # Source provenance is audited and snapshotted by the data/runner layers.
    # Avoid copying unused document metadata into every daily lookup record.
    bar_fields = ("date", "instrument_id", "available_at", "open", "high", "low", "close",
                  "volume", "amount", "upper_limit", "lower_limit", "suspended",
                  "limit_terms_verified", "limit_source_url", "limit_rule_available_at",
                  "listing_session", "special_session", "limit_reference_price")
    bars = source_bars.loc[:, [key for key in bar_fields if key in source_bars]].copy()
    actions = _get(dataset, "actions", pd.DataFrame()).copy()
    rules = tax_rules if tax_rules is not None else _get(dataset, "tax_rules", pd.DataFrame())
    if not isinstance(rules, pd.DataFrame):
        rules = pd.DataFrame(rules)
    master_rows, bar_rows = defaultdict(list), defaultdict(list)
    for record in masters.to_dict("records"):
        record["_available"] = _timestamp(record["available_at"])
        master_rows[record["instrument_id"]].append(record)
    stock_ids = {sid for sid, records in master_rows.items() if any(row.get("asset_type") == "STOCK" for row in records)}
    if dividend_tax is not None and any(len({row.get("asset_type") for row in records}) != 1 for records in master_rows.values()):
        raise ExecutionBlockedError("Engineering replay requires stable asset-class identity")
    parsed_bar_times = {}
    for record in bars.to_dict("records"):
        record["date"] = str(record["date"])[:10]
        value = record["available_at"]
        if value not in parsed_bar_times:
            parsed_bar_times[value] = _timestamp(value)
        record["_available"] = parsed_bar_times[value]
        bar_rows[(record["instrument_id"], record["date"])].append(record)
    for rows in bar_rows.values():
        rows.sort(key=lambda row: row["_available"])
        if len({row["_available"] for row in rows}) != len(rows):
            raise ExecutionBlockedError("Ambiguous same-time source revisions")

    def master(sid, cutoff):
        try:
            return master_record(master_rows[sid], cutoff)
        except TemporalStateError as exc:
            raise ExecutionBlockedError(str(exc)) from exc

    def bar(sid, day, cutoff=None):
        rows = [r for r in bar_rows[(sid, day)] if r["_available"] <= (cutoff or _cutoff(day))]
        return rows[-1] if rows else None

    def historical_adv(sid, day):
        index = day_index[day]
        if index < 19:
            return None
        rows = [bar(sid, d, _cutoff(day)) for d in calendar[index - 19:index + 1]]
        if any(r is None or not _valid(r.get("amount")) for r in rows):
            return None
        return sum(float(r["amount"]) for r in rows) / 20

    def permission(meta, day, buying):
        if meta is None:
            return "UNKNOWN_INSTRUMENT_ASOF"
        if str(meta.get("listed_on", "9999"))[:10] > day:
            return "NOT_LISTED"
        delisted = meta.get("delisted_on")
        if pd.notna(delisted) and str(delisted)[:10] <= day:
            return "DELISTED_RETAIN_RIGHTS"
        asset = meta.get("asset_type")
        if buying and asset == "STOCK" and meta.get("board") not in ("MAIN", "CHINEXT"):
            return "BOARD_PERMISSION_DENIED"
        if buying and asset == "ETF" and meta.get("account_verified") is not True:
            return "ETF_PERMISSION_UNVERIFIED"
        if buying and asset == "STOCK" and meta.get("account_verified") is not True:
            return "ACCOUNT_PERMISSION_REVOKED" if meta.get("account_verified") is False else "STOCK_PERMISSION_UNVERIFIED"
        if buying and pd.notna(delisted):
            return "ANNOUNCED_DELISTING"
        if asset not in ("ETF", "STOCK"):
            return "UNSUPPORTED_ASSET_TYPE"
        if meta.get("lot_size") != 100 or meta.get("t_plus") not in (0, 1):
            return "UNSUPPORTED_TRADING_RULES"
        if asset == "STOCK" and meta.get("t_plus") != 1:
            return "UNSUPPORTED_STOCK_SETTLEMENT"
        if not _valid(meta.get("tick_size"), True):
            return "MISSING_TICK_RULE"
        status = meta.get("status") if asset == "STOCK" else meta.get("status", "NORMAL")
        if buying and asset == "STOCK":
            # Both historical fields must explicitly permit new stock risk.
            # Identity rejects 0/1, strings and missing values; truthiness or
            # equality would silently turn malformed flags into non-ST status.
            if (not isinstance(status, str) or status not in ("NORMAL", "ACTIVE")
                    or meta.get("is_st") is not False):
                return "INSTRUMENT_STATUS_DENIED"
        elif buying and (meta.get("is_st") is True or status not in ("NORMAL", "ACTIVE")):
            return "INSTRUMENT_STATUS_DENIED"
        return None

    def rates(meta, day):
        if meta["asset_type"] == "ETF":
            return 0., 0.
        matches = []
        for rule in rules.to_dict("records"):
            known = rule.get("available_at")
            if pd.notna(known) and _timestamp(known) > _cutoff(day, "09:30:00"):
                continue
            if (engineering_replay or _get(dataset, "manifest", {}).get("synthetic") is False) and pd.isna(known):
                raise ExecutionBlockedError("STOCK_TAX_RULE_AVAILABILITY_REQUIRED")
            if (str(rule.get("effective_from", "9999"))[:10] <= day <= str(rule.get("effective_to", "0000"))[:10]
                    and rule.get("verified") is True and rule.get("source_url")):
                matches.append(rule)
        if len(matches) != 1:
            raise ExecutionBlockedError("UNKNOWN_OR_AMBIGUOUS_STOCK_TAX_RULE")
        rule = matches[0]
        if (not _valid(rule.get("stamp_duty_sell")) or not _valid(rule.get("transfer_fee_both"))
                or float(rule["stamp_duty_sell"]) > 1 or float(rule["transfer_fee_both"]) > 1):
            raise ExecutionBlockedError("INVALID_STOCK_TAX_RULE")
        return float(rule["stamp_duty_sell"]), float(rule["transfer_fee_both"])

    def charges(notional, buy, statutory):
        return _charges(notional, buy, statutory, cost_multiplier)

    decision_by_day = {}
    for decision in decisions:
        d = asdict(decision) if is_dataclass(decision) else dict(decision)
        if "fixed_quantities" in d:
            if not engineering_replay:
                raise ExecutionBlockedError("Fixed quantities are engineering replay only")
            fixed = d["fixed_quantities"]
            if (not isinstance(fixed, dict)
                    or any(not isinstance(sid, str) or not sid.strip() for sid in fixed)
                    or any(type(qty) is not int or qty < 0 or qty % 100 for qty in fixed.values())):
                raise ExecutionBlockedError("Fixed engineering targets require a mapping of instrument IDs to nonnegative round lots")
            # Explicit shares are a complete engineering target. Weight keys
            # are not needed to discover which instruments must be processed.
            d.setdefault("weights", {})
        day, execution = str(d["decision_date"])[:10], str(d["execution_date"])[:10]
        if execution < start_date:
            continue
        if day not in day_index or execution not in day_index or day_index[execution] <= day_index[day]:
            raise ExecutionBlockedError("Execution must follow a valid decision session")
        if day in decision_by_day:
            raise ExecutionBlockedError("Duplicate decision session")
        if "decision_at" in d and _timestamp(d["decision_at"]) != _cutoff(day):
            raise ExecutionBlockedError("Only 21:00 decision cutoff is supported")
        weights = d["weights"]
        if any(not _valid(w) for w in weights.values()) or sum(weights.values()) > 1 + 1e-10:
            raise ExecutionBlockedError("Weights must be finite, long-only and unleveraged")
        decision_by_day[day] = d

    events = defaultdict(list)
    dividend_records = defaultdict(list)
    def register_dividend_record(action):
        if dividend_tax is None or action["action_type"] != "CASH_DIVIDEND":
            return
        sid = action["instrument_id"]
        if sid not in stock_ids:
            return
        record_day = str(action.get("record_date", ""))[:10]
        if record_day not in day_index or record_day >= str(action["ex_date"])[:10] or record_day < start_date:
            raise ExecutionBlockedError("Stock dividend requires account record-date capture")
        if _timestamp(action["available_at"]) > _cutoff(record_day):
            raise ExecutionBlockedError("Stock dividend terms not known at record close")
        if (action.get("cash_dividend_kind") not in ("ORDINARY", "SPECIAL")
                or action.get("tax_category") != "ORDINARY_CASH_DIVIDEND"):
            raise ExecutionBlockedError("Explicit cash dividend and tax classification required")
        if action.get("settlement_mode") != "SYNTHETIC_SCHEDULED_SIMULATION":
            raise ExecutionBlockedError("Synthetic dividend cash requires explicit modeled settlement")
        dividend_records[record_day].append(action)
    warmup_share_events = []
    if not actions.empty:
        resolved_actions = []
        for _, revisions in actions.groupby("action_id", sort=False):
            source_rows = revisions.to_dict("records")
            if all(r["action_type"] in ("SPLIT", "CASH_DIVIDEND") and str(r["ex_date"])[:10] < start_date for r in source_rows):
                first = source_rows[0]
                warmup_share_events.append({"date": str(first["ex_date"])[:10], "action_id": first["action_id"],
                    "instrument_id": first["instrument_id"], "status": "UNOWNED_PRE_ACCOUNT_EVENT",
                    "old_quantity": 0, "new_quantity": 0})
                continue
            known_versions = sorted(
                [r for r in revisions.to_dict("records") if _timestamp(r["available_at"]) <= _cutoff(calendar[-1])],
                key=lambda r: _timestamp(r["available_at"]))
            terms = ("instrument_id", "ex_date", "record_date", "pay_date", "cash_per_share", "share_factor", "recovery_per_share", "action_type",
                     "recognition_date", "entitlement_action_id", "installment_id", "is_final", "settlement_mode", "cash_settlement_verified",
                     "scheduled_pay_date", "settlement_rule_source_url", "settlement_rule_effective_from", "settlement_rule_effective_to",
                     "settlement_rule_available_at", "settlement_rule_verified", "settlement_rule_event_types", "settlement_account_type",
                     "settlement_rule_credit_basis", "participant_transfer_date", "modeled_cash_date",
                     "effective_phase", "rounding_policy", "action_status")
            for previous, revised in zip(known_versions, known_versions[1:]):
                if (_timestamp(revised["available_at"]) > _action_cutoff(previous)
                        and any(str(previous.get(k)) != str(revised.get(k)) for k in terms)):
                    raise ExecutionBlockedError("Post-effective corporate-action revision requires an adjustment ledger")
            candidates = []
            late_share_candidates = []
            for action in revisions.to_dict("records"):
                effective = str(action["ex_date"])[:10]
                if effective < calendar[0] or effective > calendar[-1]:
                    continue
                available = _timestamp(action["available_at"])
                if available <= _action_cutoff(action):
                    candidates.append((available, action))
                elif action["action_type"] == "SPLIT":
                    late_share_candidates.append((available, action))
            if not candidates and late_share_candidates:
                candidates = [min(late_share_candidates, key=lambda pair: pair[0])]
            if not candidates:
                if any(calendar[0] <= str(d)[:10] <= calendar[-1] for d in revisions["ex_date"]):
                    raise ExecutionBlockedError("Corporate action not known by its effective open")
                if dividend_tax is not None and known_versions:
                    last = known_versions[-1]
                    record_day = str(last.get("record_date", ""))[:10]
                    if (last["action_type"] == "CASH_DIVIDEND" and str(last["ex_date"])[:10] > calendar[-1]
                            and record_day in day_index and record_day >= start_date):
                        register_dividend_record(last)
                continue
            if len({time for time, _ in candidates}) != len(candidates):
                raise ExecutionBlockedError("Ambiguous same-time corporate-action revisions")
            resolved_actions.append(max(candidates, key=lambda pair: pair[0])[1])
        for action in resolved_actions:
            effective = str(action["ex_date"])[:10]
            if effective not in day_index:
                if calendar and effective < calendar[0]:
                    continue
                if calendar and effective > calendar[-1]:
                    continue
                raise ExecutionBlockedError("Corporate action is outside trading calendar")
            if _timestamp(action["available_at"]) > _action_cutoff(action) and action["action_type"] != "SPLIT":
                raise ExecutionBlockedError("Corporate action not known by its effective open")
            if action["action_type"] not in ("CASH_DIVIDEND", "SPLIT", "DELISTING", "LIQUIDATION", "LIQUIDATION_PAYMENT"):
                raise ExecutionBlockedError("Unsupported corporate action")
            events[effective].append(action)
            register_dividend_record(action)
    action_rank = {"SPLIT": 0, "CASH_DIVIDEND": 1, "LIQUIDATION": 2, "LIQUIDATION_PAYMENT": 3, "DELISTING": 4}
    for day_events in events.values():
        day_events.sort(key=lambda action: (action_rank[action["action_type"]], str(action["action_id"])))

    cash, withdrawable = float(initial_cash), float(initial_cash)
    lots, marks, stale, receivables = defaultdict(list), {}, defaultdict(int), []
    dead, queues = set(), defaultdict(list)
    risk_exit_started = set()
    record_holdings = {}
    unresolved_shares = {}
    liquidation_rights, retired_instruments, paid_installments = {}, {}, set()
    observation_replay = False
    assumed_settlement = False
    rule_based_settlement = False
    output = {key: [] for key in ("nav", "positions", "orders", "fills", "rejected_orders", "costs", "exposure", "cash_events", "order_events", "rights", "share_events", "tax_balances", "tax_lots", "dividend_entitlements", "tax_events")}
    output["share_events"].extend(warmup_share_events)
    sequence = 0

    def quantity(sid):
        return sum(lot["quantity"] for lot in lots[sid])

    def rule_payment_date(action):
        failures = rule_errors(action)
        if failures:
            raise ExecutionBlockedError("; ".join(failures))
        modeled = action["pay_date"]
        if action.get("settlement_rule_credit_basis") == "NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER":
            modeled = action["modeled_cash_date"]
            transfer_index = bisect_left(calendar, action["participant_transfer_date"])
            if transfer_index < len(calendar):
                if calendar[transfer_index] != action["participant_transfer_date"]:
                    raise ExecutionBlockedError("Participant transfer must be a verified trading session")
                if transfer_index + 1 < len(calendar) and modeled != calendar[transfer_index + 1]:
                    raise ExecutionBlockedError("Modeled investor credit must follow participant transfer by one session")
        index = bisect_left(calendar, modeled) + cash_delay_sessions
        # No guessed 2025 trading calendar: keep an unpaid receivable if the
        # registered delay needs a session outside the supplied sample.
        return calendar[index] if index < len(calendar) else None

    def equity():
        return cash + sum(quantity(sid) * marks.get(sid, 0.) for sid in lots) + sum(r["amount"] for r in receivables) - (float(dividend_tax.tax_payable) if dividend_tax else 0.)

    def tax_reserve(day):
        return float(dividend_tax.reserve(day)) if dividend_tax else 0.

    def reject(order, day, reason, qty=None):
        output["rejected_orders"].append({"order_id": order["order_id"], "date": day,
            "instrument_id": order["instrument_id"], "side": order["side"],
            "quantity": order["quantity"] if qty is None else qty, "reason": reason})

    def create_order(day, execution, sid, side, qty, reference, adv, attempt=1, parent=None,
                     intent_type="REBALANCE", risk_reason=None, source_reference_price=None,
                     reference_basis="RAW_CLOSE"):
        nonlocal sequence
        sequence += 1
        order = {"order_id": f"O{sequence:08d}", "parent_order_id": parent,
            "decision_date": day, "decision_at": str(_cutoff(day)), "execution_date": execution,
            "instrument_id": sid, "side": side, "quantity": int(qty),
            "qty_requested": int(qty), "reference_price": reference, "adv20": adv,
            "attempt": attempt, "mode": "DAILY_SCREEN_ONLY",
            "intent_type": intent_type, "risk_reason": risk_reason,
            "source_reference_price": reference if source_reference_price is None else source_reference_price,
            "reference_basis": reference_basis}
        output["orders"].append(order.copy())
        return order

    def retry(order, day, remainder):
        if order["side"] != "SELL" or remainder <= 0:
            return
        if order["attempt"] >= max_sell_attempts:
            reject(order, day, "SELL_RETRY_EXHAUSTED_RETAIN_HOLDINGS", remainder)
        elif day_index[day] + 1 < len(calendar):
            sid = order["instrument_id"]
            new = create_order(day, calendar[day_index[day] + 1], sid, "SELL", remainder,
                marks.get(sid, order["reference_price"]), historical_adv(sid, day),
                order["attempt"] + 1, order["order_id"], order["intent_type"], order["risk_reason"],
                source_reference_price=(marks.get(sid, order["reference_price"]) * eod_factors.get(sid, 1.)),
                reference_basis="POST_EOD_ADJUSTED" if sid in eod_factors else "RAW_CLOSE")
            queues[new["execution_date"]].append(new)
        else:
            reject(order, day, "END_OF_DATA_UNFILLED_RETAIN_HOLDINGS", remainder)

    def new_right(action, entitled, retired):
        return {"entitlement_action_id": action["action_id"], "instrument_id": action["instrument_id"],
                "record_date": str(action.get("record_date", ""))[:10], "retirement_date": str(action["ex_date"])[:10],
                "entitled_quantity": entitled, "retired_quantity": retired, "recognized_amount": 0.,
                "paid_amount": 0., "final_recognized": False, "late_recognition": False, "assumed_settlement": False}

    def apply_share_action(action, day):
        sid, phase = action["instrument_id"], _action_phase(action)
        if action.get("action_usage_scope") == "PRE_LISTING_METADATA_ONLY":
            listings = {str(row["listed_on"])[:10] for row in master_rows[sid] if pd.notna(row.get("listed_on"))}
            if len(listings) != 1 or day >= next(iter(listings)) or quantity(sid):
                raise ExecutionBlockedError("Pre-listing share metadata requires a verified later listing and no account holdings")
            output["share_events"].append({"date": day, "action_id": action["action_id"], "instrument_id": sid,
                "effective_phase": phase, "status": "PRE_LISTING_METADATA_ONLY", "old_quantity": 0, "new_quantity": 0})
            return
        meta = master(sid, _action_cutoff(action))
        if meta is None:
            raise ExecutionBlockedError("Share event lacks known instrument")
        status = action.get("action_status")
        status = "CONFIRMED" if status is None or pd.isna(status) else status
        available = _timestamp(action["available_at"])
        old_qty = quantity(sid)
        if available > _action_cutoff(action):
            if old_qty:
                raise ExecutionBlockedError("UNKNOWN_SPLIT_TERMS_AT_EFFECTIVE_TIME: held share rights cannot be valued with a later ratio")
            unresolved_shares[sid] = available
            output["share_events"].append({"date": day, "action_id": action["action_id"], "instrument_id": sid,
                "effective_phase": phase, "status": "UNOWNED_TERMS_PENDING", "old_quantity": 0, "new_quantity": 0})
            return
        if status == "CANCELLED":
            if action.get("terms_verified") is not True or not isinstance(action.get("source_url"), str) or not action["source_url"]:
                raise ExecutionBlockedError("Canceled split requires verified cancellation evidence")
            output["share_events"].append({"date": day, "action_id": action["action_id"], "instrument_id": sid,
                "effective_phase": phase, "status": "CANCELLED_NO_MUTATION", "old_quantity": old_qty, "new_quantity": old_qty})
            return
        if status != "CONFIRMED":
            raise ExecutionBlockedError("Unconfirmed share plan cannot mutate economic holdings")
        if meta["asset_type"] == "STOCK":
            # An integral factor does not establish whether this is a taxable
            # bonus issue, capital-reserve conversion, or a share exchange.
            # The ETF allocation routine cannot preserve those tax rights.
            raise ExecutionBlockedError("Stock share-action tax classification and entitlement accounting unsupported")
        factor = action.get("share_factor")
        if not _valid(factor, True):
            raise ExecutionBlockedError("Invalid split factor")
        rounding = action.get("rounding_policy")
        rounding = "EXACT" if rounding is None or pd.isna(rounding) else rounding
        if rounding != "EXACT" and meta["asset_type"] != "ETF":
            raise ExecutionBlockedError("Stock fractional share event taxation unsupported")
        if rounding != "EXACT":
            expected_record = day if phase == "EOD" else (calendar[day_index[day] - 1] if day_index[day] else None)
            if str(action.get("record_date", ""))[:10] != expected_record:
                raise ExecutionBlockedError("Share record_date must match the prior BOD or same-day EOD ownership boundary")
        if rounding != "EXACT" and (action.get("terms_verified") is not True or
                not isinstance(action.get("source_url"), str) or not action["source_url"]):
            raise ExecutionBlockedError("Account share rounding requires verified issuer terms")
        converted, new_qty, fraction = _account_split_lots(lots[sid], factor, rounding)
        old_mark = marks.get(sid, 0.)
        lots[sid] = converted
        marks[sid] = old_mark / float(factor)
        split_factors[sid] *= float(factor)
        split_totals[sid] = (old_qty, new_qty)
        effective_sids.add(sid)
        if phase == "EOD":
            eod_factors[sid] *= float(factor)
        output["share_events"].append({"date": day, "action_id": action["action_id"], "instrument_id": sid,
            "effective_phase": phase, "status": "APPLIED", "old_quantity": old_qty, "new_quantity": new_qty,
            "share_factor": float(factor), "rounding_policy": rounding, "rounding_share_delta": fraction,
            "reference_price_before": old_mark, "reference_price_after": marks[sid],
            "rounding_value_delta": new_qty * marks[sid] - old_qty * old_mark})
        for pending_day, pending_orders in queues.items():
            retained = []
            for pending_order in pending_orders:
                if pending_order["instrument_id"] != sid:
                    retained.append(pending_order)
                    continue
                reject(pending_order, day, "SHARE_ACTION_ORDER_CANCELLED")
                if pending_order["side"] == "SELL":
                    replacement_qty = new_qty if pending_order["quantity"] >= old_qty else min(new_qty, int(pending_order["quantity"] * float(factor)))
                    share_retry_requests.append((pending_order, replacement_qty))
            queues[pending_day] = retained

    # A fresh validation account owns no earlier entitlements, but an already
    # retired product must not become buyable merely because the ledger starts
    # after its economic retirement and before its exchange delisting.
    for effective, day_events in events.items():
        if effective < start_date:
            for action in day_events:
                if action["action_type"] == "LIQUIDATION":
                    liquidation_rights[action["action_id"]] = new_right(action, 0, 0)
                    retired_instruments[action["instrument_id"]] = action["action_id"]
                    dead.add(action["instrument_id"])

    for day in calendar:
        # Keep pre-period source rows for ADV and the final pre-period decision,
        # but start with fresh cash and no pre-period trades or entitlements.
        if day < start_date and day not in decision_by_day:
            continue
        index, withdrawable = day_index[day], cash
        effective_sids = set()
        split_factors = defaultdict(lambda: 1.)
        eod_factors = defaultdict(lambda: 1.)
        split_totals, share_retry_requests = {}, []
        # These events occur before trading and before ex-date purchases.
        for action in (events[day] if day >= start_date else []):
            sid = action["instrument_id"]
            if action["action_type"] == "SPLIT":
                if _action_phase(action) == "BOD":
                    apply_share_action(action, day)
                continue
            effective_sids.add(sid)
            meta = master(sid, _cutoff(day, "09:30:00"))
            if meta is None:
                raise ExecutionBlockedError("Corporate action lacks known instrument")
            qty, kind = quantity(sid), action["action_type"]
            if kind == "CASH_DIVIDEND":
                if meta["asset_type"] != "ETF" and dividend_tax is None:
                    raise ExecutionBlockedError("Stock dividend holding-period taxation unsupported")
                record_day = str(action.get("record_date", ""))[:10]
                if record_day not in day_index or record_day >= day:
                    raise ExecutionBlockedError("Dividend requires a valid prior record_date")
                per_share, pay_day = action.get("cash_per_share"), str(action.get("pay_date"))[:10]
                if not _valid(per_share) or pay_day < day or pay_day == "None":
                    raise ExecutionBlockedError("Invalid dividend terms")
                entitlement = record_holdings.get((record_day, sid), 0)
                amount = _product_money(entitlement, per_share)
                modeled = action.get("settlement_mode") == RULE_MODE
                synthetic_modeled = meta["asset_type"] == "STOCK" and dividend_tax is not None
                ledger_pay_day = rule_payment_date(action) if modeled else pay_day
                rule_based_settlement = rule_based_settlement or (modeled and entitlement > 0)
                if amount:
                    receivables.append({"action_id": action["action_id"], "instrument_id": sid,
                        "amount": amount, "pay_date": ledger_pay_day, "settlement_mode": "SYNTHETIC_SCHEDULED_SIMULATION" if synthetic_modeled else RULE_MODE if modeled else "SCHEDULED",
                        "actual_pay_date": None if modeled or synthetic_modeled else pay_day,
                        "scheduled_pay_date": pay_day, "modeled_pay_date": ledger_pay_day if modeled or synthetic_modeled else None})
                    output["cash_events"].append({"date": day, "event": "DIVIDEND_RECEIVABLE", "instrument_id": sid, "amount": amount,
                        "settlement_mode": "SYNTHETIC_SCHEDULED_SIMULATION" if synthetic_modeled else RULE_MODE if modeled else "SCHEDULED", "actual_pay_date": None if modeled or synthetic_modeled else pay_day,
                        "scheduled_pay_date": pay_day, "modeled_pay_date": ledger_pay_day if modeled or synthetic_modeled else None})
                if sid in marks:
                    marks[sid] = max(0., marks[sid] - float(per_share))
            elif kind == "LIQUIDATION":
                if meta["asset_type"] != "ETF":
                    raise ExecutionBlockedError("Stock liquidation taxation unsupported")
                if (action.get("terms_verified") is not True or not isinstance(action.get("source_url"), str)
                        or not action["source_url"].strip()):
                    raise ExecutionBlockedError("Liquidation requires verified source terms")
                if any(_valid(action.get(field), True) for field in ("cash_per_share", "recovery_per_share")):
                    raise ExecutionBlockedError("Liquidation amounts require a separate linked payment event")
                record_day = str(action.get("record_date", ""))[:10]
                if record_day not in day_index or record_day >= day:
                    raise ExecutionBlockedError("Liquidation requires a valid prior record_date")
                if sid in retired_instruments or action["action_id"] in liquidation_rights:
                    raise ExecutionBlockedError("Duplicate economic liquidation")
                right = new_right(action, record_holdings.get((record_day, sid), 0), qty)
                liquidation_rights[action["action_id"]] = right
                retired_instruments[sid] = action["action_id"]
                lots[sid] = []
                dead.add(sid)
                marks[sid] = 0.
                for pending_day, pending_orders in queues.items():
                    retained = []
                    for pending_order in pending_orders:
                        if pending_order["instrument_id"] == sid:
                            reject(pending_order, day, "ECONOMIC_LIQUIDATION_ORDER_CANCELLED")
                        else:
                            retained.append(pending_order)
                    queues[pending_day] = retained
                output["cash_events"].append({"date": day, "event": "LIQUIDATION_RIGHT_RECOGNIZED",
                    "action_id": action["action_id"], "instrument_id": sid, "amount": 0.,
                    "entitled_quantity": right["entitled_quantity"], "valuation_status": "UNPRICED_RIGHT"})
            elif kind == "LIQUIDATION_PAYMENT":
                if (action.get("terms_verified") is not True or not isinstance(action.get("source_url"), str)
                        or not action["source_url"].strip()):
                    raise ExecutionBlockedError("Liquidation payment requires verified source terms")
                entitlement_id = action.get("entitlement_action_id")
                right = liquidation_rights.get(entitlement_id)
                if right is None or right["instrument_id"] != sid:
                    raise ExecutionBlockedError("Liquidation payment lacks matching prior entitlement")
                installment = action.get("installment_id")
                if not isinstance(installment, str) or not installment:
                    raise ExecutionBlockedError("Liquidation payment needs stable installment_id")
                if (entitlement_id, installment) in paid_installments or right["final_recognized"]:
                    raise ExecutionBlockedError("Duplicate installment or payment after final liquidation")
                if str(action.get("recognition_date", ""))[:10] != day:
                    raise ExecutionBlockedError("Liquidation recognition_date must equal effective ex_date")
                per_share, pay_day = action.get("cash_per_share"), str(action.get("pay_date", ""))[:10]
                if not _valid(per_share) or len(pay_day) != 10:
                    raise ExecutionBlockedError("Invalid liquidation payment amount or date")
                try:
                    pd.Timestamp(pay_day)
                except (ValueError, TypeError):
                    raise ExecutionBlockedError("Invalid liquidation pay_date")
                if type(action.get("is_final")) is not bool:
                    raise ExecutionBlockedError("Liquidation is_final must be explicit boolean")
                mode = action.get("settlement_mode")
                if mode not in ("SCHEDULED", "LATE_RECOGNITION", "ASSUMED_SCHEDULED_CREDIT", RULE_MODE):
                    raise ExecutionBlockedError("Unknown liquidation settlement mode")
                assumed = mode == "ASSUMED_SCHEDULED_CREDIT"
                modeled = mode == RULE_MODE
                ledger_pay_day = rule_payment_date(action) if modeled else max(day, pay_day)
                if not assumed and not modeled and action.get("cash_settlement_verified") is not True:
                    raise ExecutionBlockedError("Liquidation cash date requires verified account settlement")
                late = pay_day < day
                if late and mode != "LATE_RECOGNITION":
                    raise ExecutionBlockedError("Past liquidation payment requires explicit late recognition")
                if mode == "LATE_RECOGNITION" and not late:
                    raise ExecutionBlockedError("Late recognition requires an earlier actual pay_date")
                amount = _product_money(right["entitled_quantity"], per_share)
                right["recognized_amount"] = _money(right["recognized_amount"] + amount)
                right["final_recognized"] = action["is_final"]
                right["late_recognition"] = right["late_recognition"] or late
                right["assumed_settlement"] = right["assumed_settlement"] or assumed
                observation_replay = observation_replay or (late and right["entitled_quantity"] > 0)
                assumed_settlement = assumed_settlement or (assumed and right["entitled_quantity"] > 0)
                rule_based_settlement = rule_based_settlement or (modeled and right["entitled_quantity"] > 0)
                paid_installments.add((entitlement_id, installment))
                output["cash_events"].append({"date": day, "event": "LIQUIDATION_RECEIVABLE",
                    "action_id": action["action_id"], "entitlement_action_id": entitlement_id,
                    "installment_id": installment, "instrument_id": sid, "amount": amount,
                    "actual_pay_date": None if assumed or modeled else pay_day,
                    "scheduled_pay_date": pay_day if assumed or modeled else None,
                    "modeled_pay_date": ledger_pay_day if modeled else None, "settlement_mode": mode})
                receivables.append({"action_id": action["action_id"], "instrument_id": sid,
                    "entitlement_action_id": entitlement_id, "installment_id": installment,
                    "amount": amount, "pay_date": ledger_pay_day, "actual_pay_date": None if assumed or modeled else pay_day,
                    "scheduled_pay_date": pay_day if assumed or modeled else None,
                    "modeled_pay_date": ledger_pay_day if modeled else None,
                    "event_type": "LIQUIDATION", "settlement_mode": mode})
            else:
                recovery = action.get("recovery_per_share")
                if pd.notna(recovery) and float(recovery) != 0:
                    raise ExecutionBlockedError("Positive delisting recoveries require a verified payment model")
                dead.add(sid)
                marks[sid] = 0.
            output["order_events"].append({"date": day, "event": kind, "instrument_id": sid, "quantity": qty})
        for receivable in list(receivables):
            if receivable["pay_date"] is not None and receivable["pay_date"] <= day:
                cash += receivable["amount"]
                withdrawable += receivable["amount"]
                if receivable.get("event_type") == "LIQUIDATION":
                    right = liquidation_rights[receivable["entitlement_action_id"]]
                    right["paid_amount"] = _money(right["paid_amount"] + receivable["amount"])
                    output["cash_events"].append({"date": day, "event": "LIQUIDATION_PAID",
                        "action_id": receivable["action_id"], "entitlement_action_id": receivable["entitlement_action_id"],
                        "installment_id": receivable["installment_id"], "instrument_id": receivable["instrument_id"],
                        "amount": receivable["amount"], "actual_pay_date": receivable["actual_pay_date"],
                        "scheduled_pay_date": receivable["scheduled_pay_date"],
                        "modeled_pay_date": receivable.get("modeled_pay_date"),
                        "settlement_mode": receivable["settlement_mode"]})
                else:
                    output["cash_events"].append({"date": day, "event": "DIVIDEND_PAID", "instrument_id": receivable["instrument_id"], "amount": receivable["amount"],
                        "actual_pay_date": receivable.get("actual_pay_date"), "scheduled_pay_date": receivable.get("scheduled_pay_date"),
                        "modeled_pay_date": receivable.get("modeled_pay_date"), "settlement_mode": receivable.get("settlement_mode")})
                receivables.remove(receivable)
        # Open marks only affect matching/risk checks, never desired quantities.
        for sid in list(lots):
            meta, row = master(sid, _cutoff(day, "09:30:00")), bar(sid, day)
            if meta is not None and pd.notna(meta.get("delisted_on")) and str(meta["delisted_on"])[:10] <= day:
                dead.add(sid)
            if sid in dead:
                marks[sid] = 0.
            elif row is not None and row.get("suspended") is False and _valid(row.get("volume"), True) and _valid(row.get("open"), True):
                marks[sid] = float(row["open"])
        delayed_retries = []
        daily = sorted(queues.pop(day, []), key=lambda o: (o["side"] != "SELL", o["order_id"]))
        capacity_used = defaultdict(float)
        for order in daily:
            sid, buy = order["instrument_id"], order["side"] == "BUY"
            meta, row = master(sid, _cutoff(day, "09:30:00")), bar(sid, day)
            qty, reason = order["quantity"], permission(meta, day, buy)
            if sid in unresolved_shares and unresolved_shares[sid] > _cutoff(day, "09:30:00"):
                reason = "SHARE_TERMS_NOT_YET_KNOWN"
            statutory = (0., 0.)
            if sid in dead:
                reason = "DELISTED_RETAIN_RIGHTS"
            if sid in effective_sids:
                reason = "CORPORATE_ACTION_ORDER_CANCELLED"
            if reason is None:
                try:
                    statutory = rates(meta, day)
                    if dividend_tax is not None and meta["asset_type"] == "STOCK":
                        verify_daily_limits(meta, row, day)
                except (ExecutionBlockedError, EquityAccountingBlocked) as exc:
                    reason = str(exc)
            if reason is None and (row is None or not all(_valid(row.get(k), True) for k in ("open", "high", "low", "upper_limit", "lower_limit"))):
                reason = "MISSING_PRICE_OR_LIMIT_RULE"
            if reason is None and (row.get("suspended") is not False):
                reason = "SUSPENDED_OR_UNKNOWN_STATUS"
            if reason is None and (not _valid(row.get("volume"), True) or not _valid(row.get("amount"), True)):
                reason = "NO_MARKET_TRADING"
            if reason is None:
                tick = float(meta["tick_size"])
                if (row["lower_limit"] > row["upper_limit"] or not row["low"] <= row["open"] <= row["high"]
                    or any(not _on_tick(row[k], tick) for k in ("open", "upper_limit", "lower_limit"))):
                    reason = "INVALID_PRICE_GRID"
                elif (buy and row["open"] >= row["upper_limit"] - 1e-10) or (not buy and row["open"] <= row["lower_limit"] + 1e-10):
                    reason = "OPEN_AT_ADVERSE_LIMIT"
            if reason is None and (not _valid(order["adv20"], True) or not _valid(order["reference_price"], True)):
                reason = "MISSING_HISTORICAL_ADV_OR_REFERENCE"
            if reason is not None:
                reject(order, day, reason)
                delayed_retries.append((order, qty))
                continue
            slip = Decimal("0.0003" if meta["asset_type"] == "ETF" else "0.001") * Decimal(str(slippage_multiplier))
            price = _tick(Decimal(str(row["open"])) * (1 + slip if buy else 1 - slip), tick, buy)
            if price <= 0 or price < row["lower_limit"] - 1e-10 or price > row["upper_limit"] + 1e-10 or price < row["low"] - 1e-10 or price > row["high"] + 1e-10:
                reject(order, day, "SLIPPAGE_PRICE_OUTSIDE_VALID_RANGE")
                delayed_retries.append((order, qty))
                continue
            cap_left = max(0., .01 * float(order["adv20"]) - capacity_used[sid])
            capacity_qty = int(cap_left / max(price, float(order["reference_price"])))
            fill_qty = min(qty, capacity_qty)
            limit_reason = "HISTORICAL_ADV_CAPACITY"
            reserved = 0.
            if buy:
                reserve_price = _tick(Decimal(str(order["reference_price"])) * (1 + slip), tick, True)
                risk_price = max(reserve_price, price)
                current_equity = equity()
                instrument_value = quantity(sid) * marks.get(sid, float(row["open"]))
                cap = .35 if meta["asset_type"] == "ETF" else .05
                # Include the incremental commission in post-fill equity caps.
                risk_budget = max(0., (cap * current_equity - instrument_value - cap * 5 * cost_multiplier) / (1 + cap * .0003 * cost_multiplier))
                gross = sum(quantity(s) * marks.get(s, 0.) for s in lots)
                risk_budget = min(risk_budget, max(0., current_equity - gross))
                if meta["asset_type"] == "STOCK":
                    industry = meta.get("industry")
                    if pd.isna(industry) or not industry:
                        risk_budget = 0.
                        limit_reason = "MISSING_INDUSTRY"
                    else:
                        industry_value = sum(quantity(s) * marks.get(s, 0.) for s in lots
                            if (master(s, _cutoff(day, "09:30:00")) or {}).get("asset_type") == "STOCK"
                            and (master(s, _cutoff(day, "09:30:00")) or {}).get("industry") == industry)
                        risk_budget = min(risk_budget, max(0., .20 * current_equity - industry_value - 5 * cost_multiplier))
                risk_qty = max(0, int(risk_budget / risk_price))
                if risk_qty < fill_qty:
                    limit_reason = "JOINT_EXPOSURE_LIMIT"
                    fill_qty = risk_qty
                # Reservation is based on the immutable known reference. A gap
                # is allowed to consume only this reservation, never extra cash.
                spendable = max(0., cash - tax_reserve(day))
                reserve_qty = min(fill_qty, int(spendable / reserve_price)) // 100 * 100
                while reserve_qty > 0:
                    reserve_notional = _product_money(reserve_qty, reserve_price)
                    reserve_fees = sum(charges(reserve_notional, True, statutory))
                    reserved = reserve_notional + reserve_fees
                    if reserved <= spendable + 1e-9:
                        break
                    reserve_qty -= 100
                if reserve_qty <= 0:
                    reserved = 0.
                fill_qty = reserve_qty
                output["order_events"].append({"date": day, "order_id": order["order_id"],
                    "event": "RESERVE", "cash_reserved": reserved, "cash_total": cash,
                    "cash_available": cash - reserved, "nav": current_equity})
                while fill_qty > 0 and _product_money(fill_qty, price) + sum(charges(_product_money(fill_qty, price), True, statutory)) > reserved + 1e-9:
                    fill_qty -= 100
                    limit_reason = "REFERENCE_RESERVATION_GAP"
                if reserve_qty == 0:
                    limit_reason = "INSUFFICIENT_CASH_OR_RISK_BUDGET"
            else:
                sellable = sum(lot["quantity"] for lot in lots[sid] if lot["sellable_index"] <= index)
                if sellable < fill_qty:
                    limit_reason = "T_PLUS_LOCKED"
                    fill_qty = sellable
                fill_qty = min(fill_qty, quantity(sid))
                # Odd lots are disposed only as the entire available remainder.
                if fill_qty != quantity(sid):
                    fill_qty = fill_qty // 100 * 100
            if buy:
                # Exact final check includes rounded statutory fees and the
                # adverse execution price, while holdings remain marked at
                # the market open. It can only reduce the fixed intention.
                while fill_qty > 0:
                    prospective_fees = sum(charges(_product_money(fill_qty, price), True, statutory))
                    post_nav = current_equity - prospective_fees - fill_qty * (price - float(row["open"]))
                    post_value = instrument_value + fill_qty * float(row["open"])
                    industry_ok = (meta["asset_type"] != "STOCK" or
                        industry_value + fill_qty * float(row["open"]) <= .20 * post_nav + 1e-8)
                    if post_value <= cap * post_nav + 1e-8 and industry_ok and gross + fill_qty * float(row["open"]) <= post_nav + 1e-8:
                        break
                    fill_qty -= 100
                    limit_reason = "JOINT_EXPOSURE_LIMIT_AFTER_COSTS"
            if fill_qty > 0:
                notional = _product_money(fill_qty, price)
                commission, stamp, transfer = charges(notional, buy, statutory)
                total_fees = commission + stamp + transfer
                if dividend_tax is not None and meta["asset_type"] == "STOCK":
                    if buy:
                        dividend_tax.buy(sid, fill_qty, day)
                    else:
                        dividend_tax.sell(sid, fill_qty, day)
                if buy:
                    debit = notional + total_fees
                    cash -= debit
                    withdrawable = max(0., withdrawable - debit)
                    lots[sid].append({"quantity": fill_qty, "acquired_on": day,
                        "sellable_index": index + int(meta["t_plus"])})
                    marks[sid] = float(row["open"])
                else:
                    cash += notional - total_fees
                    remaining = fill_qty
                    for lot in lots[sid]:
                        if lot["sellable_index"] <= index:
                            removed = min(remaining, lot["quantity"])
                            lot["quantity"] -= removed
                            remaining -= removed
                    lots[sid] = [lot for lot in lots[sid] if lot["quantity"]]
                capacity_used[sid] += fill_qty * max(price, float(order["reference_price"]))
                slippage_cost = _product_money(fill_qty, abs(Decimal(str(price)) - Decimal(str(row["open"]))))
                output["fills"].append({"date": day, "order_id": order["order_id"], "instrument_id": sid,
                    "side": order["side"], "quantity": fill_qty, "price": price, "notional": notional,
                    "commission": commission, "stamp_duty": stamp, "transfer_fee": transfer,
                    "fees": total_fees, "slippage_cost": slippage_cost, "mode": "DAILY_SCREEN_ONLY"})
                output["costs"].append({"date": day, "order_id": order["order_id"], "instrument_id": sid,
                    "commission": commission, "stamp_duty": stamp, "transfer_fee": transfer,
                    "total_cost": total_fees, "slippage_cost": slippage_cost})
                output["cash_events"].append({"date": day, "event": "BUY" if buy else "SELL",
                    "order_id": order["order_id"], "amount": -notional - total_fees if buy else notional - total_fees})
            if buy:
                output["order_events"].append({"date": day, "order_id": order["order_id"], "event": "RELEASE_RESERVATION", "cash_reserved": 0., "cash_total": cash, "cash_available": cash})
            if fill_qty < qty:
                reject(order, day, limit_reason, qty - fill_qty)
                delayed_retries.append((order, qty - fill_qty))
        # Close valuation uses raw price. Total-return indices are never money.
        for sid in list(lots):
            row = bar(sid, day)
            if sid in dead:
                marks[sid], stale[sid] = 0., 0
            elif row is not None and row.get("suspended") is False and _valid(row.get("volume"), True) and _valid(row.get("close"), True):
                marks[sid], stale[sid] = float(row["close"]), 0
            else:
                stale[sid] += 1
        for action in (events[day] if day >= start_date else []):
            if action["action_type"] == "SPLIT" and _action_phase(action) == "EOD":
                apply_share_action(action, day)
        for order, replacement_qty in share_retry_requests:
            if replacement_qty <= 0:
                continue
            if index + 1 >= len(calendar):
                reject(order, day, "END_OF_DATA_UNFILLED_RETAIN_HOLDINGS", replacement_qty)
                continue
            sid = order["instrument_id"]
            raw = bar(sid, day)
            replacement = create_order(day, calendar[index + 1], sid, "SELL", replacement_qty,
                marks.get(sid), historical_adv(sid, day), order["attempt"], order["order_id"],
                order["intent_type"], order["risk_reason"],
                source_reference_price=raw["close"] if raw else marks.get(sid),
                reference_basis="POST_EOD_ADJUSTED" if sid in eod_factors else "RAW_CLOSE")
            queues[replacement["execution_date"]].append(replacement)
        for order, remainder in delayed_retries:
            # Corporate action transformed quantities. Retry the actual holding.
            if order["instrument_id"] in effective_sids:
                sid = order["instrument_id"]
                old, new = split_totals.get(sid, (0, 0))
                remainder = new if old and remainder >= old else min(int(remainder * split_factors[sid]), quantity(sid))
            retry(order, day, remainder)
        if dividend_tax is not None:
            for settlement in _get(dataset, "tax_settlements", []):
                if settlement["debit_date"] == day:
                    if settlement.get("mode") != "RULE_BASED_SIMULATION":
                        raise ExecutionBlockedError("Synthetic replay cannot claim observed account tax debits")
                    amount = float(settlement["amount"])
                    if amount > cash:
                        raise ExecutionBlockedError("Tax debit exceeds actual cash")
                    dividend_tax.settle_tax(**settlement)
                    cash -= amount
                    withdrawable = max(0., withdrawable - amount)
                    output["cash_events"].append(dict(date=day, event="DIVIDEND_TAX_DEBIT", amount=-amount,
                        actual_debit_date=None, settlement_mode="RULE_BASED_SIMULATION"))
            for action in dividend_records[day]:
                dividend_tax.record_dividend(action["action_id"], action["instrument_id"], day,
                    action.get("cash_per_share"), tax_category=action["tax_category"],
                    terms_verified=action.get("terms_verified"), source_url=action.get("source_url"))
            for sid in lots:
                tax_qty = sum(lot["remaining"] for lot in dividend_tax.lots if lot["instrument_id"] == sid)
                if sid in stock_ids and tax_qty != quantity(sid):
                    raise ExecutionBlockedError("FIFO and account share reconciliation failure")
            output["tax_lots"].extend(dict(lot, date=day) for lot in dividend_tax.lots)
            output["dividend_entitlements"].extend(dict(claim, date=day) for claim in dividend_tax.entitlements)
        reserve = tax_reserve(day)
        nav = equity()
        if cash < -1e-7 or withdrawable < -1e-7 or withdrawable > cash + 1e-7:
            raise ExecutionBlockedError("Cash conservation failure")
        holdings_value = sum(quantity(sid) * marks.get(sid, 0.) for sid in lots)
        unpriced_rights = any(right["entitled_quantity"] > 0 and not right["final_recognized"]
                              for right in liquidation_rights.values())
        # Zero is a conservative mark, never proof that a delisted shareholder
        # has no recovery rights. Keep the shares and explicitly mark uncertainty.
        unpriced_stock_rights = any(quantity(sid) > 0 and sid in dead for sid in lots)
        stale_stock_marks = any(quantity(sid) > 0 and stale[sid] > 0 and sid not in dead
            and (master(sid, _cutoff(day)) or {}).get("asset_type") == "STOCK" for sid in lots)
        unknown_master = any(quantity(sid) > 0 and master(sid, _cutoff(day)) is None for sid in lots)
        unpriced_rights = unpriced_rights or unpriced_stock_rights
        valuation_status = ("ASSUMED_SCHEDULED_CREDIT" if assumed_settlement else
                            "OBSERVATION_TIME_REPLAY" if observation_replay else
                            "CONSERVATIVE_UNPRICED_RIGHTS" if unpriced_rights else
                            "UNKNOWN_INSTRUMENT_STATE" if unknown_master else
                            "STALE_STOCK_MARK" if stale_stock_marks else "PRICED_LEDGER")
        output["nav"].append({"date": day, "nav": nav, "cash_total": cash, "cash": cash,
            "cash_available": max(0., cash - reserve), "cash_withdrawable": max(0., min(withdrawable, cash - reserve)), "cash_reserved": reserve,
            "dividend_tax_payable": float(dividend_tax.tax_payable) if dividend_tax else 0.,
            "dividend_tax_paid": float(dividend_tax.tax_paid) if dividend_tax else 0.,
            "hypothetical_liquidation_nav": nav - reserve + (float(dividend_tax.tax_payable) if dividend_tax else 0.),
            "holdings_value": holdings_value, "receivables": float(sum(r["amount"] for r in receivables)), "mode": "DAILY_SCREEN_ONLY",
            "valuation_status": valuation_status, "valuation_uncertainty": observation_replay or assumed_settlement or unpriced_rights or stale_stock_marks or unknown_master,
            "assumed_settlement": assumed_settlement, "late_recognition": observation_replay})
        if dividend_tax is not None:
            output["tax_balances"].append(dict(date=day, tax_payable=float(dividend_tax.tax_payable),
                tax_paid=float(dividend_tax.tax_paid), tax_reserve=reserve))
        for right in liquidation_rights.values():
            if right["entitled_quantity"] == 0 and right["retired_quantity"] == 0:
                continue
            outstanding = _money(right["recognized_amount"] - right["paid_amount"])
            status = ("PAID_FINAL" if right["final_recognized"] and outstanding == 0 else
                      "FINAL_RECEIVABLE" if right["final_recognized"] else
                      "PARTIALLY_PRICED_RIGHT" if right["recognized_amount"] else "UNPRICED_RIGHT")
            output["rights"].append(dict(right, date=day, status=status,
                outstanding_receivable=outstanding, carrying_value=outstanding,
                valuation_uncertainty=not right["final_recognized"] or right["late_recognition"] or right["assumed_settlement"]))
            output["positions"].append({"date": day, "instrument_id": right["instrument_id"],
                "quantity": 0, "retired_quantity": right["retired_quantity"], "sellable_quantity": 0,
                "locked_quantity": 0, "price": 0., "market_value": 0., "weight": 0.,
                "stale_days": 0, "delisted_rights": True})
        industries = defaultdict(float)
        for sid in sorted(lots):
            qty = quantity(sid)
            if qty == 0:
                continue
            if sid in dead and sid not in retired_instruments:
                output["rights"].append(dict(date=day, entitlement_action_id="DELISTING:" + sid,
                    instrument_id=sid, entitled_quantity=qty, retired_quantity=0,
                    recognized_amount=0., paid_amount=0., outstanding_receivable=0.,
                    carrying_value=0., final_recognized=False, late_recognition=False,
                    assumed_settlement=False, status="UNPRICED_DELISTED_RIGHT", valuation_uncertainty=True))
            value, meta = qty * marks.get(sid, 0.), master(sid, _cutoff(day))
            sellable = sum(lot["quantity"] for lot in lots[sid] if lot["sellable_index"] <= index)
            weight = value / nav if nav > 0 else 0.
            output["positions"].append({"date": day, "instrument_id": sid, "quantity": qty,
                "retired_quantity": 0,
                "sellable_quantity": sellable, "locked_quantity": qty - sellable,
                "price": marks.get(sid, 0.), "market_value": value, "weight": weight,
                "stale_days": stale[sid], "delisted_rights": sid in dead})
            cap = .35 if (meta or {}).get("asset_type") == "ETF" else .05
            output["exposure"].append({"date": day, "scope": "INSTRUMENT", "key": sid,
                "weight": weight, "limit": cap, "breach": weight > cap + 1e-10})
            if meta is None or meta["asset_type"] == "STOCK":
                industries[str((meta or {}).get("industry", "UNKNOWN"))] += weight
        for industry, weight in industries.items():
            output["exposure"].append({"date": day, "scope": "STOCK_INDUSTRY", "key": industry,
                "weight": weight, "limit": .20, "breach": weight > .20 + 1e-10})
        output["exposure"].append({"date": day, "scope": "GROSS", "key": "ALL",
            "weight": holdings_value / nav if nav > 0 else 0., "limit": 1., "breach": holdings_value > nav + 1e-7})
        if day >= start_date:
            for sid in lots:
                record_holdings[(day, sid)] = quantity(sid)
        # Daily qualification exits precede monthly rebalancing. A detected
        # risk starts one bounded chain; an exhausted chain is not reset by
        # the same condition appearing on another daily screen.
        for sid in sorted(lots):
            if quantity(sid) == 0:
                risk_exit_started.discard(sid)
                continue
            if sid in dead or sid in risk_exit_started:
                continue
            meta = master(sid, _cutoff(day))
            risk_reason = permission(meta, day, True)
            if risk_reason not in {"BOARD_PERMISSION_DENIED", "ETF_PERMISSION_UNVERIFIED",
                                   "ACCOUNT_PERMISSION_REVOKED", "STOCK_PERMISSION_UNVERIFIED", "ANNOUNCED_DELISTING",
                                   "INSTRUMENT_STATUS_DENIED"}:
                continue
            risk_exit_started.add(sid)
            output["order_events"].append({"date": day, "event": "DAILY_RISK_EXIT",
                "instrument_id": sid, "quantity": quantity(sid), "reason": risk_reason})
            next_day = calendar[index + 1] if index + 1 < len(calendar) else None
            pending = [order for pending in queues.values() for order in pending
                       if order["instrument_id"] == sid]
            pending_sells = [order for order in pending if order["side"] == "SELL"]
            adequate_exit = any(order["execution_date"] == next_day and
                                order["quantity"] >= quantity(sid) for order in pending_sells)
            for queued_day, pending_orders in queues.items():
                retained = []
                for order in pending_orders:
                    replace_order = order["instrument_id"] == sid and (order["side"] == "BUY" or not adequate_exit)
                    if replace_order:
                        reject(order, day, "SUPERSEDED_BY_DAILY_RISK_EXIT")
                    else:
                        retained.append(order)
                queues[queued_day] = retained
            if adequate_exit:
                continue
            reference = marks.get(sid)
            raw_reference = bar(sid, day)
            source_reference = raw_reference["close"] if raw_reference else reference
            attempt = max((order["attempt"] for order in pending_sells), default=1)
            parent = pending_sells[0]["order_id"] if pending_sells else None
            risk_order = create_order(day, next_day, sid, "SELL", quantity(sid), reference,
                                      historical_adv(sid, day), attempt, parent, "RISK_EXIT", risk_reason,
                                      source_reference_price=source_reference,
                                      reference_basis="POST_EOD_ADJUSTED" if sid in eod_factors else "CARRIED_MARK")
            if next_day is None:
                reject(risk_order, day, "END_OF_DATA_UNFILLED_RETAIN_HOLDINGS")
            else:
                queues[next_day].append(risk_order)
        if day in decision_by_day:
            decision = decision_by_day[day]
            weights, refs, advs = decision["weights"], decision["reference_prices"], decision["adv20"]
            execution = str(decision["execution_date"])[:10]
            for sid in sorted(set(weights) | set(decision.get("fixed_quantities", {})) | {s for s in lots if quantity(s)}):
                meta, row = master(sid, _cutoff(day)), bar(sid, day)
                ref, supplied_adv = refs.get(sid), advs.get(sid)
                reason = None
                if not _valid(ref, True) or row is None or not math.isclose(float(ref), float(row["close"]), rel_tol=1e-8, abs_tol=1e-8):
                    reason = "REFERENCE_NOT_DECISION_CLOSE"
                actual_adv = historical_adv(sid, day)
                if not _valid(supplied_adv, True) or not _valid(actual_adv, True):
                    reason = reason or "MISSING_HISTORICAL_ADV"
                if reason:
                    buying = (decision["fixed_quantities"].get(sid, 0) > quantity(sid)
                              if "fixed_quantities" in decision else weights.get(sid, 0) > 0)
                    order = create_order(day, execution, sid, "BUY" if buying else "SELL", 0, ref, supplied_adv)
                    reject(order, day, reason)
                    continue
                source_ref = float(ref)
                ref = source_ref / eod_factors.get(sid, 1.)
                reference_basis = "POST_EOD_ADJUSTED" if sid in eod_factors else "RAW_CLOSE"
                if row.get("suspended") is not False or not _valid(row.get("volume"), True):
                    if quantity(sid) and _valid(marks.get(sid), True):
                        ref, reference_basis = marks[sid], "CARRIED_ACTION_ADJUSTED_MARK"
                    else:
                        order = create_order(day, execution, sid, "BUY", 0, ref, actual_adv,
                            source_reference_price=source_ref, reference_basis="UNTRADED_REFERENCE")
                        reject(order, day, "SUSPENDED_DECISION_REFERENCE")
                        continue
                target = int(nav * float(weights.get(sid, 0.)) / float(ref)) // 100 * 100
                if "fixed_quantities" in decision:
                    target = decision["fixed_quantities"].get(sid, 0)
                delta = target - quantity(sid)
                if delta == 0:
                    continue
                side = "BUY" if delta > 0 else "SELL"
                # Preserve active risk-exit retries; no duplicate sell reservation.
                pending_sell = any(o["instrument_id"] == sid and o["side"] == "SELL" for pending in queues.values() for o in pending)
                order = create_order(day, execution, sid, side, abs(delta), float(ref), min(float(supplied_adv), actual_adv),
                    source_reference_price=source_ref,
                    reference_basis=reference_basis)
                reason = permission(meta, day, side == "BUY")
                if sid in unresolved_shares and unresolved_shares[sid] > _cutoff(day):
                    reason = "SHARE_TERMS_NOT_YET_KNOWN"
                if sid in retired_instruments:
                    reason = "ECONOMICALLY_RETIRED_INSTRUMENT"
                if pending_sell:
                    reason = "PENDING_SELL_ALREADY_EXISTS"
                if side == "BUY" and meta is not None and float(weights.get(sid, 0)) > (.35 if meta["asset_type"] == "ETF" else .05) + 1e-10:
                    reason = "TARGET_INSTRUMENT_LIMIT"
                if reason:
                    reject(order, day, reason)
                else:
                    queues[execution].append(order)

    schemas = {
        "orders": ["order_id", "parent_order_id", "decision_date", "decision_at", "execution_date", "instrument_id", "side", "quantity", "qty_requested", "reference_price", "adv20", "attempt", "mode", "intent_type", "risk_reason", "source_reference_price", "reference_basis"],
        "fills": ["date", "order_id", "instrument_id", "side", "quantity", "price", "notional", "commission", "stamp_duty", "transfer_fee", "fees", "slippage_cost", "mode"],
        "rejected_orders": ["order_id", "date", "instrument_id", "side", "quantity", "reason"],
        "costs": ["date", "order_id", "instrument_id", "commission", "stamp_duty", "transfer_fee", "total_cost", "slippage_cost"],
        "positions": ["date", "instrument_id", "quantity", "retired_quantity", "sellable_quantity", "locked_quantity", "price", "market_value", "weight", "stale_days", "delisted_rights"],
        "rights": ["date", "entitlement_action_id", "instrument_id", "record_date", "retirement_date",
                   "entitled_quantity", "retired_quantity", "recognized_amount", "paid_amount",
                   "outstanding_receivable", "carrying_value", "final_recognized", "late_recognition", "assumed_settlement", "status", "valuation_uncertainty"],
    }
    if dividend_tax is not None:
        output["tax_events"] = dividend_tax.events
    result = {key: pd.DataFrame(rows, columns=schemas.get(key)) for key, rows in output.items()}
    if engineering_replay:
        for table in result.values():
            table["purpose"] = REPLAY_TAG
            table["synthetic"] = True
    for key, table in result.items():
        if "date" in table.columns and key != "share_events":
            result[key] = table.loc[table["date"] >= start_date].reset_index(drop=True)
    result["mode"] = "DAILY_SCREEN_ONLY"
    result["purpose"] = REPLAY_TAG if engineering_replay else "DAILY_SCREEN_ONLY"
    result["performance_evidence"] = False
    result["rule_based_settlement"] = rule_based_settlement
    result["cash_delay_sessions"] = cash_delay_sessions
    result["accounting_timing_eligible"] = not bool(result["nav"]["valuation_uncertainty"].any())
    result["confirmation_eligible"] = False  # Daily screening never verifies executable confirmation.
    result["limitations"] = ["Daily bars do not establish opening queue liquidity.",
        "Stock dividend FIFO is connected only for explicit synthetic engineering replay; real stock admission remains blocked.",
        "Pending orders are canceled on a corporate-action ex-date; buys are not retried.",
        "Unpriced liquidation rights carry zero with explicit valuation uncertainty; late recovery observations never backfill cash.",
        "ETF look-through industry exposure is unavailable; observed stock industries only."]
    return result
