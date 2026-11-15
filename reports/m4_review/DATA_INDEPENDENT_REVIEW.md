# Independent M4 financial-document and denominator review

**PASS_DOCUMENTARY_COVERAGE_AUDIT_ADMISSION_BLOCKED.** The five completed documentary pairs and three quarantined conflicts are supported by the inspected local source documents. This is an independent agent review of the data author's work; independent human acceptance remains **0**. R2 and R3 remain blocked.

The reviewer imported no D collection or normalization code. An independent script in `work/m4_data_review/review_sources.py` verified 22 unique PDF source hashes, located all 48 reported original/revised financial values in the declared pages, checked 16 availability/execution clocks against the bound exchange calendars, and checked revision links. Poppler rendered the source pages; 25 complete pages were visually inspected across all eight cases, including both sides of the three conflicts. Exact document hashes, field-to-page matches and inspected page lists are saved in `data_independent_review.json`.

| Case | Independent source conclusion |
|---|---|
| 康美 2017 | Original 2017 report and 2018 comparative restatement support the three values; 2017 comparative columns are distinguished from 2018 values. |
| 英飞拓 2019 | Original and correction tables support the parent profit, cash flow and total assets; total profit and parent profit are distinguished. |
| 三晖 2023Q3 | Parent profit and cash flow use year-to-date columns; assets use period-end values. The correction's after-value columns support the card. |
| 光莆 2022 | The three R2 fields are unchanged. The original and revised reports contain a genuine revenue correction; no artificial R2-field change is claimed. |
| 好利 2022Q3 | Original and corrected year-to-date cash flow and period-end assets match the card; parent profit remains unchanged. |
| 景峰 2023 | Corrected statement versus correction announcement differs by CNY 0.01 in parent profit. Both figures are visible; canonical revised field remains null. |
| 宁科 2022 | Revised report summary/statement reports negative cash flow while its narrative table retains the old positive value. Canonical revised cash flow remains null. |
| 安靠 2021H1 | Correction announcement asset row differs by CNY 0.01 from its liabilities-plus-equity row and revised statement. Canonical revised assets remain null. |

All amounts reviewed use consolidated CNY yuan. Parent-attributable profit, total profit, year-to-date flows and period-end assets are not interchanged. Five means five distinct issuer-period documentary pairs, not fifteen field cases or five human-accepted admission cases. Exhaustive intermediate/later version coverage remains explicitly unknown.

One documentation finding was repaired by the D author: the 宁科 conflicting narrative cash-flow value is on physical PDF page 17, omitted from the initial card's page list 6/76. The final card now lists `[6,17,76]` and records `statement_source_page=76` and `conflict_source_page=17`. This repair was independently verified; quarantine and financial values were unchanged. The initial check output is preserved under `work/m4_data_review/before_page_location_repair.json`.

Date-only publication consistently maps to the strictly next exchange session at 21:00, then the next session for earliest execution. Holiday/weekend cases were checked. The 2024-12-31 notices have 2025-01-02/03 clock metadata only; they were not placed into the 2020 snapshot or used to access 2025 market observations. Historical vendor first-seen and exact intraday release times remain unknown.

The independent denominator reconstruction starts from all 4,810 rows in the actual 2020-07-31 provider security response and applies only the fixed board scope. Its exact 3,779-ID set matches the published pool, retaining 212 `isST=1` names and 28 suspended names. Every published raw daily field and vendor industry join was compared with the original response. Missing shares, market capitalization, complete risk state/history, listing age, liquidity history, company-action history and financial vintages remain missing. The non-ST size-percentile denominator is not fabricated from the 3,567 vendor non-ST rows.

The official industry's saved publication page supports 2020-07-14, followed by the conservative 2020-07-15 21:00 availability clock. This review did not independently parse every one of the 3,878 official industry codes or audit all subsequent issuer industry changes. Completeness against an independent exchange historical roster remains unverified. The data author's report preserves these limitations.

Corporate-action collection completeness, normalized event accuracy and network-budget accounting are outside this financial/denominator review. No market strategy, optimization, bootstrap, performance test, procurement or admission release was performed.

Final financial-card SHA256: `134f43b506fdca59bb54ccd05e63781510a5eb461b787772a31155af0b645fb5`. The machine review binds the final cards, coverage summary, calendar evidence and data author's report. Full checked source paths and hashes are provided there for local reproduction.
