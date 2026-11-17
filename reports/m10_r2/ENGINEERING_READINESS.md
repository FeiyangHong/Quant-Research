# 2026-11-18 校园恢复增量

当前访问已通过；18财务+8结构固定调用已实测，13必要原件hash匹配。四组有限财务比对通过，但股本/行业历史公开、可得和版本链未准入，整体仍 **BLOCKED_DATA_CAPABILITY**。详见[当前实证、具体字段缺口和下一输入](../m10_activation/CAMPUS_RESULTS.md)。不将下方旧机访问/原件库存状态当成本机现状；原困难队列和冲突保留。生产适配、全池、股票执行/runner未完成，完整卡0、human0、实际R2账户0，24草案与null绩效不变。AI复核不替代human；尚不可集中请求签不完整卡。

## 以下为保留的先前阶段记录

# M10 R2 工程就绪审计

## 2026-11-17：M10_SOURCE_ACTIVATION_V1 当前状态

**BLOCKED_ACCESS_OR_LICENSE / EDUCATION_NETWORK_REQUIRED。** 用户已提供本人RQData教育license并保存配置；实际SDK初始化被教育网限制拒绝。已停止请求：1次初始化、0显式quota、0行情/财务、0真实R2账户，SDK内部请求/字节未知。历史能力未测试，不判断密钥无效或供应商无PIT。下一步是执行电脑使用许可证认可的校园网络，再恢复[固定样本计划](../m10_activation/SAMPLE_PLAN.md)。[本次结果与去敏证据](../m10_activation/RESULTS.md)。数据/执行缺项、完整卡0、human0和原24格未授权状态不变。以下2026-11-16内容保留为历史来源裁决。


2026-11-16。检查基线为公开 HEAD `3e19797ecaa88ce5c7c7f9f138b7dabfac4ea30a`，本轮仅增加下述估值合同与离线草案检查。**真实 R2 账户运行数为 0；没有 R2 绩效。当前不是 READY_FOR_HUMAN_REVIEW，仍同时缺数据、执行及 runner 能力。**

## 本轮实际完成

- `EXPERIMENT_REGISTRY.json` 是 `DRAFT_NOT_AUTHORIZED` 的 24 格草案：VALUE/QUALITY/COMBINED × 2016—2021/2022—2024 × base/2x/3x/额外一交易日。每格重新注资 10 万元，actual_run_id 和 performance_metrics 均为 null。实际代码/数据/规则注册哈希尚未生成。
- 主比较固定为验证 base 的 COMBINED−VALUE 净日收益差。两期各 20/60/120 日块，共六个 CI，5000 次、seed=20261114；没有继承 M9 二次效用。股票每边滑点 10bp、佣金 3bp、最低 5 元，法定费用不倍增。
- `equity_features.r2_factors` 增加显式参数 `valuation_convention="A_PRICE_ALL_ISSUED_ORDINARY_SHARES_V1"`。默认 `LEGACY_TOTAL_EQUITY` 保持旧行为。新模式用不同的 `market_cap_scope="A_PRICE_ALL_ISSUED_ORDINARY_PROXY"`，不把代理估值与旧 TOTAL_EQUITY 标签混同。
- 新模式验证 A 股未复权收盘 × 全已发行普通股数，包括 A/B/H、排除优先股。要求正整数 A 股及总普通股数、总数不小于 A 股数、股本单位、源字段映射、来源 hash、股类/库存股语义、独立公开/可得/采集时钟及股本生效时钟。日期精度按原保守规则。晚于历史截止的采集时间允许存在；未来公开、可得或生效时间不允许成为当时输入。
- 该模式按输入重新相乘并校验提供的市值。它不会下载、验证供应商真伪或把来源响应 hash 当作财报原件 hash。原财务核仍仅接受 ORIGINAL_FILING/CORRECTION_FILING，未创建 PROVIDER_PIT 适配器。所有输出继续 `formal_eligible=False`；数值可算不等于准入。
- `scripts/m10_preflight.py` 只读取草案和定义文件，检查固定矩阵、成本、主端点、六个 CI、30/45/6 规则、封锁状态及定义 hash。这是选定关键约束检查，不是对所有定义的穷尽验证。它没有运行或放行选项，无论草案是否一致，`strategy_runs_permitted` 都为 false。检查成功只表示这些草案约束一致。

## 逐项核对实际源码

