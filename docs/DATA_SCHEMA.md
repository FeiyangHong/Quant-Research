# 离线数据 Schema v1

版本 `r1-offline-1.2`；2026-11-15；时区 `Asia/Shanghai`。实现为 `src/quant_research/data.py`。继续读取1.0/1.1快照。本 Schema 为 R1 离线工程接口，不替代 `DATA_CONTRACT.md` 的真实数据证据要求。

## 文件与类型

一次快照为独立目录：`manifest.json`、`calendar.json`、`instruments.json`、`bars.json`、`actions.json`、`benchmark.json`。表文件包含显式 `columns` 与 `records`，空表也保存列名。日期为 `YYYY-MM-DD` 字符串；时间必须携带 `Z` 或 `+/-HH:MM` 时区；空值为 JSON `null`，不得使用 NaN/Infinity。持久化不保存 pandas 行号，版本键才是记录身份。

`manifest.file_sha256` 保存五个数据文件的 SHA-256。加载时逐个核验，缺 hash 或内容不符即拒绝。快照目录不可覆盖为不同内容，同内容重复保存幂等；更正必须新建 dataset_version/路径。manifest 本身由运行级文件清单 hash 绑定；内部 SHA-256 只能检测内容漂移，不能证明外部供应商真实性或授权。

Python 接口：

```python
Dataset(calendar: list[str], instruments: pd.DataFrame, bars: pd.DataFrame,
        actions: pd.DataFrame, benchmark: pd.DataFrame, manifest: dict)
synthetic_dataset(seed=20261114) -> Dataset
save_dataset(dataset, path) -> dict  # 返回带文件 hashes 的 manifest
load_dataset(path, allow_unverified=False) -> Dataset
audit_dataset(dataset) -> dict
asof_records(frame, cutoff, keys) -> pd.DataFrame
master_asof(dataset, cutoff) -> pd.DataFrame
bars_asof(dataset, cutoff) -> pd.DataFrame
date_only_available_at(publication_date, calendar, extra_delay=0) -> str
```

`load_dataset` 默认拒绝结构错误和证据阻断。`allow_unverified=True` 只供审计/隔离读取，仍拒绝结构错误，不改变审计结论，不构成研究准入。

## 主键与字段

所有表具有 `available_at`、`revision_id`、可空 `supersedes_id`。不同记录的 revision ID 可以局部命名，修订引用限于同一经济主键。主键冲突、同一经济键的同一可用时间多版本及不存在/不早于当前的前序版本都不能静默去重。

| 表 | 经济主键 | 专属字段 |
|---|---|---|
| calendar | 日期本身 | 排序、唯一、非空 ISO 日期列表；真实数据必须是已核验交易所日历 |
| instruments | instrument_id | asset_type, board, listed_on, delisted_on, account_verified, benchmark_id, industry, lot_size, tick_size, t_plus, strategy_universe |
| bars | instrument_id + date | open, high, low, close, volume, amount, upper_limit, lower_limit, suspended, total_return_index |
| actions | action_id | instrument_id, action_type, announcement_date, ex_date, record_date, pay_date, cash_per_share, share_factor, recovery_per_share |
| benchmark | date | total_return_index |

