# M5 test portability addendum

This packaging change leaves production behavior and the original independent review outcomes unchanged. It separates portable numerical/contract tests from integrations requiring locally archived source bytes. The accounting 42-test and financial 25-test reviews remain historical snapshots; their JSON files gain a separate portability addendum with current test hashes.

`tests/fixtures/m5_verified_calendar_2015_2024.json` contains 2,431 actual sessions from 2015-01-05 through 2024-12-31. It is the sorted unique union of the existing verified development/validation calendars restricted to that interval, explicitly real-derived and not synthetic. It contains dates, provenance, and hashes, without vendor prices or raw vendor response files.

| Item | SHA256 |
|---|---|
| Committed derived calendar | `d2975e5273586d38907a6cb0784a70d0b92261d57cca54cb9015539809538103` |
| Development source calendar | `8200cca2c04cc847ebddf43c0783ff1b8d15b28a9d11e48a3b3f51661c4e52ae` |
| Validation source calendar | `be8124db8fbc33b9162df4948f6669c0e17fc89f3251b0027ce41687e28c3526` |

Both financial suites always load the committed calendar. The 22 independent transcribed amount/page/unit comparisons and all factor/prefix/latest/freshness/capitalization assertions always run. Six separate `archived_source` tests verify the original PDF hashes when the files exist; only those byte checks skip when an original is absent. A corrupt existing file still fails.

The accounting end-to-end registered-rule digest rejection remains an archived integration, with an explicit skip when its original calendars, budget, raw wire, rule, or event files are unavailable. Its complete original assertion still executes locally. An additional portable hash-contract test independently checks rejection of a wrong digest and acceptance of the exact digest. Synthetic accounting mechanisms and the three committed raw-input conditional source-scenario oracles remain active.

The market reviewer adapted both source-conflict mutations to explicitly invented temporary ledgers and a minimal 3,779-identity test pool, running the actual report builder and preserving the conflicting-source rejection assertions. The late-notice contract uses retained real candidate/rejection rows in the committed summary. A separate archived integration checks the complete original provider response and hash when present; absolute archival paths are rebased to the current checkout. The temporary calendar uses the same committed verified calendar.

The optional BaoStock transport dependency is replaced only inside its wrapper-contract test by an isolated in-memory module with the same `send_msg` entry point. The collector's real wrapper still performs message-date rejection, durable request charging, and failed-terminal-state assertions. This makes the test run without an ignored local SDK directory and performs no network request.

The `archived_source` pytest marker describes only source-byte integrations. Original raw files remain local; no vendor source object, original PDF, or SDK source tree was added for CI. New tests/configuration and the derived calendar are the portable artifacts. Exact local/clean-data counts, skipped scope, current hashes, and UTC interval are recorded in `PORTABILITY_ADDENDUM.json`; the root agent performs the final whole-repository suite separately.

Final clean-data simulation: **143 passed, 8 skipped in 17.38 seconds**. The scratch source snapshot contains the proposed code/tests/reports and fixture, with no original `data/` or `work/` trees. The exact skips are six original PDF hash tests, one original accounting builder integration, and one original market-provider response/hash integration. All other M5 tests run. Local verification retained **109 passed, zero skipped** across the changed financial/accounting/budget suites and **4 passed, zero skipped** in the market suite, so the original-byte checks still execute where sources exist.

The final whole-repository result is reported by root separately; this addendum does not replace it. Conservative portability session starts at 2026-11-15 11:29:00 UTC (first captured clock 11:29:07 UTC); completion and elapsed occupancy are in the JSON. Parallel market-review time belongs to that reviewer's separate interval and is not silently counted as this agent's time.