| 依赖 | 现有代码/证据 | M10 状态及最小剩余工作 |
|---|---|---|
| PIT 财务长表与 TTM | `equity_features.py:42 financial_asof`、`:199 r2_factors` | 已有逐字段版本链与当时 TTM；供应商真实版本格式未验证，不能改标签冒充原件。最新公开报表覆盖与历史披露义务/延期策略仍未注册；默认输出明确阻断 |
| 估值分母 | `equity_features.py:118 _m10_valuation_cap` | 本轮修复旧 A-only 股类检查与 M10 新约定的合同冲突。只通过合成语义检查；无真实全池输入、股本映射或价格/公告时钟验收 |
| 全身份与规模分母 | 原核接受显式 universe_ids | 尚无按月输出的全主板+创业板非ST已上市全分母；没有历史权限、上市龄、状态、流动性、行业完整串接。不能在已取得财报子集重算底30%。规模截止并列/取整实现仍需收益前固定 |
| 一次中性化 | `equity_features.py:332 r2_scores` | 已有共同池 1%/99%线性截尾、ddof=0 标准化、行业+log规模残差再标准化；小行业统一父级或 WHOLE_POOL、残差 ≤1e−12 为零。无需另写或重复执行中性化 |
| 30/45 缓冲 | `equity_features.py:382 r2_portfolio` | 已有旧仓 rank≤45 保留、rank>45 不作为新股回购、每行业6、30只每只1/30；仍需与真实持仓状态和现金账连接。行业配额用原 PIT 行业 |
| 信号/释放时钟 | `equity_features.py:35 _signal_at` | 当前仅 D21。必须以实际源证据先固定共同最小释放延迟；不能直接复制 ETF D/D+1/D+2，也不能硬用尚未可得的收盘/股本/行业。草案对应实际延迟保持 null |
| 真实股票准入 | `provenance.py:54 validate_run_config`、`admission.py:61 split_sample` | 普通正式配置仅 R1B，数据拆分标识也是 real-r1b；无 R2 财务/全版本链/20真人签核 gate。不能把 R2 改名 R1B 或 synthetic 绕过 |
| R2 runner | `runner.py:43 _run_experiment`、`strategy.py:130 generate_targets` | 没有 R2 入口或股票历史资格构建；不能称“已有因子核即 runner 就绪”。有真实源后仅新增薄数据绑定、共同池、真实账簿闭环和不可变24格注册入口 |
| 红利 FIFO 主账 | `execution.py:148`、`:642`；`engineering_replay.py:14 validate_replay` | FIFO 目前仅在 engineering_replay 模式接线，真实来源 replay 必须显式非绩效。普通股票现金分红仍拒绝。必须在独立股票准入后建立真实研究模式，不能开启 replay 标志冒充策略运行 |
| 送转/配股/合并 | `execution.py:440`、`:567` | 股票送转税类/股数权益尚阻断，配股/合并未支持。只实现实际全池可达依赖；未知退出权利不能清零、删股或删事件 |
| 已有实际事件 | `reports/m6_stock_execution/results.json` | 康美 41 日有仓 ST 工程账通过；茅台普通/特别分红均缺 transfer_fee 原件、零成交阻断，broker_ledger_verification=UNVERIFIED。不能称真实持仓分红或实扣税完成 |
| 共享日容量 | `execution.py:796`—`:988`，结果模型 SHARED_DAILY_1PCT_ADV_AMOUNT_SHARES | 复用历史 ADV20 金额/当日实际额/实际股数的同证券同日共享额度，买卖绝对累计。不重写已有 M8 修复；日线不证明开盘队列成交 |
| 固定统计 | `evaluation.py:38 paired_inference` | 已有配对 circular bootstrap-t/HAC；未知固定成本保持 BLOCKED_HURDLE 但描述性 CI 仍可算。未来仅调六个预定区间，不套 M9 效用或扩大压力显著性网格 |

## 接通一个真实主源后才有意义的最小实施顺序

1. 按实际响应确认身份/状态/行业/全普通股/财务版本/公司行为时钟与字段，保留源响应和官方原件身份差异；完成原时期及必要前史覆盖。没有此输入，不造通用供应商层。
2. 形成每月全分母、未知原因和共同池；事前固定行业分类方案、披露义务政策、规模截止并列细则及源释放延迟。用本轮估值合同同时供 F01、底30%和 log规模，避免分母分叉。
3. 对全池可达事件补齐费用原件和真实账簿接线；保留已核 FIFO/现金预约/T+1/整手/阻塞旧仓/共享容量规则，独立对账。未知行为不能靠过滤掉相关股票消失。
4. 仅新增 R2 runner/准入绑定，复用原因子、评分、组合和统计核。20份完整真实人审及全池版本链与数据/执行门槛全部通过后，才生成实际不可变注册，先六条 base 复核，再十八条压力。缺人审时不能先跑绩效补签。

这些是尚未完成的工程工作，不冒充永久外部阻断，也不把它们写成已可运行。当前数据来源能力阻断下，继续造虚构接口不能补齐它们。

## 本次验证及限制

锁定解释器 `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe`，执行：

```text
-m pytest tests/test_m10_preflight.py tests/test_equity_features.py tests/test_m5_financial.py -q
57 passed in 7.97s
scripts/m10_preflight.py
draft_valid=true; strategy_runs_permitted=false; real_accounts_run=0
```

这些测试都是合成语义/旧核兼容与草案约束检查，没有真实股票收益或新增真实财务覆盖。独立审查由非作者另存 `review_code/m10/test_independent_m10.py` 和 `reports/m10_review/`；不把 agent 复核计为 human_review。本轮作者外部请求为 0，无来源响应下载、采购、实盘或 M9 重跑。
