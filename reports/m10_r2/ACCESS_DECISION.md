# 2026-11-18 校园恢复增量

当前访问已通过；18财务+8结构固定调用已实测，13必要原件hash匹配。四组有限财务比对通过，但股本/行业历史公开、可得和版本链未准入，整体仍 **BLOCKED_DATA_CAPABILITY**。详见[当前实证、具体字段缺口和下一输入](../m10_activation/CAMPUS_RESULTS.md)。不将下方旧机访问/原件库存状态当成本机现状；原困难队列和冲突保留。生产适配、全池、股票执行/runner未完成，完整卡0、human0、实际R2账户0，24草案与null绩效不变。AI复核不替代human；尚不可集中请求签不完整卡。

## 以下为保留的先前阶段记录

# M10 source decision — BLOCKED_DATA_CAPABILITY

## 2026-11-17：M10_SOURCE_ACTIVATION_V1 当前状态

**BLOCKED_ACCESS_OR_LICENSE / EDUCATION_NETWORK_REQUIRED。** 用户已提供本人RQData教育license并保存配置；实际SDK初始化被教育网限制拒绝。已停止请求：1次初始化、0显式quota、0行情/财务、0真实R2账户，SDK内部请求/字节未知。历史能力未测试，不判断密钥无效或供应商无PIT。下一步是执行电脑使用许可证认可的校园网络，再恢复[固定样本计划](../m10_activation/SAMPLE_PLAN.md)。[本次结果与去敏证据](../m10_activation/RESULTS.md)。数据/执行缺项、完整卡0、human0和原24格未授权状态不变。以下2026-11-16内容保留为历史来源裁决。


Decision date: 2026-11-16, Asia/Shanghai. No real R2 strategy account has been run. Existing free-source archives are accessible and reusable, but none is an admitted main source for the full 2016–2024 stock universe, financial versions, historical status/industry/share chains and company actions. Stop Stage A data probing at this evidence boundary; do not start a 20-company web reconstruction or a new provider adapter.

The primary status is **BLOCKED_DATA_CAPABILITY**, because actual archived access exists but the necessary historical capabilities have not passed. A separate access condition remains **ACCESS_NOT_VERIFIED** for any adequate full-PIT subscription or export: none is configured or verified in the inspected project scope. This does not assert that the user has no external subscription or that free reconstruction is impossible. Official API documentation describes candidate capability, not account entitlement, complete returned versions or a license.

## Scope and actual access evidence

The read-only inventory examines the original private project at `F:/QuantTrade/Quant-Research`: six `configs/*.json` files, `pyproject.toml`, 89 Python files under `src/` and top-level `scripts/`, and the explicitly enumerated M3–M6 evidence files. The project pins BaoStock 0.9.4 as an optional dependency. Existing code implements BaoStock, Eastmoney historical share requests and official-document acquisition. There is no declared RQData/Tushare/JQData/Wind/Choice connection or provider export path in this scope. Literal project Python environment declarations number zero, so zero environment names or values were inspected. No credential directories, account stores or unrelated user paths were searched.

| Provider / route | Configured | Access verified | Covered fields and PIT evidence | License scope / remaining limitation |
|---|---|---|---|---|
| BaoStock 0.9.4 | Existing project collectors; anonymous mode | Prior successful M3/M4 responses exist locally; no new M10 authentication/availability check | Historical membership/date samples, raw daily prices, volume/amount, daily `isST`, vendor industry. Historical names can contain later names; `isST` misses delisting-risk states. Observed financial endpoints lack retained revision chains and required raw R2 statement fields; observed daily endpoint has no ordinary-share contract. | Archived platform description supports local personal research/API/storage. No general raw redistribution or commercial resale inference. |
| Eastmoney `RPT_F10_EH_EQUITY` | Existing M5/M6 bounded collector | Three M6 success receipts and raw responses; no new M10 service request | 1,000 broad event rows plus 122 five-ID rows; five structural share counts reconcile with originals. `END_DATE` and `NOTICE_DATE` demonstrably differ. No verified original-publication/revision/complete-event contract. | M6 explicitly records historical-data license verification false. Accessible endpoint is not permission to redistribute or an admitted full-history feed. |
| Exchange/issuer/CNInfo official originals | Existing bounded document collectors and archived PDFs | Raw files independently hash-checked in this inventory | Five documentary original/revision pairs, three quarantined conflicts, limited industry/status/action evidence. Official originals establish only their specific facts and publication evidence. | Retained locally as research evidence; public reachability does not establish broad republication rights. |
| Full-PIT subscription or frozen whole-pool export | Not configured or verified in inspected scope | **ACCESS_NOT_VERIFIED** | No actual response/export to bind or adapt. RQData/Tushare documentation is not a substitute. | Local calculation/storage/derived-publication rights, expiry, quota and prices all **UNKNOWN** until an actual source is identified. |