- `asset_type` 为 `ETF` / `STOCK`；`board` 为 `MAIN` / `CHINEXT` / `STAR` / `BSE` / `ETF`。ETF 产品资格独立，不能由成分股板块推断。`account_verified` 只接受布尔值，字符串 `"true"` 无效。历史研究资格、账户订单资格、代理资格仍由策略与风险模块分别形成。
- `listed_on` 为上市首日；`delisted_on` 为第一天不再挂牌的日期，可空。历史证券永远留在主表。未知的未来退市日应为 null；公告后通过新增主表修订给出，不得回写旧记录。`master_asof` 保留已退市身份，由使用方按所需日期判断新增资格，存量持仓不得被过滤掉。
- `strategy_universe` 显式指定 `R1B` / `R1I` 等用途；当前工程只开放 R1B。benchmark_id 为基金跟踪的指数类别。industry 必须为历史已知分类，不能拿当前分类回填；R1B 宽基夹具使用 `BROAD_MARKET`。
- `lot_size` 为买入最小整数单位，`tick_size` 为人民币报价单位，`t_plus` 为卖出可用延迟。真实历史交易规则仍须独立、版本化有效区间核验，主表几个数值不能代替完整规则表。
- bars 是**原始未复权价格**；价格/金额单位人民币元，volume 为股或基金份额。数值必需有限，OHLC 必需一致；每日最终数值不能在当日15:00之前标记为已可得。upper/lower_limit 是该日该品种已核验的价格边界，不按当前板块统一臆造。当前 MVP 必需完整数值；真实“无涨跌幅限制”时期、缺报价或特殊上市阶段应扩展版本化规则模型后再准入，不能塞入 Infinity 或伪造限价。
- suspended 必须布尔值；停牌记录为显式零量零额。缺记录与停牌不同，审计会逐品种报告挂牌区间缺失交易日。停牌行中的估值价格必须在上游来源中解释，不能用于成交。
- total_return_index 为独立总收益序列，只在事件已生效后纳入公司行为；不用于成交价，也不能与账本现金分红重复记收益。benchmark 为已在 manifest 固定定义的单一总收益基准，不接受价格指数冒充。
- actions 支持 `CASH_DIVIDEND` / `SPLIT` / `DELISTING` / `LIQUIDATION` / `LIQUIDATION_PAYMENT`。cash_per_share 为原持仓每股/份现金，share_factor 为新股数/原股数（普通事件为1），recovery_per_share 未知必须 null。正清算回收使用独立付款事件，不能塞入DELISTING。record_date 表示本模型记录权益的前一持仓日期；真实不同登记/到账机制需要适配并审计。pay_date 为空不代表已经到账。配股、合并等其他事件类型当前阻断，不伪装成已支持。

### 1.1清算扩展

两类清算事件均要求 `terms_verified=true` 与非空 `source_url`。`LIQUIDATION.ex_date`是账务上将交易份额转为权利的日期，不声称该日法律上注销；必须晚于record_date。`LIQUIDATION_PAYMENT`额外要求 `entitlement_action_id`、唯一 `installment_id`、布尔 `is_final`、`recognition_date=ex_date`、`pay_date`和显式 `settlement_mode`。

`SCHEDULED`及`LATE_RECOGNITION`要求 `cash_settlement_verified=true`；后者仅用于较晚得知付款的观察时间回放。`ASSUMED_SCHEDULED_CREDIT`只模拟公告安排的发放日，输出actual_pay_date=null及scheduled_pay_date。迟到确认和未经规则支持的假设到账仍阻断真实Dataset准入。1.2另提供下述明确区分的规则模拟；不以该模式伪造个人账户流水。金额未知时保留权利及估值不确定性，不填造回收额。详见[执行模型](EXECUTION_MODEL.md)。

### 1.2 份额、资金和数据依赖

`SPLIT.effective_phase`为BOD或EOD；`rounding_policy`为EXACT/FLOOR/CEIL，后两者按账户合计取整并要求原始条款。`action_status=CANCELLED`保留取消记录而不改变数量。原公告的除权日和日终登记日不同时，`source_ex_date`保留公告除权日，账本`ex_date`使用实际生效日期并结合phase；两者不可混淆。`PRE_LISTING_METADATA_ONLY`只允许上市前的事件，登记日未知可null，不再调整已按上市后单位报价的行情。晚公布比例通过独立TR时钟控制，持仓时条款未知仍阻断。

`RULE_BASED_SIMULATION`用于有当时公告及适用清算规则支持的假设指定交易账户。需登记规则URL、有效区间、可用时间、事件适用类型和账户模型；`actual_pay_date=null`且不能设置实际收款已验证。`pay_date/scheduled_pay_date`保留公告日期。若该日期只是托管划出日，另记录`participant_transfer_date`、`modeled_cash_date`及`settlement_rule_credit_basis=NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER`；引擎核验模拟到账为结算参与人划付后下一交易日。普通分红规则不能自动用于清算。固定现金延迟0/1/3交易日从已说明的模拟资金可用日开始。

`bars.available_at`始终控制原始行情和成交额；`total_return_available_at`独立控制总收益特征。晚到的公司行为条款不能使已公开成交额消失，或改变季度代表。`bars_asof`和策略均屏蔽未到可用时间的TR，保留可用原始行情。

`representative_dependencies`由全候选原始成交额及当时主表独立重算，保存完整代表名单与必要特征依赖。非代表、2015年前不被使用的暖启动TR允许为null，标记`REPRESENTATIVE_SELECTION_ONLY`，不能填0。若基金直到样本末仍不足252个挂牌交易日，可独立证明其永远不能进入本轮信号，保留代表竞争及明确依赖豁免；不能因缺数据替换代表。实际执行所需限价必须完整；未被执行使用的候选和2016年前暖启动允许限价未知，原始数值继续保留。

