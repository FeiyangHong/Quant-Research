# Historical R1B universe and raw-history audit

Audit date: 2026-11-15, Asia/Shanghai. Requested observation window: 2010-01-01 through 2024-12-31. No 2025–2026 historical price or strategy-return observations were requested. Current descriptive metadata and later reports describing pre-2025 funds are retained as retrospective evidence, with their actual publication dates.

This collection supports an auditable competitor inventory and an independent turnover-only dependency calculation. It does not itself establish a point-in-time research dataset, account permissions, a data licence, or strategy performance.

## Inventory coverage

The BaoStock 0.9.4 anonymous adapter returned the complete requested calendar: 5,479 natural days, including 3,643 reported exchange sessions. Historical ETF queries cover the first session, 2010-01-04, plus every final trading session of the 60 calendar quarters through 2024. All 61 endpoint queries succeeded after explicitly recorded repairs. They contain 17,869 membership rows and 1,148 distinct historical identities; individual snapshot counts range from 7 to 1,033. The largest gap is 66 trading sessions.

The strategy fixes each quarter's representatives using the previous quarter's final session. Therefore, a fund capable of being chosen must be present at a selection endpoint. A fund whose entire lifetime falls between endpoints cannot be selected by this rule. This establishes an efficient sampling argument **conditional on the provider's endpoint membership completeness**; it is not a claim to enumerate every fund that ever existed. A held fund is not deleted when absent from a later snapshot. The 252-session listing-age requirement applies to monthly entry, not to the representative competition; the independent turnover calculation does not incorrectly apply it at quarter selection.

The current stock master returned 9,038 records. Historical-day name calls also failed to name 122 identities retained by historical ETF snapshots. Two large metadata requests reached their bounded wall timeout; successful older name calls recovered none of those withdrawn identities. The current Eastmoney fund-name list likewise recovered none. These findings demonstrate why current metadata alone cannot define the historical competitor set.

The official-source collector searched all 122 missing identities, with complete pagination in its recorded windows, and obtained 101 historical annual reports. Supplementary original notices and corrected report titles resolve the remaining relevant identities. Six additional competitors were recovered: 510520 (CSI500), 515930 and 159927 (CSI300), 159955 (ChiNext), 159999 (CSI500), and 159846 (CSI1000). Withdrawn products such as 512320 remain in the overall inventory even when their documented index is outside the frozen strategy scope.

Review of every remaining current name containing the target broad-market terms found 588180, abbreviated as 国联安科创ETF, without an index number. Its official report identifies the STAR50 index and listing on 2021-07-01. It is included in the competitor history collection. Exact index names prevent the CSI500 Shanghai-only index (510440, code 000802), CSI500 Shenzhen-only index (159932), sector indices, and style variants from being combined with CSI500 or CSI300.

## Evidence and reproduction

Raw root: `data/raw_r1_universe/r1_2010_2024/`.

- `universe_manifest_v3.json`: all requested endpoints, calendar, metadata queries, raw hashes and inventory linkage. SHA256: `22c4c6cea9b702ad0bbd6809f51400028d0bdbdd5da138a26b7d8ce06efe4853`.
- `inventory_v3.json`: all 1,148 identities, including unresolved and out-of-scope identities; no current-survival deletion.
- `inventory_documentary_v6.json` and `candidates_documentary_v6.json`: official evidence attached without backdating publication; 110 candidates across 13 exact index groups. Candidate SHA256: `1b4ab585c2c07842ef6f4da4dc80e40afca245b1fe7471a94a447674811b09de`.
- `documentary_manifest_v6.json`: hashes of the input inventory and every documentary JSON source, with immutable exact-byte copies under `documentary_inputs/`. SHA256: `98fab99aa106e1664c3929df82d63ffd826e219eaf8476fe40089393681f181d`.
- `histories_b87b8e5ad646_v4.json`: 110 successful full-window history queries and their raw/normalized object hashes. SHA256: `a4596ad7ce5ffc60eb39b8473e32b18bd3833477f898a834322e8232d6b82f82`.
- `provisional_dependencies_v6.json`: independent decimal ADV60 schedule over 60 quarters, using original dated master records. SHA256: `f151e7f3ff8e3bfc8ae905544976f58d37bcd0fbd954ea44effa417ca945d7d2`.
- `query_cache/`, `manifests/`, `raw/`, `normalized/`: original and repair attempts, immutable SDK row snapshots, exact raw string values, and reproducible normalized records. Raw snapshots are SDK response records, not a claim of wire-packet capture.