The separate [official capability check](OFFICIAL_CAPABILITY_CHECK.json) confirms that Tushare's income documentation lists `ann_date`, `f_ann_date`, `end_date`, `report_type` and `update_flag`; the FAQ explains initial/revised flags. Those fields are capability clues, not proof of complete version chains, authenticated access or broad storage/publication rights. The current RQData page fetch timed out twice and was stopped; its candidate capabilities come from the supplied handoff and were **not independently verified from a current page in M10**. No additional data-service probe is warranted without a configured main source.

## Dependencies preventing use as an R2 main source

1. Complete historical main-board/ChiNext identities, including later exits and renames, with historical boards, listings and risk/permission states. One observed 3,779-ID snapshot is not the full historical denominator.
2. Complete share-class events and their public/effective clocks, including A/B/H ordinary shares and exclusion of preferred/nonordinary shares. Formal PIT capitalization is null for every one of the 3,779 snapshot records.
3. One historical industry scheme, classification version transitions and issuer assignment/public/effective clocks. The observed official quarterly table and vendor weekly snapshot do not cover subsequent changes.
4. Original and revised consolidated raw financial fields, period/comparison identities, reliable public clocks and complete filing inventories. Latest-public-period completeness and a registered disclosure/freshness treatment remain unresolved.
5. Full raw-market/liquidity histories, action and exit-entitlement chains, and source-backed applicable execution/fee evidence. The prior two Moutai dividend accounts remain blocked by the 2022 transfer-fee evidence gate; actual broker cash/tax records are unverified.
6. At least 20 complete nonduplicate original/revision review cases and independent **human** acceptance. Current archive: 20 candidate correction PDFs, five paired documentary cards, three quarantines, zero human acceptances. Those counts are distinct. Even 20 accepted examples would not establish full-pool completeness.

## Resource decision and stopping condition

This inventory made **0 external requests**, acquired **0 new source-response bytes**, and spent **0 cash**. Existing local objects read for hashes total 101,060,224 bytes by distinct referenced path; these are reused bytes, not M10 acquisition. Root's official-document checks, delivery operations and cumulative session time are recorded in the central M10 budget; they are not silently included in these zero inventory counters.

Stage A closed at 2026-11-16 07:47:26 UTC after 6 official-document request equivalents, zero SDK/new-market requests and 52,441 saved decoded web-tool-response bytes; the root's closeout measured 0.8965 aggregate agent-hours. Hidden backend/wire requests and bytes are unknown. The six equivalents include both failed RQData opens and the Tushare section views. These are the Stage A totals, separate from this inventory's zero network use and from later local preparation/delivery time.

Estimated full acquisition cost: **UNKNOWN** for requests, bytes, entitled quota, agent effort, human effort and money. The historical M6 linear estimate of 389 requests / 398,879,433 bytes describes all-provider share events from two sample pages; it excludes financial versions, market/status/industry/actions and is not a target-pool M10 acquisition estimate. The 4,096-request, 8-GiB, 24-aggregate-hour task limits are ceilings, not evidence that collection will fit. No bulk acquisition is authorized by this document.

The single required user resource decision is to identify an **already authorized service or frozen export** and its available scope for these dependencies, with a local configuration/export location and permission to compute, store and publish allowed derived results. Keys stay in local configuration. If no such source exists, keep M10 stopped pending a separate source/budget choice; no purchase, trial, supplier contact or substitute survivor sample is implied. Human review remains a separate subsequent requirement, not the only blocker.

Evidence and reproducibility: [COVERAGE_REPORT.md](COVERAGE_REPORT.md), [COVERAGE_REPORT.json](COVERAGE_REPORT.json), [DATA_CONTRACT_ADDENDUM.md](DATA_CONTRACT_ADDENDUM.md). Raw files stay in the original private archive. No M9 rerun or 2025-and-later market/factor/strategy data was opened.
