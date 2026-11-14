# R1 documentary rule mapping

Status: **STAGING / PENDING INDEPENDENT REVIEW**. This policy admits no dataset and reports no returns.

Generate with `.venv/Scripts/python.exe scripts/create_r1_build_policy.py`. The generator uses fixed v6 inventory/candidate names, checks the frozen 117-row master SHA256, checks every referenced raw source, and records source hashes in `configs/r1_build_policy.json`. Re-running against identical inputs produces identical output. New event evidence requires regeneration and review.

The master contains 110 funds and 117 dated identity revisions, including 159908's 2018 index conversion and six later delisting announcements. Original prospectus/index evidence stays separate from retrospective completeness reports. Historical availability is reconstructed from publication dates; source ingestion uses actual capture timestamps.

| Rule | Mapping and evidence |
|---|---|
| Account | Hypothetical ordinary A-share designated account, domestic equity ETF secondary trading. `account_verified` is a scenario mask, with `actual_broker_permission_observed=false`. MAIN/CHINEXT direct-stock authorization is separate from STAR/BSE direct-stock denial and ETF qualification. |
| Buy lot / tick / sellability | 100 units / CNY0.001 / next-session sellability for secondary-market domestic equity ETF buys. Original product documents and SSE2014/SZ2013 general rules support this scope; dated later texts corroborate unchanged terms. Primary-market creation/redemption and cross-border/bond/cash ETFs are outside this mapping. |
| Ordinary limit | 10%, including ordinary ETF first listing day. Historical exchange texts are attached by source hash; stock IPO exceptions are not applied to ETFs. |
| Qualifying index ETF limit | 20% for indices comprising STAR/ChiNext or other20%-limit shares, SSE from2020-08-21, SZ from2020-08-24. Product identity is dated. Original SZ2020-06-12 special rules plus Aug14 launch announcement are decisive before Aug24; Aug21 list corroborates159915/159949 and is not backdated. SSE's first relevant ETF listing is later than its rule availability. |
| Rule revisions | SSE2020 text is used once conservatively known (Mar17; unchanged ordinary terms bridge Mar13–16); SZ2016 fromMay9. 2023 rules are used only fromApr10. No2023 document is treated as a2020 publication. |
| Limits rounding | Decimal HALF_UP to0.001 using retained provider `preclose` as ex-rights reference, never a guessed yesterday-close replacement. Required execution coverage starts2016. Null warmup limits are permitted only outside execution dependencies. |
| Ordinary dividends | 17 per-event Shanghai issuer notices support `RULE_BASED_SIMULATION` for the hypothetical designated account. Each issuer rule expires at that event's scheduled payment date; actual receipt remains null. No later ChinaClear guide is backdated. Special512320 liquidation is not assigned ordinary-dividend treatment. |
| Shenzhen159922 cash | Original scheduled issuer transfer remains2024-12-03. Applicable ChinaClear2022 guide3.3.1.4 provides R+2 closing clearing and next-session participant transfer: Dec4, conditional on timely full funding. Explicit modeled investor credit is the following exchange session, Dec5, assuming normal settlement/broker processing. It is neither an observed receipt nor a guaranteed worst-case deadline. Actual receipt remains null. |
| Cash stress | Modeled base cash day and predeclared+1/+3 exchange-session delays remain distinct from observed investor receipts. Broker timing is not proved by an issuer transfer date alone. |
| Market clock | Scheduled session endD15, reconstructed public-asofD21, `published_at=null`, unknown vendor first-seen. This is not an original data-vintage assertion. |
| Benchmark clock | CSI observation is datedD; unknown intraday publication conservatively becomes availableD+1 session21. AnchorD → decisionD+1 → executionD+2; delayed executionD+3. |
| Boundary calendar | Official2024-12-23 holiday notice supplies2025-01-02 solely to timestamp the retained2024-12-31 observation. No2025 price or simulation execution is added. |
| Costs | 3bp/minimumCNY5 per actual order is a counterfactual research commission, not an observed historical broker tariff. ETF stamp/stock-transfer components are zero in this scope. |
| Use rights | Private local noncommercial research only; no public raw redistribution or commercial-license claim. CSI/BaoStock evidence remains hash-bound and subject to independent review. |

The provisional amount-only representative union retains 16 instruments. Full accounting/feature history currently applies to 15;159573 remains in the selector/inventory, but its247 listed sessions through2024 never meet the predeclared252-session entry age. Its unresolved2023 split-proof gap is retained under the independently checked dependency waiver; no substitute ETF is selected.

Current documentary gaps:

- None identified by this generator; independent admission remains pending.

Key official sources: [SSE2014 full rules](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988782.shtml), [SZ2013 full rules](https://docs.static.szse.cn/www/disclosure/notice/W020180328432928783546.pdf), [SZ2020 special rules, original June12 dated text](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf), [Aug14 launch announcement](https://www.szse.cn/aboutus/trends/news/t20200814_580660.html), [Aug24 ETF list](https://docs.static.szse.cn/www/aboutus/trends/news/W020200821764606607644.pdf), [SSE20% notice](https://etf.sse.com.cn/ruleguide/business/c/5287913.shtml). Per-instrument and per-event original URLs, dates, captures, and hashes are in the JSON overlay.
