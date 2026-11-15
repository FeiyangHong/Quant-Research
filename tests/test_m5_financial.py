"""Fixed documentary cases plus explicitly invented mutations; no alpha evidence."""
import json
from pathlib import Path
from decimal import Decimal

import pandas as pd
import pytest

from quant_research.data import DataValidationError
from quant_research.equity_features import financial_asof, r2_factors

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/m5_financial"


@pytest.fixture
def real_inputs():
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    facts = pd.DataFrame(read(OUT / "canonical_facts.json"))
    coverage = pd.DataFrame(read(OUT / "report_coverage.json"))
    cal = read(ROOT / "tests/fixtures/m5_verified_calendar_2015_2024.json")["trading_dates"]
    return facts, coverage, cal


def empty_market():
    return pd.DataFrame(columns=["instrument_id", "date", "available_at", "market_cap", "market_cap_scope"])


def calculate(inputs, identity="sz.002857", at="2023-10-27T21:00:00+08:00", market=None):
    facts, coverage, cal = inputs
    contract = coverage.loc[coverage.instrument_id.eq(identity) & coverage["asof"].eq(at)]
    return r2_factors(facts, empty_market() if market is None else market, at, cal, [identity], report_coverage=contract).iloc[0]


def test_two_real_cases_use_main_chain_and_decimal_hand_values(real_inputs):
    annual = calculate(real_inputs, "sh.600518", "2018-04-27T21:00:00+08:00")
    quarter = calculate(real_inputs)
    aa = (Decimal("68722020630.61") + Decimal("54823896576.81")) / 2
    qa = (Decimal("726007340.73") + Decimal("606916408.59")) / 2
    qp = Decimal("-6354889.62") + Decimal("12944711.92") - Decimal("100478.18")
    qc = Decimal("-9898689.75") + Decimal("45404676.85") - Decimal("-20765136.43")
    assert annual.F02 == pytest.approx(float(Decimal("4100926148.57") / aa), abs=1e-14)
    assert annual.F03 == pytest.approx(float(Decimal("1842794237.84") / aa), abs=1e-14)
    assert quarter.F02 == pytest.approx(float(qp / qa), abs=1e-14)
    assert quarter.F03 == pytest.approx(float(qc / qa), abs=1e-14)
    assert len(annual.input_revision_ids) == 4
    assert len(quarter.input_revision_ids) == 8
    for r in (annual, quarter):
        assert r.F01 is None
        assert "NO_VISIBLE_SAME_DAY_MARKET_CAP" in r.missing_reasons
        assert not r.formal_eligible and not r.all_three_valid
        assert r.freshness_status == "UNASSESSED_NO_REGISTERED_POLICY"
        assert r.latest_period_status == "UNVERIFIED"


@pytest.mark.parametrize("identity,at,later,expected", [
    ("sh.600518", "2018-04-27T21:00:00+08:00", "2019-05-06T21:00:00+08:00", "2149836281.41"),
    ("sz.002857", "2023-10-27T21:00:00+08:00", "2024-12-26T21:00:00+08:00", "-8587577.84")])
def test_real_later_corrections_preserve_prefix_and_select_revision(real_inputs, identity, at, later, expected):
    facts, coverage, cal = real_inputs
    original_prefix = facts.loc[pd.to_datetime(facts.available_at, utc=True) <= pd.Timestamp(at)]
    pd.testing.assert_series_equal(calculate(real_inputs, identity, at), calculate((original_prefix, coverage, cal), identity, at))
    rows = financial_asof(facts, later, cal)
    target = "2017-12-31" if identity == "sh.600518" else "2023-09-30"
    selected = rows.loc[rows.instrument_id.eq(identity) & rows.period_end.eq(target) & rows.field.eq("net_profit_parent_ytd")].iloc[0]
    assert selected.value == expected and selected.version_basis == "CORRECTION_FILING"
    assert selected.supersedes_id


@pytest.mark.parametrize("identity,later,period", [
    ("sh.600518", "2019-05-06T21:00:00+08:00", "2019-03-31"),
    ("sz.002857", "2024-12-26T21:00:00+08:00", "2024-09-30")])
def test_known_later_unparsed_report_blocks_old_complete_period(real_inputs, identity, later, period):
    r = calculate(real_inputs, identity, later)
    assert r.period_end == period
    assert r.F01 is None and r.F02 is None and r.F03 is None
    assert "MISSING:net_profit_parent_ytd:" + period in r.missing_reasons


@pytest.mark.parametrize("missing", ["annual_cfo", "prior_q3_profit", "prior_q3_assets"])
def test_missing_real_leg_or_base_assets_remains_missing(real_inputs, missing):
    facts, coverage, cal = real_inputs
    field, end = {"annual_cfo": ("operating_cashflow_ytd", "2022-12-31"),
                  "prior_q3_profit": ("net_profit_parent_ytd", "2022-09-30"),
                  "prior_q3_assets": ("total_assets", "2022-09-30")}[missing]
    facts = facts.loc[~(facts.instrument_id.eq("sz.002857") & facts.period_end.eq(end) & facts.field.eq(field))]
    r = calculate((facts, coverage, cal))
    assert "MISSING:" + field + ":" + end in r.missing_reasons
    if missing == "annual_cfo":
        assert r.F02 is not None and r.F03 is None
    elif missing == "prior_q3_profit":
        assert r.F02 is None and r.F03 is not None
    else:
        assert r.F02 is None and r.F03 is None


