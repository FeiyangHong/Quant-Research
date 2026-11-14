# 离线数据 Schema v1

版本 `r1-offline-1.0`；2026-11-14；时区 `Asia/Shanghai`。实现为 `src/quant_research/data.py`。本 Schema 为 R1 离线工程接口，不替代 `DATA_CONTRACT.md` 的真实数据证据要求。

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
- actions 支持 `CASH_DIVIDEND` / `SPLIT` / `DELISTING`。cash_per_share 为原持仓每股/份现金，share_factor 为新股数/原股数（普通事件为1），recovery_per_share 为退市每股可核验回收额，未知必须 null。record_date 表示本模型记录权益的前一持仓日期；真实不同登记/到账机制需要适配并审计。pay_date 为空不代表已经到账。配股、合并等其他事件类型当前阻断，不伪装成已支持。

## 可用时间与修订

决策截止默认交易日21:00。`asof_records` 先过滤 `available_at <= cutoff`，再按经济主键选最新可见版本；未来版本不会覆盖过去查询。cutoff 也必须带时区。同时间版本歧义直接报错。

只有公告日期 D 时，`date_only_available_at` 取严格晚于 D 的第一个交易日21:00；`extra_delay=1` 再加一交易日。交易最早仍是该决策后的下一交易日。日历覆盖不足即拒绝推算。精确时间保留时区并转换比较，21:00之后与海外尚未收盘的数值不可提前进入。

真实表额外要求：`published_at`, `publication_precision`, `vendor_first_seen_at`, `ingested_at`, `processed_at`, `availability_mode`, `source`, `endpoint`, `source_record_id`, `raw_object_hash`, `license_profile_id`, `quality_status`。原始对象 hash 为64位小写 SHA-256。

允许模式为 `historical_public_asof` / `historical_vendor_asof` / `live_capture`。真实历史下载时间仅作为 ingested_at；不会用它冒充历史首可用。公开历史重建的 available_at 下界取公开时间及日期精度延迟；供应商历史模式还须不早于 vendor_first_seen_at；实时模式还须不早于接收和处理完成。processed_at 不得早于 ingested_at。publication_precision 为 second/minute/date_only，unknown 阻断；quality_status 必须 accepted。

## Manifest 与审计准入

必需 `dataset_id`、`dataset_version`、`schema_version`、布尔 `synthetic`、timezone 和明确 units。units 固定为 `volume=shares_or_fund_units`、`amount=CNY`、`price=CNY`。真实数据另需 availability_mode、`calendar_kind=VERIFIED_EXCHANGE_CALENDAR`、license_profile_id 和 source_snapshot_hashes。

真实 `evidence_gates` 必须逐项登记：source、license、calendar、historical_coverage、point_in_time、lifecycle、corporate_actions、total_return、historical_rules、historical_fees、account_permissions、dual_source_reconciliation。每项包含 `status=VERIFIED`、reviewer、带时区 reviewed_at、非空 evidence 引用。它们是需外部审阅的证据声明；代码不能自行证明授权合同、完整历史或供应商发布时点。不得仅填占位字符串解锁研究。

审计返回 status/errors/blockers/warnings/performance_evidence/coverage/schema_version。结构违规为 errors；缺证据/缺覆盖为 blockers。两者任一非空均为 `BLOCKED_DATA`；合成全通过为 `SYNTHETIC_ONLY` 且 performance_evidence=false；真实全通过才为 `PASSED`。PASSED 仅代表本数据入口检查通过，不代表已经证明策略有效或执行模型充分。

coverage 包含日历长度、表行数、按年月/品种/板块观察数、停牌观察数、每个品种挂牌区间缺失交易日。真实困难样本、跨年代/板块抽检与双源核验须另附外部审计证据，不能用总体覆盖率替代。
