"""R2/R3 research kernels; these functions do not admit data or run accounts.

Original-document provenance is a required input, not proof that a provider's
history is point in time. The real runner remains closed to stock strategies
until separate data and execution reviews admit their complete dependencies.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable

import numpy as np
import pandas as pd

from .data import DataValidationError, asof_records, date_only_available_at


FIELDS = ("net_profit_parent_ytd", "operating_cashflow_ytd", "total_assets")
FACT_KEYS = ["instrument_id", "field", "period_end", "report_scope", "currency"]
M10_VALUATION_CONVENTION = "A_PRICE_ALL_ISSUED_ORDINARY_SHARES_V1"


def _at(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise DataValidationError("An explicit decision timezone is required")
    stamp = stamp.tz_convert("Asia/Shanghai")
    if stamp >= pd.Timestamp("2025-01-01", tz="Asia/Shanghai"):
        raise DataValidationError("Final holdout remains locked")
    return stamp


def _signal_at(value, anchor=None):
    at = _at(value)
    if at != at.normalize() + pd.Timedelta(hours=21) or (anchor is not None and at.date().isoformat() != anchor):
        raise DataValidationError("Stock research kernels require the registered anchor-day 21:00 cutoff")
    return at


def financial_asof(facts: pd.DataFrame, cutoff, calendar: Iterable[str]):
    """Validate visible original/correction facts and select visible revisions.

    Facts are long-form, consolidated CNY amounts, including original YTD
    flows. Each correction points to its predecessor for the same fact key.
    Comparison-period restatements are independent facts with their actual
    later publication clock, never updates to the old record in place.
    """
    at = _at(cutoff)
    required = set(FACT_KEYS + ["value", "revision_id", "supersedes_id", "available_at",
                               "published_at", "publication_precision", "version_basis",
                               "source_document_hash"])
    if required - set(facts):
        raise DataValidationError("Missing financial provenance fields: " + str(sorted(required - set(facts))))
    if not facts.available_at.astype(str).str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
        raise DataValidationError("Financial availability requires explicit timezone")
    clocks = pd.to_datetime(facts.available_at, utc=True, format="mixed", errors="raise")
    visible = facts.loc[clocks <= at.tz_convert("UTC")].copy()
    if visible.duplicated(FACT_KEYS + ["revision_id"]).any():
        raise DataValidationError("Repeated financial revision identity; do not silently deduplicate")
    for column in FACT_KEYS + ["revision_id"]:
        if visible[column].isna().any() or visible[column].astype(str).eq("").any():
            raise DataValidationError("Nonempty financial economic and revision keys required")
    for key, group in visible.groupby(FACT_KEYS, dropna=False, sort=False):
        if group.revision_id.isna().any() or group.revision_id.astype(str).eq("").any():
            raise DataValidationError("Financial revision identity required")
        versions = group.set_index("revision_id", drop=False)
        if versions.index.duplicated().any():
            raise DataValidationError("Repeated financial revision identity")
        ordered = group.assign(_clock=pd.to_datetime(group.available_at, utc=True)).sort_values("_clock")
        previous = None
        previous_publication = None
        previous_precision = None
        for row in ordered.to_dict("records"):
            if row["field"] not in FIELDS or row["report_scope"] != "consolidated" or row["currency"] != "CNY":
                raise DataValidationError("Unsupported financial field, scope or currency")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row["period_end"])):
                raise DataValidationError("period_end requires canonical YYYY-MM-DD")
            period = pd.Timestamp(row["period_end"])
            if period.strftime("%m-%d") not in ("03-31", "06-30", "09-30", "12-31") or period.date() > at.date():
                raise DataValidationError("Invalid quarterly period_end")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row["source_document_hash"])):
                raise DataValidationError("Original source document hash required")
            if row["version_basis"] not in ("ORIGINAL_FILING", "CORRECTION_FILING"):
                raise DataValidationError("Latest/revised provider history is not original filing history")
            available, published = pd.Timestamp(row["available_at"]), pd.Timestamp(row["published_at"])
            if published.tzinfo is None or pd.isna(published) or published.date() < period.date():
                raise DataValidationError("Invalid original publication clock")
            precision = row["publication_precision"]
            if precision == "date_only":
                lower = pd.Timestamp(date_only_available_at(published.tz_convert("Asia/Shanghai").date().isoformat(), calendar))
            elif precision in ("second", "minute"):
                lower = published
            else:
                raise DataValidationError("Unknown financial publication precision")
            if available < lower:
                raise DataValidationError("Financial availability precedes its conservative publication clock")
            supersedes = row["supersedes_id"]
            has_parent = pd.notna(supersedes) and supersedes != ""
            if previous is None:
                if has_parent or row["version_basis"] != "ORIGINAL_FILING":
                    raise DataValidationError("Original financial version missing")
            elif not has_parent or supersedes != previous or row["version_basis"] != "CORRECTION_FILING":
                raise DataValidationError("Incomplete or branching financial revision chain")
            if previous_publication is not None:
                if "date_only" in (precision, previous_precision):
                    reversed_publication = published.tz_convert("Asia/Shanghai").date() < previous_publication.tz_convert("Asia/Shanghai").date()
                else:
                    reversed_publication = published < previous_publication
                if reversed_publication:
                    raise DataValidationError("Correction publication precedes its original version")
            previous = row["revision_id"]
            previous_publication, previous_precision = published, precision
    return asof_records(visible, at, FACT_KEYS)


def _m10_valuation_cap(row, at, calendar):
    """Validate a supplied M10 observation, not its external authenticity.

    All quantities are canonical shares and CNY. Source payload hashes are
    not official filing hashes. Collection time may be after the historical
    cutoff; publication and availability may not. No provider adapter or
    financial/data admission is implied by this arithmetic contract.
    """
    def reject(reason):
        raise DataValidationError("INVALID_M10_VALUATION:" + reason)

    def number(key, integral=False):
        value = row.get(key)
        if isinstance(value, (bool, np.bool_)):
            reject(key)
        try:
            result = Decimal(str(value))
            if not result.is_finite() or result <= 0 or (integral and result != result.to_integral_value()):
                reject(key)
        except (InvalidOperation, ValueError, TypeError):
            reject(key)
        return result

    def stamp(key):
        try:
            result = pd.Timestamp(row.get(key))
            if pd.isna(result) or result.tzinfo is None:
                reject(key)
        except (TypeError, ValueError):
            reject(key)
        return result

    if (row.get("market_cap_scope") != "A_PRICE_ALL_ISSUED_ORDINARY_PROXY"
            or row.get("valuation_convention") != M10_VALUATION_CONVENTION
            or row.get("price_share_class") != "A_ORDINARY"
            or row.get("price_adjustment") != "UNADJUSTED"
            or row.get("price_currency") != "CNY"
            or row.get("shares_unit") != "SHARES"
            or row.get("ordinary_share_scope") != "ALL_ISSUED_ORDINARY_A_B_H_EX_PREFERRED"
            or row.get("ordinary_share_scope_verified") is not True
            or row.get("preferred_shares_excluded") is not True
            or row.get("treasury_share_treatment") not in ("INCLUDED_IF_ISSUED", "NO_TREASURY_SHARES")):
        reject("SCOPE_UNITS_OR_SEMANTICS")
    if row.get("price_date") != at.date().isoformat():
        reject("PRICE_DATE")
    for source in ("price", "shares"):
        mapping = row.get(source + "_source_field")
        if not isinstance(mapping, str) or not mapping.strip():
            reject(source + "_SOURCE_FIELD")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(source + "_source_sha256", ""))):
            reject(source + "_SOURCE_HASH")
        published = stamp(source + "_published_at")
        available = stamp(source + "_available_at")
        retrieved = stamp(source + "_retrieved_at")
        precision = row.get(source + "_publication_precision")
        if precision == "date_only":
            lower = pd.Timestamp(date_only_available_at(published.tz_convert("Asia/Shanghai").date().isoformat(), calendar))
        elif precision in ("second", "minute"):
            lower = published
        else:
            reject(source + "_PUBLICATION_PRECISION")
        if available < lower or available > at or retrieved < published or available > stamp("available_at"):
            reject(source + "_CLOCK")
    price_published = stamp("price_published_at").tz_convert("Asia/Shanghai")
    if price_published < at.normalize() + pd.Timedelta(hours=15):
        reject("CLOSE_BEFORE_SESSION_CLOSE")
    if stamp("shares_effective_at") > at:
        reject("SHARES_NOT_EFFECTIVE")
    price = number("unadjusted_A_close")
    a_shares = number("a_shares", integral=True)
    ordinary = number("total_ordinary_shares", integral=True)
    if a_shares > ordinary:
        reject("A_EXCEEDS_ALL_ORDINARY")
    computed = price * ordinary
    if computed != number("market_cap"):
        reject("SUPPLIED_CAP_DIFFERS_FROM_PRICE_TIMES_ORDINARY_SHARES")
    if not math.isfinite(float(computed)) or float(computed) <= 0:
        reject("NONFINITE_CAP")
    return float(computed)


def r2_factors(facts: pd.DataFrame, market: pd.DataFrame, cutoff, calendar: Iterable[str],
               universe_ids: Iterable[str], *, report_coverage: pd.DataFrame = None,
               valuation_convention="LEGACY_TOTAL_EQUITY"):
    """Compute F01-F03 without filling a missing vintage or a bad denominator.

    Legacy `market` supplies same-date, audited total-equity capitalization.
    Explicit M10 mode instead validates A-price times all issued ordinary
    shares, including A/B/H, excluding preferred shares, with separate
    source/clock/units fields. Neither mode grants source authenticity.
    The stock-pool gate, historical shares/share-class consistency and source
    authenticity are separate admission responsibilities. Optional report_coverage
    binds an issuer's latest visible report period to this exact cutoff, including
    reports whose facts have not been transcribed. It requires instrument_id,
    asof, latest_visible_period, coverage_status and evidence_sha256. PARTIAL
    coverage can establish a newer known report, but cannot prove completeness.
    Without a registered freshness policy these outputs never grant admission.
    """
    if valuation_convention not in ("LEGACY_TOTAL_EQUITY", M10_VALUATION_CONVENTION):
        raise DataValidationError("Unregistered valuation convention")
    at = _signal_at(cutoff)
    visible = financial_asof(facts, at, calendar)
    needed = {"instrument_id", "date", "available_at", "market_cap", "market_cap_scope"}
    if needed - set(market):
        raise DataValidationError("Missing dated market capitalization inputs")
    current = asof_records(market, at, ["instrument_id", "date"])
    current = current.loc[current.date.eq(at.date().isoformat())]
    if current.instrument_id.duplicated().any():
        raise DataValidationError("Ambiguous market capitalization")
    expected = list(universe_ids)
    if len(set(expected)) != len(expected) or any(not isinstance(i, str) or not i for i in expected):
        raise DataValidationError("Explicit unique historical universe identities required")
    capitals = {row["instrument_id"]: row for row in current.to_dict("records")}
    coverage = {}
    if report_coverage is not None:
        required = {"instrument_id", "asof", "latest_visible_period", "coverage_status", "evidence_sha256"}
        if required - set(report_coverage) or report_coverage.instrument_id.duplicated().any():
            raise DataValidationError("Unique latest-report coverage contract required")
        for item in report_coverage.to_dict("records"):
            if _at(item["asof"]) != at:
                raise DataValidationError("Latest-report coverage must bind the exact factor cutoff")
            end = str(item["latest_visible_period"])
            if not re.fullmatch(r"\d{4}-(?:03-31|06-30|09-30|12-31)", end) or pd.Timestamp(end).date() > at.date():
                raise DataValidationError("Invalid latest visible report period")
            if item["coverage_status"] not in ("PARTIAL", "COMPLETE_THROUGH_CUTOFF"):
                raise DataValidationError("Unknown report coverage status")
            if not re.fullmatch(r"[0-9a-f]{64}", str(item["evidence_sha256"])):
                raise DataValidationError("Latest-report coverage evidence hash required")
            coverage[item["instrument_id"]] = item
    output = []
    for identity in expected:
        cap = capitals.get(identity)
        rows = visible.loc[visible.instrument_id.eq(identity)]
        record = {"instrument_id": identity, "asof": at.isoformat(), "F01": None, "F02": None,
                  "F03": None, "period_end": None, "input_revision_ids": [], "missing_reasons": [],
                  "all_three_valid": False, "report_coverage_status": "UNVERIFIED",
                  "latest_period_status": "UNVERIFIED",
                  "freshness_status": "UNASSESSED_NO_REGISTERED_POLICY", "freshness_policy": None,
                  "report_age_days": None, "formal_eligible": False,
                  "formal_blockers": ["KERNEL_NOT_DATA_ADMISSION", "FRESHNESS_POLICY_UNREGISTERED"]}
        if valuation_convention == M10_VALUATION_CONVENTION:
            record.update(valuation_convention=valuation_convention, valuation_cap=None)
        contract = coverage.get(identity)
        if contract is not None:
            record["report_coverage_status"] = contract["coverage_status"]
            if contract["coverage_status"] == "COMPLETE_THROUGH_CUTOFF":
                record["latest_period_status"] = "VERIFIED_BY_INPUT_CONTRACT"
        if contract is None or contract["coverage_status"] != "COMPLETE_THROUGH_CUTOFF":
            record["formal_blockers"].append("LATEST_REPORT_COVERAGE_UNVERIFIED")
        if cap is None:
            record["missing_reasons"].append("NO_VISIBLE_SAME_DAY_MARKET_CAP")
        if rows.empty and contract is None:
            record["missing_reasons"].append("NO_VISIBLE_ORIGINAL_FINANCIALS")
            output.append(record)
            continue
        period = contract["latest_visible_period"] if contract is not None else rows.period_end.max()
        if not rows.empty and rows.period_end.max() > period:
            raise DataValidationError("Coverage contract omits a later visible financial report")
        record["period_end"] = period
        record["report_age_days"] = (at.date() - pd.Timestamp(period).date()).days
        year, suffix = int(period[:4]), period[4:]
        lookup = {(r["field"], r["period_end"]): r for r in rows.to_dict("records")}
        def value(field, end):
            item = lookup.get((field, end))
            if item is None or pd.isna(item["value"]) or not math.isfinite(float(item["value"])):
                record["missing_reasons"].append("MISSING:" + field + ":" + end)
                return None
            record["input_revision_ids"].append({"field": field, "period_end": end,
                "revision_id": item["revision_id"], "source_document_hash": item["source_document_hash"]})
            return float(item["value"])
        def ttm(field):
            ends = [period] if suffix == "-12-31" else [period, str(year - 1) + "-12-31", str(year - 1) + suffix]
            values = [value(field, end) for end in ends]
            if any(v is None for v in values):
                return None
            return values[0] if len(values) == 1 else values[0] + values[1] - values[2]
        profit, cashflow = ttm(FIELDS[0]), ttm(FIELDS[1])
        assets = [value("total_assets", end) for end in (period, str(year - 1) + suffix)]
        average = sum(assets) / 2 if all(v is not None and v > 0 for v in assets) else None
        if average is None:
            record["missing_reasons"].append("INVALID_AVERAGE_ASSETS")
        capitalization = cap["market_cap"] if cap is not None else None
        m10_cap = None
        if valuation_convention == M10_VALUATION_CONVENTION:
            if cap is not None:
                try:
                    m10_cap = _m10_valuation_cap(cap, at, calendar)
                    record["valuation_cap"] = m10_cap
                except DataValidationError as exc:
                    record["missing_reasons"].append(str(exc))
        if cap is None:
            pass
        elif valuation_convention == M10_VALUATION_CONVENTION:
            if m10_cap is not None and profit is not None:
                record["F01"] = profit / m10_cap
        elif cap["market_cap_scope"] != "TOTAL_EQUITY" or pd.isna(capitalization) or not math.isfinite(float(capitalization)) or capitalization <= 0:
            record["missing_reasons"].append("INVALID_TOTAL_EQUITY_MARKET_CAP")
        elif (report_coverage is not None or "share_class_consistent" in cap) and not (
            cap.get("share_class_consistent") is True
            and cap.get("price_share_class") == cap.get("capital_share_class") == "A_ORDINARY"
            and re.fullmatch(r"[0-9a-f]{64}", str(cap.get("price_source_sha256", "")))
            and re.fullmatch(r"[0-9a-f]{64}", str(cap.get("shares_source_sha256", "")))
        ):
            record["missing_reasons"].append("UNVERIFIED_MARKET_CAP_SHARE_CLASS")
        elif profit is not None:
            record["F01"] = profit / capitalization  # Negative earnings remain negative.
        if average is not None:
            record["F02"] = profit / average if profit is not None else None
            record["F03"] = cashflow / average if cashflow is not None else None
        record["all_three_valid"] = all(record[k] is not None for k in ("F01", "F02", "F03"))
        output.append(record)
    return pd.DataFrame(output)


def r2_scores(eligible: pd.DataFrame, neutralization="industry_size"):
    """Fixed three-factor rules on an already admitted same-date common pool.

    Small groups use a known parent when all resulting groups have >=10 rows;
    otherwise use the declared whole-pool fallback for the entire cross-section
    and report it. Missing inputs are errors, not silent universe deletions.
    """
    if neutralization not in ("raw", "industry", "industry_size"):
        raise ValueError("Unregistered R2 normalization")
    result = eligible.copy()
    required = {"instrument_id", "industry", "market_cap", "F01", "F02", "F03"}
    if required - set(result) or result.empty or result.instrument_id.duplicated().any():
        raise DataValidationError("Unique, nonempty R2 common pool required")
    if result.industry.isna().any() or result.industry.astype(str).eq("").any():
        raise DataValidationError("Historical industry cannot be imputed from current membership")
    values = result[["F01", "F02", "F03", "market_cap"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 3] <= 0).any():
        raise DataValidationError("All three factors and positive market caps must be valid")
    groups = result.industry.astype(str)
    fallback = "NONE"
    if groups.map(groups.value_counts()).lt(10).any():
        parent = result.get("industry_parent")
        if parent is not None and parent.notna().all() and parent.astype(str).ne("").all() and parent.map(parent.value_counts()).ge(10).all():
            groups, fallback = parent.astype(str), "KNOWN_PARENT"
        else:
            groups, fallback = pd.Series("GLOBAL", index=result.index), "WHOLE_POOL"
    def zscore(array):
        scale = np.std(array, ddof=0)
        # Numerically zero regression residuals must not become arbitrary ranks.
        return np.zeros(len(array)) if scale <= 1e-12 else (array - np.mean(array)) / scale
    design = np.ones((len(result), 1))
    if neutralization != "raw":
        dummies = pd.get_dummies(groups, drop_first=True, dtype=float).to_numpy()
        design = np.column_stack((design, dummies))
        if neutralization == "industry_size":
            design = np.column_stack((design, np.log(values[:, 3])))
    for column in ("F01", "F02", "F03"):
        raw = result[column].to_numpy(dtype=float)
        normalized = zscore(np.clip(raw, *np.quantile(raw, [.01, .99])))
        if neutralization != "raw":
            normalized = zscore(normalized - design @ np.linalg.lstsq(design, normalized, rcond=None)[0])
        result["z_" + column] = normalized
    result["VALUE"] = result.z_F01
    result["QUALITY"] = .5 * (result.z_F02 + result.z_F03)
    result["COMBINED"] = .5 * result.z_F01 + .25 * result.z_F02 + .25 * result.z_F03
    result["neutralization"] = neutralization
    result["industry_fallback"] = fallback if neutralization != "raw" else "NOT_USED"
    return result


def r2_portfolio(scores: pd.DataFrame, held_ids=(), variant="COMBINED"):
    """Thirty 1/30 targets, rank<=45 retention, at most six per industry.

    Removed holdings become zero targets; actual blocked exits stay in the
    execution ledger. This does not liquidate positions or release their cash.
    """
    if variant not in ("VALUE", "QUALITY", "COMBINED"):
        raise ValueError("Unregistered R2 rule")
    required = {"instrument_id", "industry", variant}
    if required - set(scores) or scores.instrument_id.duplicated().any():
        raise DataValidationError("Unique scored pool required")
    if not np.isfinite(scores[variant].to_numpy(dtype=float)).all() or scores.industry.isna().any():
        raise DataValidationError("Finite scores and historical industry required")
    ranked = scores.sort_values([variant, "instrument_id"], ascending=[False, True]).copy()
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    held = set(held_ids)
    records = ranked.to_dict("records")
    retained = [r for r in records if r["instrument_id"] in held and r["rank"] <= 45]
    selected, counts = [], {}
    for row in retained + [r for r in records if r["instrument_id"] not in held]:
        identity, industry = row["instrument_id"], row["industry"]
        if identity in selected or counts.get(industry, 0) >= 6 or len(selected) >= 30:
            continue
        selected.append(identity)
        counts[industry] = counts.get(industry, 0) + 1
    return {"weights": {i: 1 / 30 for i in selected}, "cash_target": 1 - len(selected) / 30,
            "ranks": dict(zip(ranked.instrument_id, ranked["rank"])), "industry_counts": counts,
            "held_zero_targets": sorted(held - set(selected))}


def r3_reversal(observations: pd.DataFrame, calendar: list[str], anchor: str,
                lookback=5, model="market", decision_at=None):
    """Literal registered training/signal windows; never refit on signal days.

    One instrument's dated returns with a shared audited market/industry
    series. Historical industry for portfolio quotas is required even when
    this signal uses the market-only model. No stock universe is admitted here.
    """
    if lookback not in (3, 5, 10) or model not in ("raw", "market", "market_industry"):
        raise ValueError("Unregistered reversal specification")
    at = _signal_at(decision_at or (anchor + "T21:00:00+08:00"), anchor)
    if anchor > at.date().isoformat() or anchor >= "2025-01-01":
        raise DataValidationError("Signal anchor is not available or holdout is locked")
    if calendar != sorted(set(calendar)) or any(day >= "2025-01-01" for day in calendar):
        raise DataValidationError("Unique chronological pre-holdout calendar required")
    t = calendar.index(anchor)
    if t - lookback - 252 < 0:
        raise DataValidationError("R3 requires its entire registered calendar window")
    train_dates = calendar[t - lookback - 252:t - lookback]
    signal_dates = calendar[t - lookback + 1:t + 1]
    frame = asof_records(observations, at, ["date"]).set_index("date")
    columns = ["stock_return", "market_return"]
    if model == "market_industry":
        columns.append("industry_return")
    if set(columns) - set(frame):
        raise DataValidationError("Required return series missing")
    train = frame.reindex(train_dates)[columns].replace([np.inf, -np.inf], np.nan).dropna()
    signal = frame.reindex(signal_dates)[columns]
    if len(train) < 200 or not np.isfinite(signal.to_numpy(dtype=float)).all():
        raise DataValidationError("Insufficient known training or signal returns")
    def matrix(data, use_industry):
        parts = [np.ones(len(data)), data.market_return.to_numpy()]
        if use_industry:
            parts.append((data.industry_return - data.market_return).to_numpy())
        return np.column_stack(parts)
    fitted_model, coefficients, condition = model, [], None
    if model == "raw":
        score = -float(signal.stock_return.sum())
    else:
        design = matrix(train, model == "market_industry")
        condition = float(np.linalg.cond(design))
        if np.linalg.matrix_rank(design) < design.shape[1] or condition > 1e6:
            if model != "market_industry":
                raise DataValidationError("Market regression itself is not identifiable")
            fitted_model = "market_fallback"
            design = matrix(train, False)
            condition = float(np.linalg.cond(design))
            if np.linalg.matrix_rank(design) < 2 or condition > 1e6:
                raise DataValidationError("Market fallback is not identifiable")
        coefficients = np.linalg.lstsq(design, train.stock_return.to_numpy(), rcond=None)[0].tolist()
        expected = matrix(signal, fitted_model == "market_industry") @ np.asarray(coefficients)
        score = -float(np.sum(signal.stock_return.to_numpy() - expected))
    return {"score": score, "model_requested": model, "model_used": fitted_model,
            "coefficients": coefficients, "condition_number": condition, "training_observations": len(train),
            "training_start": train_dates[0], "training_end": train_dates[-1],
            "signal_start": signal_dates[0], "signal_end": signal_dates[-1],
            "asof": at.isoformat(), "status": "RESEARCH_KERNEL_ONLY_NOT_DATA_ADMISSION"}