Reproduce documentary reconciliation without network access:

```powershell
.venv\Scripts\python.exe scripts/collect_r1_universe.py --stage reconcile --inventory data/raw_r1_universe/r1_2010_2024/inventory_v3.json --official-evidence data/raw_r1_actions/metadata_104/by_instrument data/raw_r1_actions/dead_identities/by_instrument data/raw_r1_actions/dead_identities/identity_supplement.json data/raw_r1_actions/identity_repairs/identity_evidence.json data/raw_r1_actions/metadata_588180/by_instrument data/raw_r1_actions/listing_110/original_metadata_records.json --revision 6

.venv\Scripts\python.exe scripts/collect_r1_universe.py --stage dependencies --candidates data/raw_r1_universe/r1_2010_2024/candidates_documentary_v6.json --universe-manifest data/raw_r1_universe/r1_2010_2024/universe_manifest_v3.json --history-manifest data/raw_r1_universe/r1_2010_2024/histories_b87b8e5ad646_v4.json --master-records data/raw_r1_actions/listing_110/master_records.json --revision 6
```

These commands are idempotent while inputs are unchanged. Later official-source refreshes require a new revision number; the manifest's `snapshot_path` preserves the exact input bytes of this run.

Query collection uses the isolated optional BaoStock 0.9.4 SDK at `work/data_probe/baostock_sdk`; main research dependencies were not changed. The collector limits worker wall time to 30 seconds, API socket time to 12 seconds, one automatic retry, a minimum inter-query interval, and at most two explicit repair records. A repository-wide exclusive collector lock prevents concurrent anonymous streams.

An early concurrent inventory/history attempt produced provider `10001001` (not logged in) errors after successful login. The competing process was stopped, the remaining work serialized, and original failures retained. Six endpoint queries and five history queries required explicit repair after eliminating the session-interference condition. One later history query, 159949, returned the same error despite serialization; a bounded explicit repair succeeded. Thus concurrency was an observed aggravating condition, not a proven explanation of every provider session failure. Nothing was replaced in place. Cached success objects are reused only after hash verification.

## Raw observation checks and unresolved qualifications

Normalization retains provider OHLC/amount as decimal strings and volume as an exact integer. It does not invent publication timestamps, historical revisions, total returns, price limits, listing/delisting dates, or corporate actions. Explicit provider suspension is distinct from zero turnover with normal or unknown status; missing records are never filled into tradable bars.

The parent agent's independent Eastmoney reconciliation identified an upstream quote disagreement on 2020-08-21, 24, 25, 26 and 27: BaoStock OHLC for 510300, 510500, 512100 and 159915 are each one tick lower. Raw and normalized BaoStock decimal strings were checked and are identical. This is not a local rounding or flooring transformation. Original data remain unchanged. The parent then obtained bounded historical Tencent quotes, which matched all 80 disputed BaoStock OHLC fields. The preselected BaoStock source is retained with the disagreement documented, not silently corrected. The evidence is `data/raw_eastmoney/r1_2010_2024/reconciliation_v1.json` and `tencent_dispute_check_v2.json`. Agreement between providers is corroboration, not proof that their upstream sources are independent. Unsolicited current-quote fields in the Tencent envelope were quarantined by the parent and not admitted to research. A bounded official-site search found no specific public correction notice explaining these dates; that search is not evidence that no notice exists.

