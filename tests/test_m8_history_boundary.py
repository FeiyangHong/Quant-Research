"""Listing-age calendar must not silently change the registered market window."""
import pandas as pd

from quant_research.data import Dataset, REQUIRED, SCHEMA_VERSION, audit_dataset


def data():
    calendar = ['2018-12-28', '2019-01-02', '2019-01-03']
    masters, bars = [], []
    for n in range(6):
        sid = 'INVENTED_' + str(n)
        masters.append(dict(instrument_id=sid, asset_type='ETF', board='ETF',
            listed_on=calendar[0], delisted_on=None, available_at='2018-12-27T21:00:00+08:00',
            account_verified=True, status='NORMAL', benchmark_id='I'+str(n), industry='TEST',
            lot_size=100, tick_size=.001, t_plus=1, revision_id=sid, supersedes_id=None,
            strategy_universe='R1I_HISTORICAL_LIQUID_V1'))
        for day in calendar[1:]:
            bars.append(dict(instrument_id=sid, date=day, open=2., high=2.02, low=1.98, close=2.,
                volume=20000000, amount=40000000, upper_limit=2.2, lower_limit=1.8,
                suspended=False, total_return_index=100., available_at=day+'T16:00:00+08:00',
                revision_id=sid+day, supersedes_id=None))
    benchmark = pd.DataFrame([dict(date=day, total_return_index=100.,
        available_at=day+'T16:00:00+08:00', revision_id=day, supersedes_id=None) for day in calendar])
    return Dataset(calendar, pd.DataFrame(masters), pd.DataFrame(bars),
        pd.DataFrame(columns=REQUIRED['actions']), benchmark,
        dict(dataset_id='invented-boundary', dataset_version='1', synthetic=True,
             schema_version=SCHEMA_VERSION, timezone='Asia/Shanghai',
             research_scope='R1I_HISTORICAL_LIQUID_V1', market_history_start='2019-01-01',
             units=dict(volume='shares_or_fund_units', amount='CNY', price='CNY')))


def test_earlier_age_calendar_is_preserved_without_unneeded_price_dependency():
    result = audit_dataset(data())
    assert not result['errors'] and not result['blockers']
    assert result['coverage']['calendar_sessions'] == 3
    assert result['coverage']['earlier_calendar_purpose'] == 'LISTING_AGE_ONLY'


def test_missing_2019_observation_and_moved_start_still_block():
    dataset = data()
    dataset.bars = dataset.bars.iloc[1:]
    assert any('missing 1 listed sessions' in b for b in audit_dataset(dataset)['blockers'])
    dataset.manifest['market_history_start'] = '2020-01-01'
    assert any('fixed2019' in b for b in audit_dataset(dataset)['blockers'])


def test_boundary_does_not_waive_old_scope_history():
    dataset = data()
    dataset.manifest['research_scope'] = 'R1B'
    assert sum('missing 1 listed sessions' in b for b in audit_dataset(dataset)['blockers']) == 6