@pytest.mark.parametrize("mutation", ["repeated_identity", "branch", "unlinked_correction"])
def test_revision_identity_and_conflicts_rejected(real_inputs, mutation):
    facts, _, cal = real_inputs
    row = facts.loc[facts.instrument_id.eq("sz.002857") & facts.version_basis.eq("CORRECTION_FILING")].iloc[0].to_dict()
    if mutation != "repeated_identity":
        row["revision_id"] = "INVENTED_CONFLICT_TEST_ONLY"
        row["available_at"] = "2024-12-27T21:00:00+08:00"
    if mutation == "unlinked_correction":
        row["supersedes_id"] = "MISSING_PARENT"
    row["value"] = "123"
    with pytest.raises(DataValidationError):
        financial_asof(pd.concat([facts, pd.DataFrame([row])], ignore_index=True), "2024-12-30T21:00:00+08:00", cal)


def invented_cap(**changes):
    row = dict(instrument_id="sz.002857", date="2023-10-27", available_at="2023-10-27T21:00:00+08:00",
        market_cap=1000000000., market_cap_scope="TOTAL_EQUITY", share_class_consistent=True,
        price_share_class="A_ORDINARY", capital_share_class="A_ORDINARY", price_source_sha256="a"*64,
        shares_source_sha256="b"*64, provenance="INVENTED_MARKET_CAP_TEST_ONLY")
    row.update(changes)
    return pd.DataFrame([row])


@pytest.mark.parametrize("changes,reason", [
    ({"date": "2023-10-26"}, "NO_VISIBLE_SAME_DAY_MARKET_CAP"),
    ({"available_at": "2023-10-30T21:00:00+08:00"}, "NO_VISIBLE_SAME_DAY_MARKET_CAP"),
    ({"market_cap_scope": "FLOAT"}, "INVALID_TOTAL_EQUITY_MARKET_CAP"),
    ({"capital_share_class": "A_PLUS_H"}, "UNVERIFIED_MARKET_CAP_SHARE_CLASS"),
    ({"shares_source_sha256": ""}, "UNVERIFIED_MARKET_CAP_SHARE_CLASS")])
def test_invented_market_cap_failure_is_independent_of_real_f02_f03(real_inputs, changes, reason):
    r = calculate(real_inputs, market=invented_cap(**changes))
    assert r.F01 is None and r.F02 is not None and r.F03 is not None
    assert reason in r.missing_reasons


def test_invented_negative_ttm_stays_negative_and_valid_does_not_admit(real_inputs):
    facts, coverage, cal = real_inputs
    facts = facts.copy()
    facts.loc[facts.instrument_id.eq("sz.002857") & facts.field.eq("net_profit_parent_ytd"), "value"] = "-100"
    r = calculate((facts, coverage, cal), market=invented_cap())
    assert r.F01 < 0 and r.F02 < 0 and r.all_three_valid
    assert not r.formal_eligible and r.freshness_policy is None
    assert "LATEST_REPORT_COVERAGE_UNVERIFIED" in r.formal_blockers


def test_date_only_2024_published_but_2025_available_never_changes_2024(real_inputs):
    facts, coverage, cal = real_inputs
    row = facts.iloc[0].to_dict()
    row.update(revision_id="INVENTED_BOUNDARY_TEST_ONLY", supersedes_id=row["revision_id"],
               version_basis="CORRECTION_FILING", value="999999", published_at="2024-12-31T00:00:00+08:00",
               available_at="2025-01-02T21:00:00+08:00")
    future = pd.concat([facts, pd.DataFrame([row])], ignore_index=True)
    pd.testing.assert_frame_equal(financial_asof(facts, "2024-12-31T21:00:00+08:00", cal),
                                  financial_asof(future, "2024-12-31T21:00:00+08:00", cal))


def test_coverage_contract_cannot_omit_visible_later_period_or_drift_cutoff(real_inputs):
    facts, coverage, cal = real_inputs
    coverage = coverage.copy()
    index = coverage.index[(coverage.instrument_id == "sh.600518") & coverage["asof"].str.startswith("2019")][0]
    coverage.loc[index, "latest_visible_period"] = "2017-12-31"
    with pytest.raises(DataValidationError, match="omits a later"):
        calculate((facts, coverage, cal), "sh.600518", "2019-05-06T21:00:00+08:00")
    with pytest.raises(DataValidationError, match="exact factor cutoff"):
        r2_factors(facts, empty_market(), "2023-10-30T21:00:00+08:00", cal, ["sz.002857"],
                   report_coverage=coverage.loc[coverage.instrument_id.eq("sz.002857")].iloc[[0]])
