# M10 independent verification

2026-11-16. Independent AI reviewer; no human signature or performance authorization. Overall research status remains **BLOCKED_DATA_CAPABILITY / NOT_RUN**. This file separates reviewer-run checks from author checks and final CI.

| Reviewer-run check | Observed result |
|---|---|
| `python -X utf8 review_code/m10/inspect_existing_evidence.py` | 20/20 queued PDFs match; 31 unique case/fact source hashes match; 5 pairs / 3 quarantines / 0 human; 22 page value tokens and 22 fact clocks pass; 9 pre-2025 card clocks pass; 1 2025-availability metadata record excluded from revalidation; 2 Decimal factor calculations match. |
| `python -X utf8 review_code/m10/check_archive_manifest.py` | 270/271 references match; all 265 raw archive references match; no missing paths. Historical `scripts/m4_data_feasibility.py` mismatch retained separately. |
| `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe -m pytest review_code/m10/test_independent_m10.py -q` | 34 passed; no skips. Narrow synthetic valuation, historical-prefix, invalid-input, provenance-identity, closed-holdout, draft-matrix and forged-preflight probes. |
| `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe scripts/m10_preflight.py` | Draft valid, permission false, real accounts 0, metrics null, status NOT_RUN_BLOCKED_ADMISSION. |

The exact final reviewer execution output and source-content bindings are in [verification_receipt.json](verification_receipt.json). The preliminary valuation/draft suite had 31 passes; three additional preflight adversaries brought it to 34. Those are not independent 65 tests and are not human cases. No full M9 rerun or strategy matrix was performed.

The source-inspection scripts are standard-library, offline read-only tools. They need the existing private source objects at their retained paths; absent objects must fail visibly, not be silently downloaded or replaced. PDF checks also require local `pdftotext`. The Python environment above is reused only to run the focused test dependencies. No existing reports, datasets, raw objects or human cards are rewritten by these checks; only M10 outputs are written.

The 34 independent tests do not import the author's test fixtures or expected-factor values. Expected cap/factors use separate Decimal expressions; fixed matrix assertions derive from the handoff. The legacy evidence calculation imports no production financial functions. Tests are bounded engineering verification and cannot satisfy source authenticity, exhaustive filing/whole-pool coverage, actual payment/tax evidence or human acceptance.

The author's focused regression and final public CI are separate evidence owned by the root publication packet. A remote CI job for this M10 HEAD must be reported from its actual status; the previous M9 CI is not reused. Raw-dependent skips, if any, must be disclosed separately from passes.

Reviewer external-source requests: **0**; new source-response bytes: **0**; purchases: **0**. Existing private bytes were hashed in place. M9 artifacts and final holdout remained frozen. Session use is recorded centrally; AI session time is not human review time.
