# M10 R2 source contract addendum

Status: **DRAFT_NOT_AUTHORIZED_FOR_REAL_PERFORMANCE**. This resolves the pre-performance research conventions specified by the M10 handoff. It does not certify a source or remove any existing admission condition. [ACCESS_DECISION](ACCESS_DECISION.md) and [COVERAGE_REPORT](COVERAGE_REPORT.md) describe the actual blocking evidence. No data binding exists yet.

## Required scope and source identity

Development is 2016-01-01–2021-12-31; already-observed validation is 2022-01-01–2024-12-31, with separate CNY 100,000 starting accounts. Sufficient earlier lawful history is required for listing age, 60-session liquidity and financial TTM/comparison legs. The periods must not be silently shortened. 2025-and-later market, factor and strategy sequences remain closed; end-2024 trades/labels cannot be matured by looking into that period.

Every actual provider response must retain its own `source_payload_hash`, provider, endpoint, request parameters, explicit historical query cutoff, provider version identity and retrieval time. `filing_document_hash` is populated only for an actual retrieved official filing; otherwise null. Provider response hashes and official-document hashes must never be interchanged. No new provider adapter or `PROVIDER_PIT` admission mode is implemented before a real response proves the necessary semantics. A latest-revised row does not become PIT by relabeling it.

| Dependency | Required fields and clocks | Current unresolved point |
|---|---|---|
| Identity and eligibility | Stable identity, historical symbols/names/boards, listing/exit, ST/risk/suspension/limits; effective/public/available clocks and source evidence | Full history and later exits unproved; current names and daily `isST` are insufficient |
| Raw market and liquidity | Raw OHLC/reference prices, shares traded, CNY turnover, trade status, limits; economic date and actual release/availability precision | One snapshot and short hard-case windows do not supply full history or 21:00 delivery evidence |
| Share capital | A-share count and total issued ordinary count, units, A/B/H mapping, preferred/treasury treatment, issuance/cancellation/conversion events and versions | No complete public/effective event chain; provider field names alone do not prove semantics |
| Industry | One authoritative classification system and version, assignment, effective/public/available dates and conversion history | Quarter/week samples do not establish full assignments or valid version transitions; no scheme chosen from returns |
| Financial facts | Consolidated parent net profit, operating cash flow, total assets; original values/units/CNY, report and comparison periods, original/revision/restatement identity, publication precision and availability | Full filing inventory, missing-latest detection, complete version chains and disclosure/freshness rules unresolved |
| Corporate actions / exits | Announcement, record, ex, pay and share-effective dates; cash/share/rights/tax rules and unsettled entitlement treatment | Complete action/exit chains absent; unknown recovery is not zero; actual broker payment/debit evidence unverified |
| License | Allowed local calculation, storage, automation and derived publication, retention/expiry restrictions | No new adequate source/export license verified; raw bytes remain private |

`effective_at`/`effective_from`, `published_at`, `available_at` and `retrieved_at`/existing `ingested_at` remain separate. A later download proves retrieval only. Where historical vendor first-seen time is unknown it stays null. Historical APIs must receive explicit cutoff dates; default latest queries are disallowed.

## Fixed valuation and financial arithmetic

`valuation_cap(D) = A-share raw closing price(D) × total issued ordinary shares visible at D`.

The ordinary count includes A/B/H ordinary shares and excludes preferred and other nonordinary shares. This is an A-share-reference-price valuation proxy; it is not free-float capitalization or a sum of actual local-market A/H values. A-share count is also retained separately. Treasury-share inclusion/exclusion and vendor `total` units must be proven before mapping. This same cap definition is used by F01, the bottom-30% size exclusion and log-size control. Missing share-class semantics block the dependency; they do not justify deleting A/H issuers or substituting free float.

- F01 = parent net profit TTM / valuation cap.
- F02 = parent net profit TTM / average total assets.
- F03 = operating cash flow TTM / average total assets.
- TTM flows = current-year cumulative + prior full year − prior same-quarter cumulative, all legs using the versions visible at the cutoff.
- Average assets = (latest visible period-end assets + same-quarter assets one year earlier) / 2.

Negative profit is retained. No latest P/E inversion, adjusted-profit substitution, invalid denominator or older-complete-quarter fallback is permitted. Coverage must distinguish no issuer disclosure from a missing provider/parser filing. A newer public filing with missing necessary fields blocks factors. Any age/late-disclosure policy must follow historical obligations and known events; no ad hoc 90/180-day expiry is introduced. The existing null freshness policy is an unresolved technical dependency, not permission for stale inputs.

## Common historical denominator and decision clock

All three arms share the full historical main-board/ChiNext scope and the same factor-valid/industry-valid common pool. The bottom-30% size denominator starts with all then-listed main-board/ChiNext non-ST identities, before financial completeness or convenience filters. Known ineligible facts and unknown mandatory facts have different statuses. Old holdings remain in the account after new-candidate eligibility fails; unknown events, delistings or blocked exits cannot make holdings disappear.

Each month-end must eventually produce the full identity count, every qualification-stage count, unknown reasons, financial-calculable count and final common pool. The one-date 3,779-ID evidence is not authorization to use a survivor sample or repeat that denominator across 108 months.

Default signal cutoff is D at 21:00 Asia/Shanghai; earliest execution is the next legal exchange session. Required inputs must be available by that cutoff. Date-only financial publication is conservatively available at 21:00 on the first exchange session strictly after publication, with execution no earlier than the following session. A later necessary market/share/industry release requires a common minimal fixed delay based on source evidence before any strategy performance; D's economic window remains unchanged. ETF D/D+1/D+2 rules are not inherited without evidence.

## Remaining admission and implementation boundary

The real-source runner remains blocked until full data binding, actual clocks, complete necessary histories, source-backed execution dependencies, independent review and at least 20 human-accepted original/revision cases are satisfied. An agent review or a supplier PIT label is not a human signature. Existing five documentary pairs are preserved; the three conflicted cases remain quarantined and the fixed candidate queue is not replaced with easy survivors.

Raw prices execute trades; signal total-return construction and actual cash/share accounting must separately account for actions without double counting. Historical fees and tax rules use their applicable sources/dates. The M6 Moutai fee blocker and unverified real payment/debit observations are retained, not replaced by synthetic cases. The research remains DAILY_SCREEN_ONLY. No adapter, experiment binding or empty account return is invented to make this incomplete source contract appear runnable.
