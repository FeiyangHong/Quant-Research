# Campus activation independent review

2026-11-18, Asia/Shanghai. Reviewer: non-author AI subagent; **not a human signer**. Restoration base: `21f279fe0a73375cd26c3fb044e58c955874646f` on `codex/m10-r2-data-and-screen`.

**Decision: accept the bounded campus activation and stop at BLOCKED_DATA_CAPABILITY for the tested source contract.** Authentication and real fixed financial samples have advanced beyond the old network denial. The combined capability sample, full-pool data, stock execution, complete M10 cards and human acceptance have not passed. This is neither a supplier-wide impossibility finding nor a negative R2 performance result.

## What was independently checked

I read the access/sample/audit code, fixed plan, sanitized access and sample receipts, registered case inventory, local-original mapping and SDK 3.8.2 implementations. I did not read the license, initialize the SDK, make network calls or run a strategy. A separate reviewer-authored local comparison program read licensed response files only inside the local Python process; no vendor values or raw payloads were emitted to tools, chat or this report. Its public output is [CAMPUS_INDEPENDENT_CHECKS.json](CAMPUS_INDEPENDENT_CHECKS.json); its code is [check_campus_local_evidence.py](../../review_code/m10_activation/check_campus_local_evidence.py).

| Evidence | Independent finding | Limit |
|---|---|---|
| Campus access receipts 01–03 | Successful initialization was retained. Receipt 02 locates the failure in local quota validation; 03 passes after finite integral float normalization. | Not another education-network denial. Quota metadata does not certify all modules or rights. |
| Fixed sample receipt | 26 requested samples returned: 18 financial and 8 structural; 30 observed `_execute` attempts, 2,715,883 saved serialized-response bytes. | Client RPC observations are not a complete wire-request or wire-byte count. Serialized DataFrame JSON is not the original network payload. |
| Source integrity | All 13 reacquired official-original hashes and all 26 local serialized-response hashes match their manifests. | Original-document identity remains distinct from supplier-response identity. |
| Four fixed financial cases | For 600518, 002729, 002857 and 300632, both registered versions match the expected security, quarter, publication date and all three fields to the cent in one response row. | Expected values come from the pre-existing registered case evidence, not a new human transcription. |
| Historical-prefix checks | All four before-publication requests are empty; repeated original-cutoff responses are identical; later query results preserve original facts after filtering to the earlier publication boundary. | Retrieval/ingestion metadata is excluded only from the append comparison. This is a finite four-case check, not all-history completeness. |
| Local arithmetic | Kangmei annual and Sanhui cumulative-to-TTM profit/CFO, average assets, F02 and F03 match the pre-existing independent Decimal oracle. | Not production adapter output; F01 remains uncomputed without admitted same-clock capitalization. |

The author's PDF check establishes that registered value tokens occur on the specified physical pages, together with matching original hashes. I did not independently render and visually review those table rows/columns. Token occurrence must not be called complete table-semantic verification, an M10 case-card PASS, or human approval. The original difficult queue, three quarantines and the 002528 post-2024 availability boundary remain unchanged.

## Challenge to the stopping decision

The stopping case is stronger than merely requesting too few output columns:

- I inspected the complete mainland `get_shares` field map in SDK `services/stock_status.py`. It offers total/A/free/circulating/noncirculating/preferred share fields, but no publication, historical availability or revision-identity field. Its historical date index and `rice_create_tm` do not establish those clocks. The implementation also fills missing `preferred_shares` with zero before returning the frame; a returned zero is therefore not independent evidence of no preferred shares. The tested five identities on 2020-07-31 cannot yet bind the required ordinary A/B/H denominator and its historical public/effective chain.
- Historical `get_instrument_industry` responses provide classification codes/names for an explicit date. The SDK's alternative `get_industry_mapping(date)` provides taxonomy mappings, while `get_industry_change` provides membership start/cancellation dates without an as-of cutoff or publication clock. These are useful leads, but no checked interface establishes the required historical disclosure/version contract. I did not call an unrestricted current-history endpoint or infer its absence of leakage.
- `all_instruments(date)` explicitly filters today's instrument attributes by listed/delisted dates. It is a historical-existence lead, not a historical name, board or risk-state table. The absence of 000024 at the one fixed date does not prove missing delisted coverage. ST/suspension booleans and two dividend records likewise do not establish every risk state, company action, tax rule or payment/exit entitlement.

