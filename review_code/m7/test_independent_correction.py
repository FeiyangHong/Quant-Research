"""The one bounded M7 correction round, following initial independent review."""
import pytest

from test_independent_cohort import fixture, IDS
from quant_research.cohort import cohort_dependencies, cohort_opportunities
from quant_research.cohort_runner import validate_cohort_config
from quant_research.strategy import StrategyBlockedError


def test_unverified_false_cannot_be_silently_treated_as_known_denial():
    data=fixture(4)
    data.instruments.loc[0,'account_verified']=False
    with pytest.raises(StrategyBlockedError):cohort_dependencies(data)
    data.instruments['account_permission_status']='VERIFIED'
    data.instruments.loc[0,'account_permission_status']='DENIED'
    proof=cohort_dependencies(data)
    legal=[r for r in proof['schedule'] if r['eligible_count'] is not None]
    assert IDS[0] not in legal[0]['eligible']
    assert legal[0]['eligible_count']==3


def test_unknown_fixed_cost_is_frozen_not_an_optional_runtime_imputation():
    config=dict(protocol_version='phase2-mvp-0.1',live_enabled=False,universe='R1I_FIXED_COHORT_V1',
                initial_cash=100000,primary_capital_confirmed=True,risk_scaling=False,
                signal_release_delay=1,seed=20261114,claim_type='economic_increment',
                sample='validation',variant='R0',cost_multiplier=1,slippage_multiplier=1,
                execution_delay=1,annual_incremental_cost=None)
    validate_cohort_config(config)
    for cost in [0,1000]:
        with pytest.raises(ValueError):validate_cohort_config(dict(config,annual_incremental_cost=cost))
    del config['annual_incremental_cost']
    with pytest.raises(ValueError):validate_cohort_config(config)


def test_preactivation_cash_not_counted_as_legal_cohort_anchor():
    result=cohort_opportunities(fixture(2))
    assert result['scheduled_count']==2
    assert result['legal_anchor_count']==1
    assert result['preactivation_cash_count']==1
