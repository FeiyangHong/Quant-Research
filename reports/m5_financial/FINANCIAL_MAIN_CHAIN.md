# M5 two-case financial engineering: admission remains blocked

The fixed Kangmei 2017 annual and Sanhui 2023Q3 cases pass their arithmetic and historical-prefix engineering checks through the existing `financial_asof -> r2_factors` chain. Both have calculable F02/F03. Both F01 values are null: no proven same-day market capitalization with matching share classes was available. No factor case, strategy registration, performance run, or holdout observation was added.

| Fixed case / factor cutoff (Shanghai) | Target report period | NP TTM (CNY) | CFO TTM (CNY) | Average assets (CNY) | F02 | F03 |
|---|---|---:|---:|---:|---:|---:|
| Kangmei 600518 / 2018-04-27 21:00 | 2017-12-31 | 4,100,926,148.57 | 1,842,794,237.84 | 61,772,958,603.71 | 0.06638707682561451 | 0.0298317302504809 |
| Sanhui 002857 / 2023-10-27 21:00 | 2023-09-30 | 6,489,344.12 | 56,271,123.53 | 666,461,874.66 | 0.009737007271887206 | 0.08443262198412638 |

The annual path uses full-year flows and current/prior-year assets. The Q3 path uses current Q3 YTD plus prior FY minus prior Q3 YTD separately for parent net profit and cash flow; assets are current/prior Q3 balance-sheet stocks. Sanhui's actual current Q3 loss of CNY -6,354,889.62 is retained; its resulting TTM profit is positive because of the other two legitimate legs. No absolute value, P/E inversion, or missing-period fallback is used. `factor_cases.json` contains 40-digit Decimal reference expressions and the identities, pages and columns of all inputs; root's non-author review is separately recorded.

## Latest period, availability and freshness

Cutoffs were frozen before new source requests in `registration.json`; actual registration timestamp is system-observed UTC 2026-11-15 10:58:12.684642. The initial unobserved placeholder timestamp was corrected before any request; the conservative session-start estimate is separately labeled. Original report publication is date-only, so availability is the strictly next exchange session at 21:00. The existing exchange calendars were reused. Kangmei's 2018Q1 report was published 2018-04-28, after the fixed annual cutoff; the narrow four-notice response proves that boundary. The response and query are retained in the shared M5 ledger and `collection_manifest.json`.

The kernel now accepts an exact-cutoff report-coverage contract, even when a newer report's fields are not parsed. It rejects an assertion that omits an already visible newer fact period. Bounded provider report inventories do not establish exhaustive exchange/version-chain completeness; all four real contracts therefore remain `PARTIAL`, and latest-period status remains `UNVERIFIED`. The two numerical cases are explicitly `NUMERICAL_ENGINEERING_ONLY_LATEST_COVERAGE_UNVERIFIED`, not latest-coverage passes.

At the later fact-validation cutoffs, Kangmei 2019-05-06 selects the 2017 restated profit CNY 2,149,836,281.41, and Sanhui 2024-12-26 selects the 2023Q3 restated loss CNY -8,587,577.84. These are revision-selection checks, not factors on an artificially isolated old period. The known latest reports are respectively 2019Q1 and 2024Q3; unparsed current-period inputs block all later factors with explicit missing dependencies. Kangmei's 2018 annual facts are also retained in the long table. No later periods were deleted to force the revised case period to be latest.

There is no registered financial freshness policy. Outputs report period, age in calendar days, `UNASSESSED_NO_REGISTERED_POLICY`, and `formal_eligible=false`; no 90/180-day threshold is invented. `all_three_valid` only reports numerical calculability. Even a test with all three numbers and an invented cap cannot grant formal admission. Date-only 2024-12-31 information available in 2025 does not enter any pre-2025 snapshot.

## Documentary provenance and limits

`canonical_facts.json` and its CSV contain 22 field-version rows from six source PDFs. Every row records source SHA256, relative raw path and URL, physical PDF page, table/row/column, original and normalized value/unit, CNY currency, consolidated scope, revision/predecessor, publication precision and conservative availability. Transcription is explicitly agent-assisted, with raw page-token validation; it is not advertised as a general automatic PDF parser or independent human work. The two newly fetched dependency pages were rendered and visually inspected. Existing M4 source pages and independent documentary reviews were reused.

Kangmei's 2016 asset baseline is the unchanged comparison shown in the original 2017 filing, first observed at that filing's 2018 publication clock. It is not backdated to an uninspected 2016 filing. Its later restatement is independently chained. Sanhui's unchanged correction cash flow is displayed before on physical page 3 and after on page 4, not inferred merely because a correction omitted it. Exhaustive earlier/intermediate/later revision coverage remains unknown.

`human_review/` packages exactly five complete M4 documentary pairs with separate agent status and blank human name/date/decision/signature fields. The three M4 conflicting cases remain quarantined. Accepted human cases remain **0**; the five review cards do not become five M5 factor cases and do not satisfy the 20-case human gate. Full-pool R2 admission is **BLOCKED_HUMAN_0_FULL_CHAIN_UNKNOWN**.

## Cost and reproduction

New source collection: 9 HTTP attempts, 0 SDK wire requests, 1,478,604 response bytes; two new PDFs. All requests used `scripts/m5_sources.py` and the shared M5 ledger, within the financial allocation of 70 HTTP / 40 MiB and the global M5 limits. One pagination response repeated the first page; that response remains retained, completeness was not claimed, and a narrow date partition resolved the relevant Q1 publication boundary. No retry loop, larger case sample or 2025+ request followed. `cost_and_work_units.json` reports conservative elapsed agent-session time, not human labor or a full-pool budget estimate.

Offline reproduction from repository root:

```powershell
.venv/Scripts/python.exe scripts/m5_financial.py
.venv/Scripts/python.exe -m pytest tests/test_m5_financial.py tests/test_equity_features.py -q
```

The focused suite has 40 passing tests: real annual/Q3 arithmetic, exact revision identities and old-prefix invariance, missing TTM legs/assets, newer unparsed reports, duplicate/branch conflicts, separate market-cap failures, negative TTM values, date-only holdout boundary, and freshness/admission separation. Test-only caps and mutations are explicitly invented and never appear as real financial-case results. Reproduction requires local raw files and `pdftotext`; it makes no network request.