The raw split checks corroborate official timing: 510500 traded in old units through 2022-08-26 (close 7.220), with the first adjusted quote on 2022-08-29 (previous close 6.304); its 2015-04-13/14 records explicitly indicate suspension before the 2015-04-15 adjusted quote. 512100 is explicitly suspended on 2022-09-02 and resumes in converted units on 2022-09-05. These checks explain quote units; they are not strategy-return analysis.

Each official annual report retains its real publication date and a flag that it does not establish a historical effective interval. The official collector obtained 113 listing/correction documents and 107 original prospectuses for the 110 candidates. Original listing announcements and later benchmark changes establish index membership before competition; latest annual confirmation is not backdated to listing. This is a material issue: 159908 originally tracked 深证基本面200, whereas its later mandate is the plain ChiNext index. The original change notice was published 2018-12-04, conservatively available on 2018-12-05 at 21:00, and effective 2018-12-10. The independent schedule applies that chronology. Provider name histories are not demonstrated point-in-time vintages; a currently out-of-scope fund could historically have tracked an eligible index until its original and changed mandates are checked. All unresolved identities and source conflicts remain visible.

The original 510500 listing notice contains a 2012-03-15 date typo. Its same-publication-date final version states 2013-03-15. Both source records remain, and the reconciliation explicitly prefers the final/correction notice rather than choosing the earliest date.

Accessibility is not a licence. The provider's free API and [official ETF daily-interface documentation](https://baostock.com/mainContent?file=DailyUpdates.md) do not, by themselves, establish permission for the intended investment-research use, redistribution, historical-vintage completeness, or accuracy. The documentary and raw-history artefacts do not set `account_verified=True`.

## Validation

The unit checks cover actual-calendar quarter endpoints, locked holdout dates, retention of dead identities, current-only identities not being backfilled, exact index separation, legal fund-title suffixes, publication-date preservation, no mutation of source evidence, decimal turnover ties, missing turnover, explicit suspension, refusal of partial/empty histories, and endpoint-membership discrepancies. Provider adapter tests cover the reusable bounded snapshot layer.

Validation passed: **69 tests** across `tests/test_universe.py` and `tests/test_provider_baostock.py`.

## Completed collection and independent dependencies

All 110 requested histories succeeded, yielding **127,090 observations**, with returned dates from 2011-07-13 through 2024-12-31. The earliest record belongs to a retained identity whose original index was out of scope; a successful empty 2010 segment is not filled with fabricated history. There are 126,046 normal observations, 154 explicitly suspended observations, and 890 other zero-turnover observations. All 1,044 zero-turnover rows remain visible. Normalization reported zero parse issues.

The six recovered retired competitors are retained with 1,378 rows for 510520, 785 for 515930, 94 for 159846, 1,099 for 159927, 1,280 for 159955, and 630 for 159999. In particular, the short-lived 159846 is not dropped because it cannot meet a later entry-age test. Last observed dates are observations, not inferred official termination dates.

The independent selector uses the exact prior 60 exchange sessions, finite nonnegative raw amounts, normal prior-endpoint trading status, the original master publication/effective intervals, and deterministic ties by listing date then code. It computes no strategy returns and does not read reconstructed total-return fields or total-return availability clocks. It also does not assert account permissions. Its 111-row dated-master input is frozen with SHA256 `cb78a63ca8568bd876ea70499a1b938ac1dc66856809771d3a0ceb5aab643442`.

The resulting union is **16 instruments**: 510300, 510500, 512100, 588000, 588030, 588220, 159541, 159573, 159781, 159814, 159836, 159845, 159915, 159922, 159949 and 159991. The earlier current-category-only diagnostic had incorrectly included 159908 before its index conversion; that provisional result remains archived and is superseded by the dated-master calculation.

Across every candidate and quarter endpoint, **zero normal raw endpoint bars were absent from the provider's corresponding historical membership snapshot**. This is a useful internal consistency check over the collected competitor set. It cannot prove that an identity missing from both provider surfaces never existed, establish original vendor publication/revision vintages, or substitute for the remaining dataset-admission gates. Full company-action coverage for the 16 selected instruments is a separate dependency managed by the official-source collector.
