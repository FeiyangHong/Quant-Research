> 2026-11-18后续更正：[替代接口复核与实证](../m10_activation/OFFLINE_ALTERNATIVES_RESULTS.md)已确认PIT股本字段可返回公开日锚点，茅台一项原件比对通过。来源整体能力未被否证，股本事件/行业组合仍待验证；原来源请求子预算现已64/64，停止继续联网，不自动续额。当前完整数据未准入，0完整卡/0human/0真实R2不变。下方前轮记录涉及外部输入为唯一下步的表述已被更正。

# 2026-11-18 校园恢复增量

当前访问已通过；18财务+8结构固定调用已实测，13必要原件hash匹配。四组有限财务比对通过，但股本/行业历史公开、可得和版本链未准入，整体仍 **BLOCKED_DATA_CAPABILITY**。详见[当前实证、具体字段缺口和下一输入](../m10_activation/CAMPUS_RESULTS.md)。不将下方旧机访问/原件库存状态当成本机现状；原困难队列和冲突保留。生产适配、全池、股票执行/runner未完成，完整卡0、human0、实际R2账户0，24草案与null绩效不变。AI复核不替代human；尚不可集中请求签不完整卡。

## 以下为保留的先前阶段记录

# M10 local coverage inventory

## 2026-11-17：M10_SOURCE_ACTIVATION_V1 当前状态

**BLOCKED_ACCESS_OR_LICENSE / EDUCATION_NETWORK_REQUIRED。** 用户已提供本人RQData教育license并保存配置；实际SDK初始化被教育网限制拒绝。已停止请求：1次初始化、0显式quota、0行情/财务、0真实R2账户，SDK内部请求/字节未知。历史能力未测试，不判断密钥无效或供应商无PIT。下一步是执行电脑使用许可证认可的校园网络，再恢复[固定样本计划](../m10_activation/SAMPLE_PLAN.md)。[本次结果与去敏证据](../m10_activation/RESULTS.md)。数据/执行缺项、完整卡0、human0和原24格未授权状态不变。以下2026-11-16内容保留为历史来源裁决。


**BLOCKED_DATA_CAPABILITY. Real R2 performance: NOT_RUN.** The counts below describe reused source evidence, not coverage percentages for the 2016–2024 strategy dataset. No new source request was made. No 2016–2024 month-end common pool is verified: **0 of 108 requested monthly anchors**. The historical universe denominator is unknown; it is not 3,779 for every month.

## What is actually retained

| Evidence | Actual count | Interpretation |
|---|---:|---|
| M4 2020-07-31 all-security response | 4,810 rows | Includes securities outside the registered stock scope |
| M4 all-A daily response | 3,923 rows | One date only |
| M4 main-board/ChiNext snapshot | 3,779 identities | 2,946 main-board, 833 ChiNext; provider snapshot, not independent exchange completeness certification |
| Snapshot raw price, volume, amount, trade status and daily `isST` | Each 3,779 / 3,779 | Observed fields; full risk state and historical available-at clock remain unproved |
| Vendor historical industry | 3,772 / 3,779 | Weekly snapshot; `updateDate` is not an original-publication/effective clock |
| Official 2020Q2 industry | 3,749 / 3,779 | Public by snapshot; 2020-07-15 21:00 conservative availability; intervening changes incomplete |
| Complete risk state, listing-age history, 60-day liquidity, corporate-action chain and financial-version chain | Each 0 / 3,779 admitted | Unknown dependencies, not proven ineligible securities |
| M5 share structural samples | 5 | Original-document value crosschecks, no full PIT chain admission |
| M6 broad share batch | 1,000 event rows / 498 identities | 330 identities appear in the fixed snapshot; appearance is not complete share coverage |
| M6 five-ID batch | 122 event rows | Overlaps the structural samples; not 122 additional securities |
| Formal PIT shares / capitalization in fixed snapshot | Each 0 non-null / 3,779 | No size threshold or full denominator can be computed |
| M3 correction-PDF candidate queue | 20 | Candidate announcements, not accepted original/revision cases |
| M4 attempted issuer/period pairs | 8 | Five documentary pairs; three quarantined conflicts retained |
| M5 canonical financial table | 22 field-version rows / 6 PDF hashes | Two numerical engineering cases; F01 null in each; full latest-report coverage remains unverified |
| M5 report-coverage contracts | 4, all partial | Not complete issuer histories |
| Existing human-review cards / signatures / accepted cases | 5 / 0 / 0 | Five paired documentary cards, not five fully admitted M10 cases or 20 human acceptances |

The snapshot retains 212 daily `isST=1` records and 28 suspended records. The remaining 3,567 `isST=0` records cannot be certified free of all delisting risks. Missing facts are not removed to make a denominator or coverage ratio look complete. The 121 vendor/official raw industry-code differences include taxonomy-version differences; no invented crosswalk was applied.

The three quarantines remain: Jingfeng 2023 parent-net-profit conflict of CNY 0.01; Ningke 2022 contradictory revised cash-flow text/tables; Ankao 2021H1 asset conflict of CNY 0.01. The 2024-12-31 Infotm correction is not available inside the 2024 investment horizon under the existing date-only clock. It is documentary audit material, not a pre-2025 revised signal input.

## Existing event acceptance is limited

| M6 engineering case | Recorded result | Actual archived account facts |
|---|---|---|
| Kangmei ST | PASS | 41 days; two buys; retained blocked holdings. This establishes a fixed event-engineering case only. |
| Moutai ordinary dividend | BLOCKED | 34 days; zero fills/zero dividend-event holdings; missing accepted 2022 transfer-fee evidence |
| Moutai special dividend | BLOCKED | 35 days; zero fills/zero dividend-event holdings; same fee evidence gap |

All three have `broker_ledger_verification=UNVERIFIED`. Conditional expected dividends or tax outputs are not actual accepted dividend-position replay evidence. The published-payment-date-plus-one-session policy remains a model; actual payment/debit dates remain unverified. No event replay was rerun for this inventory.

## Hash verification and reproduction

The explicit metadata indexes yielded **271 distinct referenced path/hash pairs**: 270 match, zero missing, one historical-code mismatch. All **265 raw archive objects match**. There are 271 distinct expected content hashes and 101,060,224 reused local bytes by distinct path. These include source payloads and a small number of derived/calendar/code dependencies; counts are not independent cases or new downloads.

The preserved discrepancy is `scripts/m4_data_feasibility.py`: old M4 manifest SHA256 `87f2a965204b5a62923643e8c056f5525cb5d7ef979f52325b47efea5646fe70`, current private-checkout SHA256 `aa518913cee7f57a179b9887a244df9cc869d96904d5e92a5829d4a3a4632e8a`. The M4 report describes a collector SDK-import correction after stopping without rerun; this inventory does not certify exact historical executable identity or change old files. The mismatch is explicit in JSON and does not invalidate the separately matching raw payloads.

Run from the public checkout, with the original archive available:

```powershell
& 'F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe' scripts/m10_source_inventory.py --archive-root 'F:/QuantTrade/Quant-Research' --output reports/m10_r2/COVERAGE_REPORT.json
```

The script uses only local standard-library reads and writes metadata to its explicit output. It does not import collector modules, make network calls, decode raw payloads, generate factors/accounts or discover credentials. The exact evidence paths, file sizes, hashes, configuration scope, declared-environment presence and individual hash results are in [COVERAGE_REPORT.json](COVERAGE_REPORT.json). Missing raw bytes fail the command; recorded historical code drift stays visible. This command reproduces the inventory, not the historical strategies or a new admission decision.
