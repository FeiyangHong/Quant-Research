"""Two invented ledger-arithmetic cases; no executable ETF order is asserted.

The three-unit example intentionally isolates rounding, not lot-size validation.
Both fail against the frozen legacy checker: it rejects the correct amount and
accepts the wrong amount. After Decimal multiplication repair, both must pass.
"""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.summarize_runs import reconcile


def invented_ledger(stored_notional):
    """Cash/NAV are internally consistent with either submitted notional."""
    date, quantity, price, fees = "2020-01-02", 3, .565, 5.
    cash = 1000. - stored_notional - fees
    holding = quantity * price
    return {
        "nav": pd.DataFrame([dict(date=date, nav=cash + holding, cash_total=cash,
            cash_available=cash, cash_reserved=0., cash_withdrawable=cash,
            holdings_value=holding, receivables=0.)]),
        "positions": pd.DataFrame([dict(date=date, instrument_id="INVENTED_ARITHMETIC_ONLY",
            quantity=quantity, price=price, market_value=holding)]),
        "fills": pd.DataFrame([dict(date=date, order_id="INVENTED_ARITHMETIC_ONLY", side="BUY",
            quantity=quantity, price=price, notional=stored_notional, fees=fees,
            commission=fees, stamp_duty=0., transfer_fee=0.)]),
        "cash_events": pd.DataFrame([dict(date=date, event="BUY", amount=-stored_notional - fees)]),
        "costs": pd.DataFrame([dict(date=date, total_cost=fees)])
    }


def test_decimal_notional_checker_accepts_correct_half_cent_boundary():
    expected = (Decimal(3) * Decimal("0.565")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert expected == Decimal("1.70")
    assert reconcile(invented_ledger(float(expected)), 1000.)["status"] == "PASS"


def test_decimal_notional_checker_rejects_consistently_booked_wrong_cent():
    # Wrong notional is propagated through cash and NAV. Only an independent
    # exact quantity-times-price check can detect the one-cent defect.
    with pytest.raises(ValueError, match="fill_notional"):
        reconcile(invented_ledger(1.69), 1000.)
