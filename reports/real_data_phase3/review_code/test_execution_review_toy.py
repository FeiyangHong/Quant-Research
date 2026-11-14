"""Small fault-injection self-checks for the read-only review, not a backtest."""
import copy
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import runpy
import unittest

SCRIPT=Path(__file__).with_name('review_real_execution.py')
API=runpy.run_path(str(SCRIPT))

def fixture(q=100,opening=10,price=10.003,buy=True,cost=1,slip=1):
    side='BUY' if buy else 'SELL'
    c=dict(cost_multiplier=cost,slippage_multiplier=slip)
    m=dict(asset_type='ETF',t_plus=1,lot_size=100,tick_size=.001,listed_on='2010-01-01',delisted_on=None,account_verified=True,status='NORMAL')
    b=dict(date='2020-01-03',open=opening,high=20,low=.1,close=opening,upper_limit=20,lower_limit=.1,suspended=False,volume=1e8,amount=1e9)
    o=dict(instrument_id='ETF',side=side,execution_date=b['date'],quantity=q,reference_price=opening,adv20=1e9)
    n=API['money'](D(q)*D(str(price)))
    fee=API['money'](max(D(5),n*D('.0003'))*cost)
    f=dict(date=b['date'],order_id='O1',instrument_id='ETF',side=side,quantity=q,price=price,notional=float(n),commission=float(fee),stamp_duty=0,transfer_fee=0,fees=float(fee),slippage_cost=float(API['money'](D(q)*abs(D(str(price))-D(str(opening))))),mode='DAILY_SCREEN_ONLY')
    return f,o,b,m,c

class ReviewToy(unittest.TestCase):
    def test_valid_and_zero_slippage(self):
        for params in ({},{'price':10.,'slip':0}):
            x=fixture(**params);findings=[]
            API['verify_fill'](*x,{},findings)
            self.assertEqual(findings,[])
    def test_suspension(self):
        x=fixture();x[2]['suspended']=True
        with self.assertRaisesRegex(AssertionError,'tradable'):API['verify_fill'](*x,{})
    def test_permission(self):
        x=fixture();x[3]['account_verified']=False
        with self.assertRaisesRegex(AssertionError,'permission'):API['verify_fill'](*x,{})
    def test_announced_retirement(self):
        x=fixture();x[3]['delisted_on']='2020-02-01'
        with self.assertRaisesRegex(AssertionError,'permission'):API['verify_fill'](*x,{})
    def test_buy_odd_lot(self):
        x=fixture(q=101)
        with self.assertRaisesRegex(AssertionError,'lots of 100'):API['verify_fill'](*x,{})
    def test_adverse_limit(self):
        x=fixture();x[2]['upper_limit']=10
        with self.assertRaisesRegex(AssertionError,'adverse limit'):API['verify_fill'](*x,{})
    def test_bad_grid(self):
        x=fixture();x[2]['open']=10.0001
        with self.assertRaisesRegex(AssertionError,'price grid'):API['verify_fill'](*x,{})
    def test_low_price(self):
        x=fixture();x[0]['price']=9.999
        with self.assertRaisesRegex(AssertionError,'slippage and tick'):API['verify_fill'](*x,{})
    def test_outside_daily_range(self):
        x=fixture();x[2]['high']=10
        with self.assertRaisesRegex(AssertionError,'OHLC'):API['verify_fill'](*x,{})
    def test_capacity_shared_across_orders(self):
        x=fixture();x[1]['adv20']=100000
        with self.assertRaisesRegex(AssertionError,'ADV capacity'):API['verify_fill'](*x,{})
        x[1]['adv20']=200000
        with self.assertRaisesRegex(AssertionError,'ADV capacity'):API['verify_fill'](*x,{'ETF':D(1000)})
    def test_order_size_immutable(self):
        x=fixture();x[1]['quantity']=99
        with self.assertRaisesRegex(AssertionError,'intended units'):API['verify_fill'](*x,{})
    def test_tplus_one_and_full_odd_sale(self):
        API['verify_sale'](250,250,250)
        with self.assertRaisesRegex(AssertionError,'T\+1'):API['verify_sale'](200,300,100)
        with self.assertRaisesRegex(AssertionError,'odd-lot'):API['verify_sale'](150,250,250)
    def test_fee_error_is_not_swallowed(self):
        x=fixture();x[0]['commission']=4.;x[0]['fees']=4.
        with self.assertRaisesRegex(AssertionError,'commission'):API['verify_fill'](*x,{})
    def test_decimal_commission_regression(self):
        x=fixture(q=12500,opening=1.65,price=1.652,cost=3,slip=3)
        API['verify_fill'](*x,{},[])
        x[0]['commission']=18.58;x[0]['fees']=18.58;findings=[]
        API['verify_fill'](*x,{},findings)
        self.assertEqual([f['kind'] for f in findings],['DECIMAL_COMMISSION_ROUNDING'])
        self.assertEqual(findings[0]['expected_decimal'],'18.59')
    def test_decimal_odd_lot_notional_regression(self):
        x=fixture(q=373,opening=2.698,price=2.695,buy=False,cost=3,slip=3)
        API['verify_fill'](*x,{},[])
        x[0]['notional']=1005.23;findings=[]
        API['verify_fill'](*x,{},findings)
        self.assertIn('DECIMAL_NOTIONAL_ROUNDING',[f['kind'] for f in findings])
    def test_decimal_slippage_amount_regression(self):
        x=fixture(q=33775,opening=2.58,price=2.579,buy=False)
        API['verify_fill'](*x,{},[])
        x[0]['slippage_cost']=33.77;findings=[]
        API['verify_fill'](*x,{},findings)
        self.assertIn('DECIMAL_SLIPPAGE_AMOUNT_ROUNDING',[f['kind'] for f in findings])

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReviewToy))
    report=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests_run=result.testsRun,
        errors=len(result.errors),failures=len(result.failures),purpose='FAULT_INJECTION_REVIEW_SELF_CHECK_NO_STRATEGY_RUN',
        review_code_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        selfcheck_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    Path('work/execution_review_toy_checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(not result.wasSuccessful())
