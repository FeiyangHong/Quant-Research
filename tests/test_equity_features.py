"""Invented examples only: no stock-performance evidence or data admission."""
import numpy as np
import pandas as pd
import pytest

from quant_research.data import DataValidationError
from quant_research.equity_features import financial_asof, r2_factors, r2_scores, r2_portfolio, r3_reversal


@pytest.fixture
def financial_fixture():
    calendar = pd.bdate_range("2019-01-01", "2024-12-31").strftime("%Y-%m-%d").tolist()
    rows = []
    fields = ("net_profit_parent_ytd", "operating_cashflow_ytd", "total_assets")
    for period, amounts, pub, available in (
        ("2019-09-30", (60., 70., 900.), "2019-10-30", "2019-10-31"),
        ("2019-12-31", (100., 120., 1000.), "2020-04-29", "2020-04-30"),
        ("2020-09-30", (70., 90., 1100.), "2020-10-29", "2020-10-30"),
    ):
        for field, value in zip(fields, amounts):
            rows.append(dict(instrument_id="INVENTED_A", field=field, period_end=period, value=value,
                report_scope="consolidated", currency="CNY", revision_id=period + ":" + field + ":v1",
                supersedes_id=None, available_at=available + "T21:00:00+08:00",
                published_at=pub + "T00:00:00+08:00", publication_precision="date_only",
                version_basis="ORIGINAL_FILING", source_document_hash="a" * 64))
    facts = pd.DataFrame(rows)
    market = pd.DataFrame([dict(instrument_id="INVENTED_A", date="2020-11-02",
        available_at="2020-11-02T21:00:00+08:00", market_cap=1000., market_cap_scope="TOTAL_EQUITY")])
    return facts, market, calendar


def factors(fixture, **kwargs):
    facts, market, calendar = fixture
    return r2_factors(facts, market, "2020-11-02T21:00:00+08:00", calendar,
                      kwargs.get("universe_ids", ["INVENTED_A"]))


def test_ttm_uses_each_visible_leg_and_records_original_identities(financial_fixture):
    result = factors(financial_fixture).iloc[0]
    assert (result.F01, result.F02, result.F03) == pytest.approx((.11, .11, .14))
    assert result.all_three_valid
    assert result.period_end == "2020-09-30"
    assert len(result.input_revision_ids) == 8
    assert result.missing_reasons == []


def test_later_comparison_restatement_does_not_change_old_features(financial_fixture):
    facts, market, calendar = financial_fixture
    old = factors(financial_fixture)
    correction = facts.loc[facts.field.eq("net_profit_parent_ytd") & facts.period_end.eq("2019-12-31")].iloc[0].to_dict()
    correction.update(value=200., supersedes_id=correction["revision_id"], revision_id="CORRECTION_2021",
        available_at="2021-04-02T21:00:00+08:00", published_at="2021-04-01T00:00:00+08:00",
        version_basis="CORRECTION_FILING", source_document_hash="b" * 64)
    extended = pd.concat([facts, pd.DataFrame([correction])], ignore_index=True)
    pd.testing.assert_frame_equal(old, factors((extended, market, calendar)))
    later_market = market.assign(date="2021-04-02", available_at="2021-04-02T21:00:00+08:00")
    later = r2_factors(extended, later_market, "2021-04-02T21:00:00+08:00", calendar, ["INVENTED_A"]).iloc[0]
    assert later.F01 == pytest.approx(.21)
    assert "CORRECTION_2021" in {r["revision_id"] for r in later.input_revision_ids}


@pytest.mark.parametrize("mutation", ["duplicate_identity", "missing_original", "latest_provider", "date_clock", "noncanonical_period"])
def test_bad_financial_vintage_or_clock_is_rejected(financial_fixture, mutation):
    facts, _, calendar = financial_fixture
    facts = facts.copy(deep=True)
    if mutation == "duplicate_identity":
        row = facts.iloc[0].to_dict()
        row.update(available_at="2020-11-02T21:00:00+08:00", value=900.)
        facts = pd.concat([facts, pd.DataFrame([row])], ignore_index=True)
    elif mutation == "missing_original":
        facts.loc[0, ["version_basis", "supersedes_id"]] = ["CORRECTION_FILING", "missing_parent"]
    elif mutation == "latest_provider":
        facts.loc[0, "version_basis"] = "LATEST_REVISED_PROVIDER"
    elif mutation == "date_clock":
        facts.loc[0, "available_at"] = "2019-10-30T21:00:00+08:00"
    else:
        facts.loc[0, "period_end"] = "2019-9-30"
    with pytest.raises(DataValidationError):
        financial_asof(facts, "2020-11-02T21:00:00+08:00", calendar)


