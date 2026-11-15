# Shenzhen ETF cash-dividend settlement evidence

**The official rule supports a scheduled participant transfer on 2024-12-04 for 159922. It supports an explicitly modeled spendable-cash date of 2024-12-05 under normal processing, while actual investor credit remains unknown.** The announced 2024-12-03 date is a fund-custodian transfer date, not evidence of investor cash at that day's open.

## Applicable historical rule

ChinaClear Shenzhen's notice 中国结算深业〔2022〕73号 was published on 2022-12-23 and made its revised ETF registration/settlement guide effective on 2022-12-26. Section 3.3.1.4 requires funding by R+2 at 11:00; after full receipt, ChinaClear sends participant clearing data at R+2 end of day and transfers the cash on the following trading day. Here R is the rights-record date. The cover is PDF page 1; the operative paragraph is PDF page 29, printed page 21. Both were rendered and visually checked. [Official 2022 guide](https://www.chinaclear.cn/zdjs/yszsc/202412/380fe729a3624fa7b52482ea4f455bbc/files/中国证券登记结算有限责任公司深圳分公司交易型开放式基金登记结算业务指南.pdf).

The official 2024 replacement notice states that the next version took effect on 2024-12-23 and simultaneously superseded the version published on 2022-12-23. Therefore, the earlier version covers this early-December event. This later notice is used only to audit historical applicability, not as information available to a December 3 decision. [Official replacement notice, published 2024-12-20](https://www.chinaclear.cn/zdjs/szfgsgg/202412/8d2f0a5fa6554760a48c86de36d39e75.shtml).

## Application to 159922

The original event notice gives the 2024-11-29 record date, 2024-12-02 ex-date and 2024-12-03 announced cash-distribution date. Page 3 specifically explains that funds leave the fund's custodian account on December 3 and that investor receipt follows ChinaClear and sales-institution rules. The November 30 reminder repeats that qualification. [Original November 16 notice](https://disc.static.szse.cn/download/disc/disk03/finalpage/2024-11-15/74c9f510-906c-4a44-84da-69b812348e99.PDF), [November 30 reminder](https://disc.static.szse.cn/download/disc/disk03/finalpage/2024-11-29/bc65c24a-2f1c-4022-bb93-7e65924a0a13.PDF).

| Item | Date | Evidentiary meaning |
| --- | --- | --- |
| R: rights record | 2024-11-29 | Fund announcement |
| R+1: ex-date | 2024-12-02 | Fund announcement and exchange calendar |
| R+2: custodian transfer / clearing day | 2024-12-03 | Announced transfer; clearing occurs at day end under the rule |
| R+3: participant cash transfer | 2024-12-04 | Rule-based schedule, conditional on timely full funding |
| Modeled cash availability | 2024-12-05 open | Explicit additional-session model convention |
| Actual investor receipt | Unknown | Requires receipt/ledger evidence, not inferred |

The 2010–2024 archived exchange calendar verifies these consecutive trading sessions. The rule does not establish an intraday investor-credit timestamp or prove that a broker credited funds before the December 4 market open. Moving model cash to the next session avoids that unsupported opening-time claim. It remains a normal-processing model assumption, not proof of actual receipt or a worst-case upper bound on broker delays.

Recommended data fields are `scheduled_pay_date=2024-12-03`, `participant_transfer_date=2024-12-04`, `modeled_cash_date=2024-12-05`, `settlement_rule_credit_basis=NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER`, and null actual-credit fields. A receivable remains distinct from spendable cash before the modeled date. The project date-only publication policy makes the 2022 rule known at 2022-12-26 21:00 Asia/Shanghai; the rule's legal effective date remains a separate field.

## Captured evidence and limits

Machine-readable evidence: `reports/real_data_phase3/sz_settlement_evidence.json`.

- Operative guide: `data/raw_policy/sz_settlement/chinaclear_sz_etf_2022_09fd2e02a7a3331733fc8fb8dd9f38c6044a88c997509146c2683466a235d728.pdf`, SHA256 `09fd2e02a7a3331733fc8fb8dd9f38c6044a88c997509146c2683466a235d728`.
- Replacement notice HTML: SHA256 `3ce5832f1faafdfd83d34ded326bdb8b977ff894da15574b8a8f4648187b4b13`.
- Original event PDF: SHA256 `7e986b6ba89f02b984f3bdbdc4a3b934294a447c480042172e4f78c864fdd35a`.
- Reminder PDF: SHA256 `9b7a9c3b87511b0f40f5e9616c4ff30c541d06c18045bd19948f48082dac7d1a`.

All raw objects, retrieval timestamps, URLs, hashes, page renderings and the calendar binding are retained under `data/raw_policy/sz_settlement/`. The 2024 guide repeats the participant-transfer mechanism but is not applied retroactively. The older Shenzhen investor-education page concerns the cash-distribution form and then-current ex-date treatment; it does not establish investor receipt timing and is not used for that purpose. The attempted 2022 archive HTML wrapper redirected to today's homepage and is explicitly rejected as evidence, despite HTTP 200.

No Shanghai-specific settlement rule is applied. This finding covers the identified 2022–2024 rule interval and this event; it does not establish all earlier Shenzhen dividend regimes or account-specific broker processing. No market prices, returns, account connections or live transactions were used for this task.