### BaoStock观察区

`providers/baostock.py`输出的 `baostock-observations-1.0` 是另一种暂存格式，不是上述Dataset。它保留供应商原值、精确量额、原始状态及哈希；缺失的available_at、限价、TR和公司行为继续缺失。`real_data.audit_collection`核验文件链和观察覆盖，但不能自动设置任何evidence_gate为VERIFIED。清单标记SUCCESS只代表接口成功，不代表完整历史或策略数据验收。

## 可用时间与修订

决策截止默认交易日21:00。`asof_records` 先过滤 `available_at <= cutoff`，再按经济主键选最新可见版本；未来版本不会覆盖过去查询。cutoff 也必须带时区。同时间版本歧义直接报错。

只有公告日期 D 时，`date_only_available_at` 取严格晚于 D 的第一个交易日21:00；`extra_delay=1` 再加一交易日。交易最早仍是该决策后的下一交易日。日历覆盖不足即拒绝推算。精确时间保留时区并转换比较，21:00之后与海外尚未收盘的数值不可提前进入。

真实表额外要求：`published_at`, `publication_precision`, `vendor_first_seen_at`, `ingested_at`, `processed_at`, `availability_mode`, `source`, `endpoint`, `source_record_id`, `raw_object_hash`, `license_profile_id`, `quality_status`。原始对象 hash 为64位小写 SHA-256。

允许模式为 `historical_public_asof` / `historical_vendor_asof` / `live_capture`。真实历史下载时间仅作为 ingested_at；不会用它冒充历史首可用。公开历史重建的 available_at 下界取公开时间及日期精度延迟；供应商历史模式还须不早于 vendor_first_seen_at；实时模式还须不早于接收和处理完成。processed_at 不得早于 ingested_at。publication_precision 为second/minute/date_only，另允许原始行情使用`reconstructed_market_close`：published_at和vendor_first_seen_at均为null，记录官方依据、重建方法和计划日终边界，不声称实际最后成交时刻或供应商首见。unknown仍阻断；quality_status必须accepted。

H00300使用date_only，不套用市场行情重建精度。按D039保留月末D公式，D+1交易日21:00生成目标，D+2执行，额外执行压力为D+3。D+1订单参考价/成交额不进入D的信号窗口。`availability_calendar`可保存官方公告已知的边界下一交易日，仅用于2024末行可用时间；模拟calendar、行情、订单与NAV仍不得进入2025—2026。

## Manifest 与审计准入

必需 `dataset_id`、`dataset_version`、`schema_version`、布尔 `synthetic`、timezone 和明确 units。units 固定为 `volume=shares_or_fund_units`、`amount=CNY`、`price=CNY`。真实数据另需 availability_mode、`calendar_kind=VERIFIED_EXCHANGE_CALENDAR`、license_profile_id 和 source_snapshot_hashes。

真实 `evidence_gates` 必须逐项登记：source、license、calendar、historical_coverage、point_in_time、lifecycle、corporate_actions、total_return、historical_rules、historical_fees、account_permissions、dual_source_reconciliation。每项包含 `status=VERIFIED`、reviewer、带时区 reviewed_at、非空 evidence 引用。它们是需外部审阅的证据声明；代码不能自行证明授权合同、完整历史或供应商发布时点。不得仅填占位字符串解锁研究。

审计返回 status/errors/blockers/warnings/performance_evidence/coverage/schema_version。结构违规为 errors；缺证据/缺覆盖为 blockers。两者任一非空均为 `BLOCKED_DATA`；合成全通过为 `SYNTHETIC_ONLY` 且 performance_evidence=false；真实全通过才为 `PASSED`。PASSED 仅代表本数据入口检查通过，不代表已经证明策略有效或执行模型充分。

`STAGING_ONLY`、`strategy_runs_permitted=false`或任何残余`build_blockers`都阻断准入，即便其他证据项被误填为VERIFIED。原始元数据、公告、规则、日历及不可变文档输入需绑定实际文件哈希，不能只有一个无法核对的URL。

coverage 包含日历长度、表行数、按年月/品种/板块观察数、停牌观察数、每个品种挂牌区间缺失交易日。真实困难样本、跨年代/板块抽检与双源核验须另附外部审计证据，不能用总体覆盖率替代。
