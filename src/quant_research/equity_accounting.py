"""Isolated equity admission primitives, not an admitted performance engine.

Cash-dividend FIFO follows Cai Shui [2015] 101 and the 2015 official Q&A.
This component has no market data, orders or cash-account access. A sale
accrues tax; a separate settlement call records a modeled/observed debit.
The main execution ledger connects this only in explicitly declared
engineering accounting. Real stock strategy admission remains blocked.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


class EquityAccountingBlocked(ValueError):
    """Evidence or supported accounting semantics are missing."""


def _day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise EquityAccountingBlocked("Explicit ISO date required")


def _amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (ValueError, ArithmeticError):
        raise EquityAccountingBlocked("Explicit nonnegative finite amount required")


def _quantity(value):
    if type(value) is not int or value <= 0:
        raise EquityAccountingBlocked("Positive integer share quantity required")
    return value


def _evidence(verified, source_url):
    if verified is not True or not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise EquityAccountingBlocked("Verified source terms required; URL alone is not verification")


def dividend_tax_rate(acquired_on, disposed_on, record_date):
    """2016--2024 ordinary tradable A shares, domestic individual investor.

    Holding period excludes disposal day. Exactly one natural month remains
    20%; exactly one year remains 10%. No 30/365-day approximation. Missing
    corresponding calendar dates (Jan 31 / leap day) need a CSDC convention;
    reject instead of silently choosing a library's month-end convention.
    """
    acquired, disposed, record = map(_day, (acquired_on, disposed_on, record_date))
    if not date(2016, 1, 1) <= record <= date(2024, 12, 31):
        raise EquityAccountingBlocked("Dividend tax regime outside reviewed 2016--2024 scope")
    if disposed <= acquired or record < acquired or disposed <= record:
        raise EquityAccountingBlocked("Disposal must follow acquisition and dividend record date")
    if disposed > date(2024, 12, 31):
        raise EquityAccountingBlocked("Final holdout is locked")
    return _holding_rate(acquired, disposed)


def _holding_rate(acquired, disposed):
    try:
        year_end = acquired.replace(year=acquired.year + 1)
        month_end = acquired.replace(year=acquired.year + (acquired.month == 12),
                                     month=acquired.month % 12 + 1)
    except ValueError:
        raise EquityAccountingBlocked("Nonexistent calendar anniversary needs verified CSDC convention")
    if disposed <= month_end:
        return Decimal("0.20")
    if disposed <= year_end:
        return Decimal("0.10")
    return Decimal("0")


class CashDividendTaxLedger:
    """FIFO lots and retained dividend claims for engineering cash/NAV replay.

    Caller supplies verified record-date events chronologically, after that
    day's trades. Rates concern tax liability, not proof of broker debit time.
    Reserve is ceil-to-cent potential tax plus accrued unpaid tax. It is a
    cash restriction, not an extra expense: subtract liabilities once when
    reporting hypothetical liquidation NAV, never deduct reserve twice.
    """
    def __init__(self, account_type):
        if account_type != "DOMESTIC_INDIVIDUAL_ORDINARY_A_SHARE":
            raise EquityAccountingBlocked("Unsupported dividend taxpayer or share class")
        self.lots = []
        self.entitlements = []
        self.events = []
        self.tax_payable = Decimal("0")
        self.tax_paid = Decimal("0")
        self._last_day = None
        self._closed_record_days = set()
        self._action_ids = set()
        self._settlement_ids = set()

    def _check_day(self, day, trading=False):
        parsed = _day(day)
        if parsed > date(2024, 12, 31):
            raise EquityAccountingBlocked("Final holdout is locked")
        if self._last_day is not None and day < self._last_day:
            raise EquityAccountingBlocked("Cannot backfill tax ledger history")
        if trading and day in self._closed_record_days:
            raise EquityAccountingBlocked("Record-date close already captured")

    def buy(self, instrument_id, quantity, acquired_on):
        self._check_day(acquired_on, trading=True)
        _quantity(quantity)
        lot_id = "L%08d" % (len(self.lots) + 1)
        self.lots.append(dict(lot_id=lot_id, instrument_id=instrument_id,
                              acquired_on=acquired_on, original_quantity=quantity, remaining=quantity))
        self._last_day = acquired_on
        return lot_id

    def record_dividend(self, action_id, instrument_id, record_date, gross_per_share,
                        *, tax_category, terms_verified, source_url):
        self._check_day(record_date)
        _evidence(terms_verified, source_url)
        if tax_category != "ORDINARY_CASH_DIVIDEND":
            raise EquityAccountingBlocked("Bonus, conversion and rights tax classification unsupported")
        if not "2016-01-01" <= record_date <= "2024-12-31":
            raise EquityAccountingBlocked("Dividend tax regime outside reviewed 2016--2024 scope")
        if action_id in self._action_ids:
            raise EquityAccountingBlocked("Duplicate dividend action")
        gross = _amount(gross_per_share)
        for lot in self.lots:
            if lot["instrument_id"] == instrument_id and lot["remaining"]:
                self.entitlements.append(dict(action_id=action_id, instrument_id=instrument_id,
                    lot_id=lot["lot_id"], acquired_on=lot["acquired_on"], record_date=record_date,
                    entitled_quantity=lot["remaining"], remaining=lot["remaining"],
                    gross_per_share=gross, source_url=source_url))
        self._action_ids.add(action_id)
        self._closed_record_days.add(record_date)
        self._last_day = record_date

    def sell(self, instrument_id, quantity, disposed_on):
        self._check_day(disposed_on, trading=True)
        _quantity(quantity)
        candidates = [lot for lot in self.lots if lot["instrument_id"] == instrument_id and lot["remaining"]]
        if sum(lot["remaining"] for lot in candidates if lot["acquired_on"] < disposed_on) < quantity:
            raise EquityAccountingBlocked("Insufficient prior-day FIFO shares; T+1 or short sale")
        # Validate and calculate the entire sale before mutating any lot.
        left, allocations, charges = quantity, [], defaultdict(Decimal)
        claim_changes = []
        for lot in candidates:
            take = min(left, lot["remaining"])
            if not take:
                break
            allocations.append((lot, take))
            for claim in self.entitlements:
                if claim["lot_id"] == lot["lot_id"] and claim["remaining"]:
                    entitled = min(take, claim["remaining"])
                    rate = dividend_tax_rate(lot["acquired_on"], disposed_on, claim["record_date"])
                    charges[claim["action_id"]] += entitled * claim["gross_per_share"] * rate
                    claim_changes.append((claim, entitled))
            left -= take
        # Per action, per disposal rounding is an explicit research convention;
        # broker/CSDC cash reconciliation is still required for real admission.
        tax = sum((amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                   for amount in charges.values()), Decimal("0"))
        for lot, take in allocations:
            lot["remaining"] -= take
        for claim, take in claim_changes:
            claim["remaining"] -= take
        self.tax_payable += tax
        self._last_day = disposed_on
        event = dict(event="DIVIDEND_TAX_ACCRUED", date=disposed_on, instrument_id=instrument_id,
                     quantity=quantity, amount=tax, actual_debit_date=None,
                     lot_allocations=[(lot["lot_id"], take) for lot, take in allocations])
        self.events.append(event)
        return dict(event)

    def reserve(self, liquidation_date):
        self._check_day(liquidation_date)
        potential = defaultdict(Decimal)
        for claim in self.entitlements:
            if claim["remaining"]:
                # Record-close reserve anticipates the earliest following
                # calendar-day disposal without manufacturing a future trade.
                disposal = max(_day(liquidation_date), _day(claim["record_date"]) + timedelta(days=1))
                rate = _holding_rate(_day(claim["acquired_on"]), disposal)
                potential[claim["action_id"]] += claim["remaining"] * claim["gross_per_share"] * rate
        # Sale rounds separately per dividend action. Rounding the combined
        # reserve could underfund several simultaneous half-cent liabilities.
        return self.tax_payable + sum((value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
                                       for value in potential.values()), Decimal("0"))

    def settle_tax(self, settlement_id, debit_date, amount, *, terms_verified, source_url, mode):
        self._check_day(debit_date)
        _evidence(terms_verified, source_url)
        if mode not in ("VERIFIED_ACCOUNT_DEBIT", "RULE_BASED_SIMULATION"):
            raise EquityAccountingBlocked("Explicit observed or modeled tax-debit mode required")
        amount = _amount(amount)
        if amount != amount.quantize(Decimal("0.01")) or amount > self.tax_payable or amount <= 0:
            raise EquityAccountingBlocked("Tax debit must be positive cents within accrued payable")
        if settlement_id in self._settlement_ids:
            raise EquityAccountingBlocked("Duplicate tax settlement")
        self.tax_payable -= amount
        self.tax_paid += amount
        self._settlement_ids.add(settlement_id)
        self._last_day = debit_date
        self.events.append(dict(event="DIVIDEND_TAX_DEBIT", date=debit_date, amount=amount,
            settlement_id=settlement_id, mode=mode,
            actual_debit_date=debit_date if mode == "VERIFIED_ACCOUNT_DEBIT" else None,
            source_url=source_url))


def daily_limit_ratio(*, board, day, is_st, listed_on, listing_session,
                      ipo_regime, special_session=False, delisting_started_on=None):
    """Reviewed ordinary 2016--2024 regimes, not fabricated limit prices.

    None explicitly represents an IPO session without a daily limit; the
    existing daily execution engine cannot admit such a session. Caller must
    still provide historical status, reference price and source evidence.
    """
    trade, listing = _day(day), _day(listed_on)
    if not date(2016, 1, 1) <= trade <= date(2024, 12, 31):
        raise EquityAccountingBlocked("Trading rule outside reviewed 2016--2024 scope")
    if board not in ("MAIN", "CHINEXT") or type(is_st) is not bool:
        raise EquityAccountingBlocked("Unknown board or historical ST status")
    if type(listing_session) is not int or listing_session <= 0 or trade < listing:
        raise EquityAccountingBlocked("Verified listing-session ordinal required")
    if (trade == listing) != (listing_session == 1):
        raise EquityAccountingBlocked("Listing date and session ordinal disagree")
    if special_session is not False:
        raise EquityAccountingBlocked("Special relisting/resumption/session rule requires separate evidence")
    if ipo_regime not in ("APPROVAL", "REGISTRATION"):
        raise EquityAccountingBlocked("Unknown historical IPO regime")
    boundary = date(2020, 8, 24) if board == "CHINEXT" else date(2023, 4, 10)
    if ipo_regime == "REGISTRATION" and listing < boundary:
        raise EquityAccountingBlocked("IPO regime predates board registration reform")
    if listing_session <= 5 and ipo_regime == "REGISTRATION":
        return None
    if listing_session == 1:
        raise EquityAccountingBlocked("Legacy IPO first-day asymmetrical limits require issue-price evidence")
    if delisting_started_on is not None:
        entered = _day(delisting_started_on)
        if entered > trade:
            raise EquityAccountingBlocked("Future delisting status cannot affect today's rule")
        if board == "CHINEXT" and entered < date(2020, 8, 24):
            return Decimal("0.10")
        raise EquityAccountingBlocked("Delisting-period first-day/transition rules require event evidence")
    if board == "CHINEXT" and trade >= date(2020, 8, 24):
        return Decimal("0.20")
    return Decimal("0.05") if is_st else Decimal("0.10")
