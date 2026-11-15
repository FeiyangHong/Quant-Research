"""Hand-accounted invented batches; not market or strategy performance."""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from quant_research.engineering_replay import REPLAY_TAG, synthetic_fixture
from quant_research.execution import run_backtest


def cents(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


@pytest.mark.parametrize('board', ['MAIN', 'CHINEXT'])
@pytest.mark.parametrize('case,tax', [('ordinary_special', Decimal('80')), ('late_exit', Decimal('40'))])
def test_fixed_batches_daily_cash_tax_and_equity_hand_reconciliation(board, case, tax):
    data, instructions = synthetic_fixture(board, case)
    result = run_backtest(data, instructions, 100000, engineering_replay=True)
    assert result['purpose'] == REPLAY_TAG
    assert list(result['fills'].quantity) == [200, 200, 400]
    assert list(result['fills'].side) == ['BUY', 'BUY', 'SELL']
    assert not result['confirmation_eligible']
    cash, quantity, receivable, payable, paid = Decimal('100000'), 0, Decimal(0), Decimal(0), Decimal(0)
    for day in data['calendar']:
        for action in data['actions'].to_dict('records'):
            if action['ex_date'] == day:
                receivable += 400 * Decimal(str(action['cash_per_share']))
            if action['pay_date'] == day:
                amount = 400 * Decimal(str(action['cash_per_share']))
                cash += amount
                receivable -= amount
        for fill in result['fills'].loc[result['fills'].date == day].to_dict('records'):
            buy = fill['side'] == 'BUY'
            amount = cents(Decimal(fill['quantity']) * Decimal(str(fill['price'])))
            transfer = cents(amount * Decimal('.00001'))
            stamp = Decimal(0) if buy else cents(amount * Decimal('.0005'))
            fees = Decimal('5') + transfer + stamp
            assert cents(fill['fees']) == fees
            cash += -amount-fees if buy else amount-fees
            quantity += fill['quantity'] if buy else -fill['quantity']
            if not buy:
                payable = tax
        for debit in data['tax_settlements']:
            if debit['debit_date'] == day:
                assert Decimal(str(debit['amount'])) == tax
                cash -= tax
                payable -= tax
                paid += tax
        nav = result['nav'].set_index('date').loc[day]
        assert cents(nav.cash_total) == cash
        assert cents(nav.receivables) == receivable
        assert cents(nav.dividend_tax_payable) == payable
        assert cents(nav.dividend_tax_paid) == paid
        assert cents(nav.holdings_value) == quantity * Decimal('10')
        assert cents(nav.nav) == cash + receivable + quantity*Decimal('10') - payable
        assert cents(nav.cash_available) + cents(nav.cash_reserved) == cash
        assert cents(nav.hypothetical_liquidation_nav) == cents(nav.nav) - cents(nav.cash_reserved) + payable
    assert paid == tax and quantity == 0 and payable == receivable == 0
    assert cash == Decimal('100374.92') - tax
    if case == 'late_exit':
        assert len(result['rejected_orders'].query("reason == 'SUSPENDED_OR_UNKNOWN_STATUS'")) == 5
    assert result['cash_events'].loc[result['cash_events'].event == 'DIVIDEND_TAX_DEBIT', 'actual_debit_date'].isna().all()


def test_replay_does_not_relable_real_source_or_open_holdout():
    data, instructions = synthetic_fixture()
    data['manifest']['synthetic'] = False
    with pytest.raises(ValueError):
        run_backtest(data, instructions, 100000, engineering_replay=True)
    data['manifest']['synthetic'] = True
    data['calendar'].append('2025-01-02')
    with pytest.raises(ValueError):
        run_backtest(data, instructions, 100000, engineering_replay=True)


def test_engineering_cash_dividend_does_not_implicitly_enable_normal_runner():
    data, instructions = synthetic_fixture()
    with pytest.raises(ValueError):
        run_backtest(data, instructions, 100000)
