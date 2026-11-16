"""M8-specific source binding; invented files are not market evidence."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from quant_research.data import DataValidationError
from quant_research.liquid_runner import _verify_source_files, validate_liquid_config


def test_m7_cash_admission_cannot_authorize_m8_holdings(tmp_path):
    path = tmp_path / 'reports/m8_rotation/COHORT_SELECTION.json'
    path.parent.mkdir(parents=True)
    selection = {'synthetic_boundary_test': True}
    path.write_text(json.dumps(selection), encoding='utf-8')
    manifest = dict(synthetic=False, cohort_selection=selection,
                    cohort_selection_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    admission_scope='QUALIFICATION_ONLY_ALL_CASH')
    with pytest.raises(DataValidationError, match='cannot authorize M8 holdings'):
        _verify_source_files(SimpleNamespace(manifest=manifest), tmp_path)


def test_modified_formation_cannot_reuse_source_admission(tmp_path):
    path = tmp_path / 'reports/m8_rotation/COHORT_SELECTION.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"changed":true}', encoding='utf-8')
    manifest = dict(synthetic=False, cohort_selection={}, cohort_selection_sha256='0' * 64,
                    admission_scope='FULL_HOLDING_DEPENDENCIES')
    with pytest.raises(DataValidationError, match='Frozen formation'):
        _verify_source_files(SimpleNamespace(manifest=manifest), tmp_path)


def test_registered_pressure_combinations_do_not_open_search_or_impute_cost():
    config = dict(protocol_version='phase2-mvp-0.1', live_enabled=False,
        universe='R1I_HISTORICAL_LIQUID_V1', initial_cash=100000,
        primary_capital_confirmed=True, risk_scaling=False, signal_release_delay=1,
        seed=20261114, claim_type='economic_increment', sample='validation', variant='R0',
        annual_incremental_cost=None, cost_multiplier=1, slippage_multiplier=1, execution_delay=1)
    for cost, slip, delay in ((1, 1, 1), (2, 2, 1), (3, 3, 1), (1, 1, 2)):
        validate_liquid_config(dict(config, cost_multiplier=cost, slippage_multiplier=slip,
                                    execution_delay=delay))
    for changes in ({'cost_multiplier': 2}, {'execution_delay': 3}, {'annual_incremental_cost': 0},
                    {'sample': 'holdout'}, {'initial_cash': 1000000}, {'risk_scaling': True}):
        with pytest.raises(ValueError):
            validate_liquid_config(dict(config, **changes))
