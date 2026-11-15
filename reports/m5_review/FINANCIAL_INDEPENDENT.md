# M5 independent financial review

**PASS for the two fixed financial numerical mechanisms: 25 independent tests passed in 3.36 seconds.** No defect or corrective implementation round was required. F01 remains blocked for both real cases; latest-report coverage remains PARTIAL/UNVERIFIED, freshness has no registered policy, and formal admission remains false. This is a non-author agent review, not a human signature or full-pool admission.

Baseline: `8a9977cb5538a3ffd3c07506035c0dca7c3a0f14`. The independent reviewer wrote only the new financial test/report files and temporary rendered pages. No production, source, author report, M4 evidence, strategy experiment, or holdout data was changed. No network request was made.

## Documentary checks

All six archived PDF hashes were recomputed. The reviewer rendered and directly viewed all eight pages used by the 22 canonical field-version rows; the complete page layout, row, period column, unit, and before/after headings were inspected. No expectation is derived from `factor_cases.json`, the production factor output, or the author's Decimal routine.

| Source SHA256 prefix | Source | Physical PDF pages | Independently checked values |
|---|---|---|---|
| `15b3b15df2df` | Kangmei 2017 annual original | 6, 7 | Parent profit 4,100,926,148.57; CFO 1,842,794,237.84; 2017 assets 68,722,020,630.61; 2016 comparative assets 54,823,896,576.81 |
| `9f47aa0dc0a8` | Kangmei 2018 annual, later comparison/restatement | 6 | Current 2018 profit/CFO/assets and revised 2017 profit/CFO/assets plus revised 2016 assets; adjusted and unadjusted columns kept distinct |
| `9b57ae1e21bc` | Sanhui 2023 Q3 original | 2 | YTD profit -6,354,889.62; YTD CFO -9,898,689.75; assets 726,007,340.73 |
| `41d9370fd96d` | Sanhui correction | 3, 4 | Revised YTD profit -8,587,577.84; unchanged CFO -9,898,689.75 explicitly shown before/after; revised assets 736,593,802.62 |
| `7028b0a1c7b8` | Sanhui 2022 Q3 | 1 | YTD profit 100,478.18; CFO -20,765,136.43; assets 606,916,408.59 |
| `3ae8304f34e4` | Sanhui 2022 annual | 8 | FY profit 12,944,711.92; FY CFO 45,404,676.85 |

All 22 amounts exactly match the source amounts in CNY yuan; the independent tests pin all page/period/field combinations. Sanhui's negative original YTD values remain negative. Kangmei's 2016 asset comparison is first observable through the inspected 2017 annual filing and is not backdated to an unseen 2016 original. The eight rendered page images/text are review intermediates under `tmp/pdfs/m5_financial_independent/`.

## Hand equations through the main chain

Kangmei average assets are `(68,722,020,630.61 + 54,823,896,576.81) / 2 = 61,772,958,603.71`. Thus F02 is `4,100,926,148.57 / 61,772,958,603.71` and F03 is `1,842,794,237.84 / 61,772,958,603.71`.

Sanhui TTM parent profit is `-6,354,889.62 + 12,944,711.92 - 100,478.18 = 6,489,344.12`. TTM CFO is `-9,898,689.75 + 45,404,676.85 - (-20,765,136.43) = 56,271,123.53`. Average assets use matching Q3 stocks: `(726,007,340.73 + 606,916,408.59) / 2 = 666,461,874.66`. F02/F03 divide the respective flows by that denominator. The independent tests calculate these with 40-digit Decimal precision and compare the existing `financial_asof -> r2_factors` outputs at the registered tolerance, without assuming an invented same-day capitalization.

## Adversarial and governance checks

- Later corrections select 2,149,836,281.41 for Kangmei 2017 profit and -8,587,577.84 for Sanhui 2023 Q3 profit at their later review cutoffs. Neither changes the original historical prefix. Reversing input row order leaves the original outputs unchanged.
- The later factor cutoffs require 2019 Q1 and 2024 Q3 respectively. Missing newer fields block all factors rather than reusing an older complete year/Q3. The later report evidence is not removed to force a desired old period.
- Missing prior Q3 profit blocks F02 while preserving F03; missing FY CFO blocks F03 while preserving F02. Missing current or prior Q3 assets blocks both. No missing leg is zero-filled or replaced by a different reporting period.
- A `TOTAL_EQUITY` string without matching share-class and source-hash fields cannot open F01 on this M5 route. Wrong date, future availability, float capitalization, mismatched share classes, and missing price/share source hashes all block F01 without disabling valid F02/F03.
- Test-only complete coverage plus invented consistent capitalization can make all three numbers calculable but leaves `formal_eligible=false`, with no registered freshness policy. Missing coverage also remains unverified. These tests do not certify the authenticity of invented hashes or admit their cap.
- Date-only publication cannot be backdated to the same-day decision. A synthetic 2024-12-31 document with 2025-01-02 availability cannot change the pre-2025 snapshot. No actual 2025+ market or factor observations were read.

Latest coverage is only a bounded input contract, not proof of an exhaustive revision chain. Agent documentary checking is separate from the five blank human review cards, the 0/20 human acceptance gate, full-pool source completeness, freshness registration, ordinary-stock execution admission, and Alpha registration. None of those gates is opened by these numerical passes.

## Reproduction and time

`.venv/Scripts/python.exe -m pytest review_code/m5/test_external_financial.py -q`

Result: **25 passed in 3.36 seconds**, first independent financial review round. JSON preserves full source/code/test hashes, the transcribed constants, observed UTC endpoints, and conservative elapsed agent-session time. Financial review is a separate interval after accounting review; waiting/rendering is included, and this is not human labor or pure CPU time.
