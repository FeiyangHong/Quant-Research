# M4 independent engineering review

Status: **PASS_SCOPED_ENGINEERING_REVIEW**. Baseline `7d5bcebbf98a1fe68b50f760e63f7fbd66d28d78`. Generated 2026-11-15T09:35:21.369310+00:00.

The reviewer did not author the production changes. This audit checks dual-clock safety, synthetic main-account integration and the limits of the supporting evidence. It grants no R2/R3 admission or performance status.

## Findings and independent retest

Two P2 input-contract defects were reproduced and returned to the implementation author. Fixed-quantity instructions could be silently ignored when their security appeared only in `fixed_quantities`, and the normal-runner prohibition depended on entering the order loop. Linked temporal corrections could omit their own stable revision identity; a final root-requested check also reproduced silent transition selection for an unrecognized explicit revision kind. Four initial failing assertions were preserved in `pre_fix_counterexamples.txt`, with the additional kind failure in `pre_fix_revision_kind.txt`; the author repaired the contracts and the reviewer reran those counterexamples unchanged.

The review suite passes **33 tests**, including 16 tests from this reviewer. The focused existing execution, equity, share-event, settlement, decimal-money, data and strategy regression passes **220 tests**. The exact commands, logs, source hashes and before/after stability check are recorded in `independent_review.json`.

Additional independent cases verify order-independent corrections/transitions, invalid lineage, partial FIFO disposal before dividend cash, subsequent purchases without old dividend claims, statutory fees across the August 2023 boundary, retained unpaid tax, and blocked exits when tick/settlement/limit evidence is unknown. The mixed-lot oracle checks explicit cash CNY100,070.38 and NAV CNY100,050.38 with CNY20 unpaid tax; it is an invented accounting case, not a security return.

## Evidence checks

All **102** recorded engineering artifact hashes match. The six cases remain labeled invented and reconcile 420 daily rows using the existing fixed-input oracle. The integrity audit verifies **58** raw data objects and their byte counts, 3,779 unique pool rows (2,946 MAIN; 833 ChiNext), five complete documentary cards, three quarantined cards and zero human acceptances. It does not claim that this reviewer independently re-extracted those PDFs or proved the vendor's historical pool complete.

Root-authored independent frozen checks cover 4,356 temporal boundaries, 1,459,715 position rows and 78,545 order rows, with no intersections. Final frozen analysis reports zero actual execution dependency discrepancies. The root's independent annual check reconciles 2,016 account-years to original summaries, maximum PnL difference CNY4.8e-10. These statements are bound to the current temporal selector and frozen-analysis hashes; absence of complete persisted internal call traces remains an explicit limit. This reviewer did not rerun strategies or independently regenerate the root's frozen analysis.

## Remaining admission limits

No unresolved defect remains within the tested synthetic engineering scope. Real corporate-action source acceptance and broker/CSDC cash reconciliation remain incomplete. Unsupported stock bonus/conversion/rights/merger/liquidation-payment events, missing anniversary conventions and intraday effective intervals remain blocked. The financial route still lacks complete historical status, shares, liquidity and version coverage, and human acceptance remains zero. These are retained blockers, not synthetic substitutes for admission.

R2/R3 real strategy registration and execution remain zero. No 2025--2026 market data, purchase, paper/live action or frozen artifact mutation was performed by this reviewer. Any change to the hashes in `independent_review.json` requires rebinding this review.
