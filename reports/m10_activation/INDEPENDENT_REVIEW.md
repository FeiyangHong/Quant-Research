# M10 source activation — independent bounded access review

Reviewed 2026-11-17, Asia/Shanghai. Reviewer: a non-author AI subagent, **not a human signer**. Scope: metadata-only access, safe failure handling, preservation of the admission boundary. This reviewer neither read the real credential file nor authenticated, queried market/financial data, contacted a provider, or reran a strategy.

**Decision: PASS for the bounded stop and tested credential-handling paths; source activation remains BLOCKED_ACCESS_OR_LICENSE.** This is not CAPABILITY_SAMPLE_PASSED, full-pool admission, or READY_FOR_HUMAN_REVIEW.

## Evidence and what it establishes

The supplied activation handoff, M10_PLAN, DELIVERY_POLICY, SAMPLE_PLAN, production probe and ACCESS_RECEIPT were read directly. The user supplied a new actual education-license input, so this attempt is materially different from the earlier source inventory. The receipt records one SDK initialization with version 3.8.2, failure code EDUCATION_NETWORK_REQUIRED, zero explicit quota calls, zero market/financial requests and zero R2 accounts. Authentication is NOT_VERIFIED; historical capability is NOT_TESTED; applicable use is NOT_VERIFIED. SDK internal requests and wire bytes remain null, rather than being invented as zero.

The actual provider outcome is **author-observed and summarized in the sanitized receipt**. I did not independently repeat authentication or view a raw error that could contain credentials. I independently checked that the classifier maps an education-network denial to this specific outcome and does not serialize its original exception. No conclusion about key validity, available historical modules, expiry, quota, financial version quality, or all-campus availability follows from this denial.

The correct next prerequisite is execution from a network actually permitted by this education license, with applicable research/use/storage terms established before data retrieval. Changing proxies, sharing credentials, repeatedly requesting from the same rejected environment, or inferring a new commercial authorization would not resolve this gate. All historical dates remain pre-2025; no default-latest data call is present in this probe.

## Independent probes and author revision

The independent test file uses only freshly created synthetic credential strings and an in-memory fake SDK; it has no real provider dependency or network requests. Expected outcomes are fixed from the task contract, not derived from a real account or performance output.

| Check | Result |
|---|---|
| Empty/comment-only/empty quoted/multiple values reject before authentication | PASS |
| Shell-substitution/separator/backtick examples and connection URI reject as configuration | PASS |
| Education-network exception and SDK stdout/stderr containing a synthetic secret do not publish that secret | PASS |
| Successful fake authentication/query publishes only metadata and never grants data/strategy admission | PASS |
| Unknown response keys containing credentials/account identity are not persisted | PASS |
| Unexpected secret-valued entries under each allowlisted quota key are not persisted | PASS |
| Quota failure preserves one successful authentication and one explicit attempted quota call without logging the exception | PASS |
| Existing receipt prevents another request and preserves original bytes | PASS |
| Actual receipt retains null internal counters, zero accounts and NOT_TESTED historical capability | PASS |

Static review identified one substantive defensive gap: the original quota projection allowed arbitrary values under allowlisted keys, so a malformed response could serialize sensitive strings. The author added strict integer metadata validation and a fixed license-type enum; unknown types are anonymized. The independent malformed-response probes pass on this revised code. This was an engineering fix after the real failed authentication; no new authentication was performed, and the actual run never reached the quota projection.

A documentation discrepancy was also identified: initial SAMPLE_PLAN language allowed a named connection setting, while the implemented parser rejects connection URIs and accepts only a raw or named license. The appended implementation clarification preserves the original plan and states the actual boundary. No URI was used in the real attempt.

## Reproduction and binding

Command from the safe checkout:

```powershell
& 'F:\QuantTrade\Quant-Research\.venv\Scripts\python.exe' -X utf8 -m pytest -q review_code/m10_activation/test_access_independent.py
```

Result: **17 passed in 0.29s**, zero skips. The first reviewer-only invocation had a test-discovery path error and ran no probes; that local test harness path was corrected before the reported run. No production change was needed for that harness error.

At review, repository HEAD was `dff161b3554760b765a22c121a107f64802482ea`; the original audited base remains `d54bdc897c56163caef7507ac159c7cc50ef92f7`. The final delivery commit/CI belongs in the root publication receipt, not an invented self-referential hash here.

| Reviewed object | SHA256 |
|---|---|
| Revised scripts/m10_rqdata_access.py | `4a8459b779668695dbf2bb9b50ddc8418f03770be41af4f20358acec1be8026b` |
| Actual ACCESS_RECEIPT.json, unchanged after probe | `192a13f665c0d3fed829c0006b972b2e3aaa31d32779e0f050333dc14e271de8` |
| SAMPLE_PLAN.md including implementation clarification | `19e1d7725e695d41d0e1b03e102ed64320d793e036090027acde40e6c69b28bc` |
| Independent test file | `4b8043a337a2eb39c531626f14cb3753574aebde52310271a9c8977d2404fd52` |

The revised-code hash binds the independent offline tests, **not** the earlier real authentication executable. The real attempt's code provenance should remain separately recorded; it must not be silently rebound to the revised file. This distinction does not erase the observed denial or justify another authentication attempt.

## Research and verification limits

Historical financial samples, whole monthly universe/size denominators, original/revised fact chains, stock execution wiring, complete M10 case cards and human acceptance have not advanced through this access attempt. R2 real registrations/accounts remain 0/0, the 24 slots remain DRAFT_NOT_AUTHORIZED, and returns/IC/CI remain null. Current complete M10 cards and human acceptances remain 0/0, not merely pending signatures on 20 finished cards. The five existing documentary pairs and three quarantines are preserved.

This review does not certify every possible malformed SDK object, abrupt process termination, raw-data licensing, host network configuration or provider completeness. There was no reason to rerun old ETF or stock engineering accounts. Reviewer resource use: zero external requests, zero newly acquired source bytes, zero cash; local review and test time is included in the root's conservative two-agent session ledger.