Thus the existing responses cannot be admitted by a simple field rename or an invented delay. Additional copies of the same share fields, an arbitrary D+1 clock, or a complete market-wide PDF reconstruction would not satisfy the authorized narrow repair. The appropriate next input is a **concrete permitted interface/export and documented version/publication semantics** for the missing share and industry chains, including ordinary-share treatment. This can come from the same service; the review does not require replacing it, purchasing data or contacting anyone automatically. No conclusion is made about all untested RQData products or permissions.

Financial-only partial success does not authorize proceeding as though the full fixed capability sample passed. Given the unresolved structural contract, avoiding a fictitious full-pool binding or performance runner is consistent with the current handoff. A runnable report calculator would not close these dependencies. If later evidence closes them, the original adapter, full-pool, stock-account, runner and complete-card work still remains in the same task scope.

## Implementation review and offline tests

The access patch distinguishes failure stages and exposes only fixed metadata labels and bounded builtin numeric diagnostics. Finite exactly integral floats are normalized; text, booleans, fractions, NaN, infinity and invalid bounds stay rejected. Original receipts are preserved. The retry sequence is grounded in a diagnosed local schema mismatch, not account/proxy switching after a permission denial.

The sample collector fixes the four cases and pre-2025 dates, deep-copies SDK parameters, preserves partial results, uses exclusive output-directory creation, limits observed RPC attempts and saved bytes, and has no strategy entry. I raised the original confusion between local budget stops and access denial; the author separated `PARTIAL_BUDGET_STOP` and fixed failure codes before the completed sample run. The current-instrument metadata limitation was also made explicit before use.

`python -m pytest -q review_code/m10_activation` completed with **40 passed, 0 skipped in 0.20 seconds**. This includes 17 pre-existing tests, 19 new diagnostic tests and 4 new fixed-sample tests. The new tests use synthetic secrets and fake SDK objects only. An initial test fixture included the word CAMPUS in its fake secret and collided with the existing coarse error classifier; the fixture was corrected. Two transient assertions used the preceding diagnostic-shape schema while the author expanded it; their expected schema was updated. Neither was a real-source failure or leaked credential.

The independent local comparison is a separate actual-file check, not counted as those synthetic tests. It returns only booleans and contains no source values. It verifies local hashes and numeric consistency, not source licensing, comprehensive SDK behavior or human acceptance.

## Remaining gates and publication limits

Actual R2 accounts: **0**. Complete M10 cards: **0**. Human acceptances: **0**. Returns and confidence intervals remain null; the original 24 slots remain DRAFT_NOT_AUTHORIZED. Data, execution and full-pool dependencies remain open, so this is not READY_FOR_HUMAN_REVIEW. ETF results stay frozen; R3, post-2024 market/factor/strategy sequences, paper/live, purchasing and automatic merging remain closed.

The license and raw SDK/PDF content are not review-report artifacts. The public terms interpretation and actual contract scope remain the author's documented local-use basis; this review does not grant redistribution, cross-machine transfer, indefinite retention or deployment rights. Final public-tree secret screening, complete cumulative resource totals, pushed SHA and that HEAD's CI are root delivery checks, not outcomes invented here.

Reviewer direct source/network requests, acquired source bytes and cash spend: **0**. Local read/compute time is included in the root ledger; reviewer work occurred in bounded callbacks starting at UTC 16:01:13, 16:08:48, 16:15:31 and 16:24:03 on 2026-11-17. This report is not a human signature.