def test_missing_market_and_financials_preserve_requested_identities(financial_fixture):
    facts, market, calendar = financial_fixture
    market = market.assign(available_at="2020-11-03T21:00:00+08:00")
    result = factors((facts, market, calendar), universe_ids=["INVENTED_A", "INVENTED_DEAD"])
    assert result.instrument_id.tolist() == ["INVENTED_A", "INVENTED_DEAD"]
    assert not result.all_three_valid.any()
    assert "NO_VISIBLE_SAME_DAY_MARKET_CAP" in result.iloc[0].missing_reasons
    assert "NO_VISIBLE_ORIGINAL_FINANCIALS" in result.iloc[1].missing_reasons
    assert result.iloc[0].F02 == pytest.approx(.11)


def test_correction_cannot_be_published_before_its_predecessor(financial_fixture):
    facts, _, calendar = financial_fixture
    original = facts.iloc[[0]].copy()
    correction = original.iloc[0].to_dict()
    correction.update(revision_id="REVERSED_PUBLICATION", supersedes_id=correction["revision_id"],
        published_at="2019-10-29T18:00:00+08:00", publication_precision="second",
        available_at="2019-11-04T21:00:00+08:00", version_basis="CORRECTION_FILING", value=999.)
    with pytest.raises(DataValidationError, match="publication precedes"):
        financial_asof(pd.concat([original, pd.DataFrame([correction])], ignore_index=True),
                       "2020-11-02T21:00:00+08:00", calendar)
    # A date-only publication gives no evidence of intraday order on the same day.
    correction["published_at"] = "2019-10-30T18:00:00+08:00"
    assert financial_asof(pd.concat([original, pd.DataFrame([correction])], ignore_index=True),
                         "2020-11-02T21:00:00+08:00", calendar).iloc[0].value == 999.


def test_missing_ttm_leg_and_bad_assets_are_not_filled(financial_fixture):
    facts, market, calendar = financial_fixture
    facts = facts.loc[~(facts.field.eq("operating_cashflow_ytd") & facts.period_end.eq("2019-12-31"))].copy()
    facts.loc[facts.field.eq("total_assets") & facts.period_end.eq("2019-09-30"), "value"] = -1.
    row = factors((facts, market, calendar)).iloc[0]
    assert row.F01 == pytest.approx(.11)
    assert row.F02 is None and row.F03 is None and not row.all_three_valid
    assert "INVALID_AVERAGE_ASSETS" in row.missing_reasons


def test_negative_profit_is_negative_earnings_yield(financial_fixture):
    facts, market, calendar = financial_fixture
    facts = facts.copy()
    facts.loc[facts.field.eq("net_profit_parent_ytd"), "value"] *= -1
    assert factors((facts, market, calendar)).iloc[0].F01 == pytest.approx(-.11)


def test_signals_cannot_use_after_cutoff_or_final_holdout(financial_fixture):
    facts, market, calendar = financial_fixture
    for cutoff in ("2020-11-02T22:00:00+08:00", "2025-01-02T21:00:00+08:00"):
        with pytest.raises(DataValidationError):
            r2_factors(facts, market, cutoff, calendar, ["INVENTED_A"])


