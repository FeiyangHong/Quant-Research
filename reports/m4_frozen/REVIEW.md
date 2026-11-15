# Frozen R1 temporal impact and exposure review

Read-only review of the existing 448 runs; primary capital 100,000 CNY. No replay, new market test, parameter grid, shrinkage scan, production import, or 2025–2026 holdout access.

Audit repair disclosure: the first read-only audit draft overwrote query scope with ACCOUNT/WARMUP, making its initial zero-impact classification invalid. The draft summary/context/coverage, hashes and exact repair are preserved in superseded_audit_draft. The corrected audit was rerun over all 448 artifacts and a focused injected-impact regression test now detects the failure. This was an audit repair, not a strategy trial.

## Temporal impact

The frozen execution.master and data.master_asof choose the latest available row without effective interval checks. Original strategy._snapshot uses half-open [effective_from,effective_to) intervals before latest-publication selection. The full input grid has 585 differing metadata lookups; 4704 contexts occur in the 448 reconstructed query inventories. Observed execution-dependent discrepancies: 0. These counts are distinct from changed orders or PnL.

All master effective_to fields are null. Most raw differences are public listing announcements before the listing effective date. The dated sz.159908 index transition from SZ_FUNDAMENTAL200/OUTSIDE to CHINEXT/R1B is available 2018-12-05, effective 2018-12-10; it remains an ETF. Raw differing clocks are retained, with exact security/date/revision IDs. The instrument is absent from affected held/order paths. Current correction-chain and expiry/no-revival semantics are separate from this frozen interpretation.

Coverage reconstructs held positions at open and close, order creation/execution/events, target dependencies, corporate/share actions, full master queries at signal anchors and quarter selection dates. This is not a persisted internal lookup trace. No observed execution trigger is evidence against blanket invalidation; it does not prove every conceivable defect absent.

Original EOD share actions use 15:00; all 202 frozen master rows have availability 21:00, explicitly verified, so their 15:00 lookup state equals 09:30. The raw grid lists 09:30/21:00 while EOD queries use their equivalent 15:00 state.

## Monthly opportunity set and original risk estimator

monthly_primary16.json records every eligible ID/index family, exclusions, selection, common trend, target and actual close weights, direct portfolio return volatility, the original 50% shrink estimate and multiplier, and subsequent holding-window account risk. Dates separate anchor D, released decision D+1, and base execution D+2. Forward risk never enters historical decisions. The source estimates reproduce saved sigma exactly.

| Sample | Monthly eligible-count frequency | Trend off / decisions |
|---|---|---|
| development | {3: 26, 4: 31, 5: 12, 6: 3} | 26/72 |
| validation | {6: 7, 7: 12, 8: 15, 9: 1, 10: 1} | 25/36 |

Original shrunk/direct sigma ratios range 0.745806–0.864122. Of 432 scaled primary monthly targets (including cash), 330 have direct historical target volatility above 10%; maximum 13.4083%. This is estimator disagreement on the same trailing sample, not a promised or future risk bound. Subsequent realized risk is separately recorded and does not establish forecasting calibration.

The deterministic repeated-exposure design test uses 3/6/9 identical names and the unchanged original estimator, respecting 35% name caps. Equal splitting leaves direct risk unchanged while diagonal shrink lowers estimated risk by sqrt(0.5+0.5/n). No alternative shrink value or market return is searched. Actual ETFs need not be identical; index families and observed return dependence are not holdings look-through or causal factor attribution.

## Net PnL and holding-period contributions

| Sample | Pair | Scaling | Selection-different intervals | Net paired PnL CNY |
|---|---|---|---:|---:|
| development | R0−E0 | False | 46/72 | 3861.08 |
| development | R1−E1 | False | 46/72 | -2885.65 |
| development | R0−E0 | True | 46/72 | 1225.77 |
| development | R1−E1 | True | 46/72 | -1656.11 |
| validation | R0−E0 | False | 36/36 | 2126.00 |
| validation | R1−E1 | False | 36/36 | 3637.47 |
| validation | R0−E0 | True | 36/36 | 9347.18 |
| validation | R1−E1 | True | 36/36 | 4856.20 |

Annual attribution covers all 448 runs, 2,016 account-years and 182,784 ETF-year rows, retaining 172,624 zero-PnL rows. Maximum account-year reconciliation error is 4.66e-10 CNY; daily maximum 5.53e-10 CNY. Formula: marked value change + sale notional − purchase notional − all fill fees + recognized dividend receivables. Payment is not income twice. Slippage is already in fill prices and is not deducted again. Annual boundaries carry prior-year marked value; development and validation start with separate initial cash.

The 432 paired holding intervals run execution day through the day before next execution; ETF contributions and fees include retained/blocked positions. They reconcile to each pair's account difference. This is rebalance-window accounting, not FIFO completed trades or causal momentum alpha. Annual pairs retain 2016–2017 zero differences. PnL is additive CNY, not the registered mean daily-return endpoint and not a fixed-cost budget.

## Limits and provenance

- Missing effective_to means expiry logic has no real-data test in these inputs.
- No complete persisted trace of every internal master lookup exists; event/position/order coverage is a conservative reconstruction from frozen source and artifacts, not instrumented execution.
- Old master_asof is availability-only. Its whole-universe differences do not prove it was called on an execution-sensitive path; no persisted per-call trace.
- Current correction-chain/no-revival refinements are a separate semantic design, not a retroactive reinterpretation of frozen strategy outputs.
- Repeated ETF exposure counterexample demonstrates estimator representation dependence, not actual complete ETF return identity or a superior alternative.
- No ETF holdings look-through or causal factor model is available. Index-family counts and correlated returns are proxies, not independent economic exposures.
- Holding-period attribution means fixed rebalance execution-to-next-execution intervals, including all fills/fees/blocked positions; it is not FIFO trade attribution.
- Daily prices and modeled cash settlement retain all original data/execution limitations; fixed incremental costs remain unknown.

Original result summary SHA256: `c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb`. Original source and data hashes, every read artifact hash and row count are in input_hash_manifest.json. Frozen execution/data/strategy files were checked for all 448 runs, independently of current production source. Reproduce with `python scripts/m4_frozen_review.py`; focused design checks: `python -m pytest tests/test_m4_frozen_design.py -q`.

Disposition: no temporal-impact evidence supports replaying or blanket-invalidating 448. Existing economic/evidence limitations and ARCHIVE_CURRENT_CONFIGURATION / STOP_ETF_PARAMETER_SEARCH remain. The risk design limitation does not authorize estimator replacement, parameter optimization, paper or live deployment.
