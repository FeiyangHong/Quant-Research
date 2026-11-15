# M5 independent accounting review

The accounting mechanism passes the second and final review round: **42 independent tests passed**. First-round defects are retained below. The three registered real-source cases remain **BLOCKED_RULE_SOURCES** at this review snapshot. Their conditional model arithmetic passes; this is not real-source rule admission, broker settlement verification, or strategy performance evidence.

Reviewer: independent non-author accounting agent. Baseline: `8a9977cb5538a3ffd3c07506035c0dca7c3a0f14`. Review-only changes are confined to `review_code/m5/test_external_accounting.py` and this report/JSON. No production code, author reports, M4 evidence, 448/353 experiments, or holdout data were changed. No network requests were made.

## Preserved first round

Command: `.venv/Scripts/python.exe -m pytest review_code/m5/test_external_accounting.py -q`

Initial independent run: **33 passed, 4 failed in 2.60 seconds**. The author's own preceding M5 suite had 15 passes; it did not detect these defects.

| Finding | Independent reproducer | Impact | Final disposition |
|---|---|---|---|
| Fixed intent missing from audit | `test_fixed_intent_audit_is_boolean_true_not_nan` | `create_order` copied the order before `fixed_quantity_intent` was added. The exported audit value was NaN; `assert value` falsely succeeded because NaN is truthy. | PASS after flag is supplied before the immutable audit copy. |
| Contradictory source classification | `test_explicit_real_origin_cannot_be_relabelled_synthetic` | A manifest with explicit `data_origin=REAL` and synthetic purpose/true flag entered the synthetic path. | PASS after contradictory origin is rejected. Legacy explicitly synthetic fixtures without origin remain supported. |
| Registered source hash ignored | `test_registered_rule_artifact_hash_is_not_silently_repinned` | Replacing a registered rule SHA256 with 64 zeros did not reject. The builder recomputed hashes and silently repinned bytes instead of enforcing the registry. | PASS after registry rule, event document, and budget raw-wire hashes are enforced. Builder also compares normalized daily/basic rows with archived SDK record arrays. |
| Incorrect price-band rejection reason | parameterized `test_known_bad_execution_input_rejected` | A valid reference with a mismatched upper band emitted `HISTORICAL_LIMIT_REFERENCE_REQUIRED`. The broad ValueError handler caught its own accounting exception. It failed closed economically but misreported the audit cause. | PASS after mismatch is raised outside the conversion handler. |

The author made one corrective round. The independent final suite added terminal-rights, five-attempt sale exhaustion, and three direct raw-input scenario oracles; **42 passed in 2.63 seconds**. No third correction round was used. First/final code hashes and test timing are preserved in `ACCOUNTING_INDEPENDENT.json`.

## Independent arithmetic and boundaries

Expected values never read actual fills, actual NAV, production FIFO/fee/rate helpers, or the author's `independent_expected` function. Invented contract fixtures are explicitly documented as mechanism tests; their REAL-tag stand-in files test declaration/hash enforcement and are not authentic source evidence.

- Fixed engineering purchases use the verified pre-opening upper band for reservation. At prior close 10, upper band 11, and opening 10.10, 100 shares reserve 1,105.01 and fill for 1,015.01 including fees. Changing that day's future close to 9/10/11 does not alter the fill, reservation, or opening equity. A 10,000-share instruction with 100,000 cash is reduced to 400 by the existing 5% cap and band-based risk budget.
- Two buys of 100/200 shares at 10 cost 1,005.01 and 2,005.02. Ordinary/special dividends of 0.25/0.75 create 75/225 receivables at ex-date, retain them through official scheduled payment, and credit the next modeled session. Record-date rights and prefix balances are checked independently.
- Selling 100 FIFO shares for 1,000 incurs 6.01 fees and accrues 20 dividend tax. Cash is 98,283.96, payable 20, remaining potential tax 40, and reserve 60. NAV is 100,263.96; potential reserve is not a second NAV expense. Modeled debit of 20 changes cash/payable/paid while leaving NAV at 100,263.96 and reserve at 40.
- Explicit unknown/malformed ST values, future/unverified limits, adverse opening limits, suspensions, contradictory real manifests, changed archived bytes, unsupported stock actions, and normal-entry fixed instructions are blocked. Normal-entry stock dividends remain blocked. Five failed sales retain the shares; unpriced delisting rights retain 300 shares and explicit valuation uncertainty without invented recovery cash.

## Registered source scenarios and acceptance

The independent raw-input oracle reads the frozen case instructions, raw daily rows, and existing event facts directly. It uses Decimal candidate fee assumptions and checks all **110 daily rows** against the separately labeled conditional expectations. It checks the full predicted fill lists separately; it never derives an expectation from an actual engine fill or account NAV.

| Registered case | Sessions | Conditional expected fills | Real source gate at review |
|---|---:|---|---|
| Moutai ordinary June 2023 | 34 | Buy 100 at 1,709.99; buy 100 at 1,713.18; sell 100 at 1,699.00 | BLOCKED_RULE_SOURCES; zero actual fills |
| Moutai special December 2023 | 35 | Buy 100 at 1,648.23; buy 100 at 1,640.00; sell 100 at 1,640.01 | BLOCKED_RULE_SOURCES; zero actual fills |
| Kangmei ST May 2019 | 41 | Buy 100 at 5.78; buy 100 at 5.60; five adverse-limit sale attempts retain 200 shares | BLOCKED_RULE_SOURCES; zero actual fills |

Missing primary fee/limit rules are a source-admission blocker, not an excuse to relabel the inputs synthetic or declare a real reconciliation PASS. The conditional arithmetic does **not** require a broker ledger to be tested. Actual broker credit/debit timing remains separately UNVERIFIED. The adapter marks daily availability as a modeled 21:00 close clock with no observed vendor-first-seen claim; opening matching remains the daily-screen assumption.

The fixed 10,000,000 CNY is engineering cash needed to accommodate Moutai under the unchanged 5% cap. Deployment capital remains 100,000 CNY. This review opens no ordinary stock Alpha strategy, R2/R3 registration, ETF search, final holdout, paper trading, or live trading.

## Time and evidence

Earliest captured review clock: 2026-11-15 11:10:45 UTC. Conservative session accounting starts at 11:10:00 UTC, rounding backward to include initial read tools before that clock. The JSON records actual completion UTC and total conservative elapsed wall seconds, including tool waiting. This is agent-session occupancy, not human labor or pure CPU time. Source-collection requests/bytes attributable to this reviewer: zero.