def score_fixture():
    rng = np.random.default_rng(37)
    n = 60
    return pd.DataFrame({"instrument_id": [f"INVENTED_{i:03}" for i in range(n)],
        "industry": ["SECTOR_" + str(i // 12) for i in range(n)],
        "market_cap": np.exp(rng.normal(10, 1, n)), "F01": rng.normal(0, 1, n),
        "F02": rng.normal(0, 1, n), "F03": rng.normal(0, 1, n)})


def test_neutral_residuals_are_orthogonal_and_fixed_weights_are_used():
    frame = score_fixture()
    scored = r2_scores(frame)
    design = np.column_stack((np.ones(len(frame)), pd.get_dummies(frame.industry, drop_first=True), np.log(frame.market_cap)))
    for field in ("z_F01", "z_F02", "z_F03"):
        assert np.max(np.abs(design.T @ scored[field])) < 1e-9
        assert np.std(scored[field], ddof=0) == pytest.approx(1.)
    np.testing.assert_allclose(scored.COMBINED, .5 * scored.z_F01 + .25 * scored.z_F02 + .25 * scored.z_F03)
    shuffled = r2_scores(frame.sample(frac=1, random_state=5)).set_index("instrument_id")
    np.testing.assert_allclose(scored.set_index("instrument_id").COMBINED.sort_index(), shuffled.COMBINED.sort_index(), atol=1e-12)


def test_small_industry_fallback_is_explicit_and_missing_inputs_do_not_shrink_pool():
    frame = score_fixture()
    frame.loc[0, "industry"] = "SMALL"
    scored = r2_scores(frame)
    assert len(scored) == 60 and scored.industry_fallback.eq("WHOLE_POOL").all()
    frame["industry_parent"] = "KNOWN_PARENT"
    assert r2_scores(frame).industry_fallback.eq("KNOWN_PARENT").all()
    frame.loc[0, "F01"] = np.nan
    with pytest.raises(DataValidationError):
        r2_scores(frame)


def test_zero_residual_does_not_create_arbitrary_factor_ranks():
    frame = score_fixture()
    frame[["F01", "F02", "F03"]] = 1.
    assert r2_scores(frame).COMBINED.eq(0).all()


def test_buffer_keeps_eligible_old_rank35_and_caps_each_industry():
    frame = score_fixture()
    frame["COMBINED"] = -np.arange(len(frame))
    portfolio = r2_portfolio(frame, held_ids=["INVENTED_034"])
    assert len(portfolio["weights"]) == 30
    assert "INVENTED_034" in portfolio["weights"]
    assert max(portfolio["industry_counts"].values()) <= 6
    assert max(portfolio["weights"].values()) < .05
    assert sum(portfolio["weights"].values()) == pytest.approx(1.)


def test_rank46_old_holding_cannot_be_readded_as_a_new_candidate():
    frame = pd.DataFrame({"instrument_id": [f"INVENTED_{i:03}" for i in range(47)],
                          "industry": ["A"] * 45 + ["B", "B"], "COMBINED": -np.arange(47)})
    portfolio = r2_portfolio(frame, held_ids=["INVENTED_045"])
    assert "INVENTED_045" not in portfolio["weights"]
    assert portfolio["held_zero_targets"] == ["INVENTED_045"]
    assert "INVENTED_046" in portfolio["weights"]
    assert portfolio["cash_target"] == pytest.approx(23 / 30)


@pytest.fixture
def reversal_fixture():
    dates = pd.bdate_range("2019-01-01", periods=350).strftime("%Y-%m-%d").tolist()
    x = np.arange(len(dates))
    market = .01 * np.sin(x * .13)
    spread = .003 * np.cos(x * .31)
    frame = pd.DataFrame({"date": dates, "available_at": [d + "T21:00:00+08:00" for d in dates],
        "market_return": market, "industry_return": market + spread,
        "stock_return": .0003 + 1.2 * market + .7 * spread})
    anchor_index = 320
    frame.loc[anchor_index - 4:anchor_index, "stock_return"] -= .01
    return frame, dates, anchor_index


def test_r3_known_residual_and_literal_nonoverlapping_windows(reversal_fixture):
    frame, calendar, t = reversal_fixture
    answer = r3_reversal(frame, calendar, calendar[t], model="market_industry")
    assert answer["score"] == pytest.approx(.05)
    assert answer["coefficients"] == pytest.approx([.0003, 1.2, .7])
    assert answer["training_start"] == calendar[t - 5 - 252]
    assert answer["training_end"] == calendar[t - 5 - 1]
    assert answer["signal_start"] == calendar[t - 5 + 1]
    altered = frame.copy()
    altered.loc[t - 5, "stock_return"] = 10000.  # Explicit gap day in phase-one formula.
    altered.loc[t + 1:, "stock_return"] = -10000.
    assert r3_reversal(altered, calendar, calendar[t], model="market_industry") == answer


def test_r3_only_rank_deficiency_triggers_market_fallback(reversal_fixture):
    frame, calendar, t = reversal_fixture
    frame = frame.assign(industry_return=frame.market_return, stock_return=.0003 + 1.2 * frame.market_return)
    result = r3_reversal(frame, calendar, calendar[t], model="market_industry")
    assert result["model_used"] == "market_fallback" and result["score"] == pytest.approx(0., abs=1e-12)
    with pytest.raises(DataValidationError, match="Required return series missing"):
        r3_reversal(frame.drop(columns="industry_return"), calendar, calendar[t], model="market_industry")


def test_r3_minimum_training_and_late_signal_are_blockers(reversal_fixture):
    frame, calendar, t = reversal_fixture
    missing = frame.copy()
    missing.loc[t - 5 - 252:t - 5 - 200, "stock_return"] = np.nan  # 53 missing, 199 remain.
    with pytest.raises(DataValidationError, match="Insufficient"):
        r3_reversal(missing, calendar, calendar[t])
    late = frame.copy()
    late.loc[t, "available_at"] = calendar[t] + "T21:01:00+08:00"
    with pytest.raises(DataValidationError, match="Insufficient"):
        r3_reversal(late, calendar, calendar[t])
    with pytest.raises(DataValidationError, match="anchor-day"):
        r3_reversal(frame, calendar, calendar[t], decision_at=calendar[t + 1] + "T21:00:00+08:00")


def test_r3_future_correction_does_not_change_old_score(reversal_fixture):
    frame, calendar, t = reversal_fixture
    original = r3_reversal(frame, calendar, calendar[t])
    correction = frame.iloc[t - 20].to_dict()
    correction.update(stock_return=999., available_at=calendar[t + 1] + "T21:00:00+08:00")
    extended = pd.concat([frame, pd.DataFrame([correction])], ignore_index=True)
    assert r3_reversal(extended, calendar, calendar[t]) == original
