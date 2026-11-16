# 当前恢复入口：M9已完成，固定矩阵结束

本轮24条真实输入风险预算模拟与独立核验均已完成，不因收益、CI跨零或剩余预算重启账户/采集。按[M9_PLAN](M9_PLAN.md)、[原任务第7节](M8_INDEPENDENT_REVIEW_AND_M9_HANDOFF_2026-11-16.md)、[结果](../reports/m9_risk/RESULTS.md)、[审查](../reports/m9_review/REVIEW_PACKET.md)、[独立验证](../reports/m9_review/VERIFICATION.md)恢复事实，不依赖聊天记忆。

工作目录F:/QuantTrade/Quant-Research-M9，分支`codex/m9-risk-budget`，来自公开540fdf3，原完整本地M8分支/数据在F:/QuantTrade/Quant-Research保留不动。附件、24格和判定规则先在a696c13推送，实际M8/M9源码于a2fbb04冻结并公开；所有账户源码hash `dc4e7a79f6f5373d5af15d71def409d54e7209d3ae927c818c72d31d5a96e6a3`。后续交付提交只追加结果/审查/交接，不能重新算c或修改源后冒称原运行。

`M9_ETF_RISK_BUDGET_V1`复用原M8数据scope与两期数据hash，不改M8准入。c=0.6295030564604313、锚点2020-01-23/释放2020-02-03，跨期/压力冻结。VE/CE/VR共24路径，先6base后18压力，ACCOUNT_PATHS与SOURCE/PRIVATE表哈希保存。完整账在runs/m9_real；公开账户8文件/条，缺原件不能宣称公共全数据回放。执行差异报告解释了滑点合法价格拒单、整手/现金和延迟，未新增收益诊断。

主结论INCONCLUSIVE；符号检查PASS只是点估计约束，不等于正主CI。验证VE较CE降波动但累计收益更低、回撤略差；评分不能叫收益/Alpha/费用空间。保留风险工程和固定政策参考，停止本配置研究；M8动量/共同趋势归档不变。没有授权新风险目标/窗口/gamma、股票R2/R3、新闻/ML、2025以后留出、采购、paper/live或合并main。

持续按[DELIVERY_POLICY](DELIVERY_POLICY.md)提交并推送，报告真实远端SHA/CI。受限原件和完整源祖先不进公开链。本轮公开CI已真正跑实际实现893通过/12跳过，最终结果提交的状态以发布收据及GitHub检查为准；不把旧M8仅补丁CI当本轮实现证明。

## 历史M8公开补丁交付状态

M8 completed all 32 accounts; conclusion INCONCLUSIVE. Read [M8 publication scope](M8_PUBLIC_DELIVERY.md), [results](../reports/m8_public/SUMMARY.md), and [persistent push requirement](DELIVERY_POLICY.md). This public branch contains the independently checked derived package and code patches. Complete local source evidence and private commit ancestors are not published. Existing source CI on this branch is not an M8 account replay.

---

# Codex Astra Ultra 第二阶段直接任务书

## 当前恢复入口：M7固定32条已完成并停止

先读[M7计划](M7_PLAN.md)、[完整原任务第7节](../reports/m7_review/M6_INDEPENDENT_REVIEW_AND_M7_HANDOFF_2026-11-15.md)、[集中审查](../reports/m7_review/REVIEW_PACKET.md)、[RESULTS](../reports/m7_cohort/RESULTS.md)、[VERIFICATION](../reports/m7_review/VERIFICATION.md)及[非作者审查](../reports/m7_review/INDEPENDENT_REVIEW.md)。基准da1003a，登记18eeba4，实际32账户均运行于`679e80813daefea0b5fb312d120e7ada9b8cc40a`，详细hash在ACCOUNT_PATHS/RUN_PROVENANCE。不依赖聊天记忆恢复状态。

结论LIMITED_IDENTIFICATION。新独立范围R1I_FIXED_COHORT_V1仅159936/159938/159939/159940/159944/159945/159946，无季度代表竞争。107个合法月末N最多2，四规则实际32账户全现金；已运行8base+24压力，34,992日账，0失败、0未运行。验证R0−E0净增量0与开发一致，但无选择机会，不能称动量失败、趋势无效或成本稳健。额外固定费null，经济BLOCKED_HURDLE；真实区间因差序列退化而null，统计接口的未知费漏洞已另以合成独立oracle修复验收。

七身份和退市存续量额完整；159946清算未知、完整ETF TR/行为和有仓费用/真实交割未验收，只在本次零起始仓位且无持仓依赖证明下免除。原件在data/raw_m7和复用归档中，Git有102项hash/路径索引；不要把普通境内ETF权限研究模型说成读取了私人券商。任何新持仓依赖须另审，不能把此限定准入直接推广。

本轮研究到固定范围即结束，剩余额度不自动续用。原动态R1I仍DATA_BLOCKED、56 NOT_RUN冻结；旧R1B448+353归档及summary不改。股票旁线本轮暂停，M6康美PASS/茅台两案BLOCKED维持；同源股本只能作事件线索，缺历史vintage，不自动续pilot。R2/R3真实Alpha、2025-01-01至2026-11-13留出、paper/live、采购/供应商联系仍关闭。后续如新授权，先明确可识别的研究问题及独立范围，不改本组产品/阈值/K/年份来寻优。

当前决策路径仍为月末资格→等权或相对动量Top3→可选共同沪深300TR趋势→D+1晚目标→D+2差额订单→原主引擎费用/成交限制；M7关闭波动缩放。因为资格不足，真实目标全为空，完整现金账已保存。R2/R3只有研究核及部分来源工程，未实测。行业全市场方向、股票两路线是否继续均需新的具体依据，不由本轮零结果推断或自动启动。

## 前轮恢复入口：M6已停止在有限里程碑边界

先读[本轮计划](M6_PLAN.md)、[用户完整审查任务](../reports/m6_review/M5_INDEPENDENT_REVIEW_AND_M6_HANDOFF_2026-11-15.md)第7节、[M6审查包](../reports/m6_review/REVIEW_PACKET.md)、[验证](../reports/m6_review/VERIFICATION.md)、[独立审查](../reports/m6_review/INDEPENDENT_REVIEW.md)和本文件/IMPLEMENTATION_STATUS。基准5df2fc9，事前登记02d0f0d；最终commit、源/代码/规则/结果hash由验证包及版本化收据绑定。不要根据旧阶段任务自动重新采集。

本轮优先级已由用户改为R1I行业代理ETF，唯一历史中证一级分类，固定56账户路径、全部不波动缩放。批量发现可行、历史分类和共同依赖未全，故56均NOT_RUN_DATA_BLOCKED，收益/配对区间/经济增量null。原1148供应商ETF加官方补充共1970身份保留；991待审量额、历史十→十一行业过渡/指数方法链、发现差异是具体阻断。108计划决策N未知，不能以0伪装有效现金或LIMITED_IDENTIFICATION。源pilot已在46HTTP停止，不自动花剩余额度。

费率未来行缺clock反例已修复，独立29例通过；R1I纯选择核23例通过，但真实资格/runner仍未接线。康美ST真实固定持仓41日独立账通过；茅台普通/特别两案仍缺2022过户费官方原文或可核完整官方转载，零成交账不能算事件PASS。现有官方媒体托管稿只旁证，不应再次机械抓同一失败URL。独立Decimal期望不依赖实际fills/NAV。没有私人券商流水，工程模型不称真实交割验收。

股票股本批量来源3HTTP已证明技术可取，下一候选只允许另登记的有限合同pilot；不得自动抓全389页或3779公司PDF。原3779分母完整PIT股本链仍0，NOTICE/版本链/许可及A普通股与全普通股估值分子合同未决。R2财务20例human门槛保持，R3不依赖R2财务但共同数据不可豁免。本轮未扩手工财务。

当前范围已结束，须集中研究审查另定下一预算/数据方案后继续；不为R1I未运行降低门槛，不因R1B失败外推行业方向，也不把R1I数据困难当已否证Alpha。R1B448+353和原summary哈希、R2/R3 Alpha0、最终留出/paper/live关闭均保持。原M5/更早任务保留下方作历史，不构成新授权。

## M5恢复入口（历史，已由以上M6状态更新）

先读 docs/M5_PLAN.md、reports/m5_review/REVIEW_PACKET.md、VERIFICATION.md、INDEPENDENT_REVIEW.md 和 IMPLEMENTATION_STATUS.md。M5基准8a9977c，最终代码以审查包所属提交及哈希清单为准；不要仅凭下文第一阶段任务书重新执行旧阶段。

M5总体B：双时间依赖、持久预算和已验证主链工程断言通过；两个真实财务案例F02/F03通过算术核验，F01/完整latest覆盖/正式freshness仍未准入；三真实事件主账户因历史规则原件缺口保持BLOCKED、0实际成交，条件预期不能冒称已通过真实对账。2020-07-31的3,779身份保留，5例股本诊断完成但完整PIT市值链0，全市场分位未计算。五卡human签核仍0，不阻止不依赖该门槛的工程。

后续不得自动启动R2/R3 Alpha、R1搜索或最终留出。用户M5任务已经达到固定案例/两路线边界；继续扩采或改变正式协议须在集中审查中另定范围。20例人类财务验收仍是R2正式门槛，R3独立依赖共同历史池/行业/市值/行为/规则。原448+353、summary c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb、主本金10万元及四档情景不变。原50%对角收缩模型不改；任何新共享风险模块须在新收益实验前另注册“同一经济暴露拆分不降低风险”的基线和验收，不扫描系数救收益。

M5收尾增加[买卖决策与范围表](STRATEGY_IMPLEMENTATION.md)：E0等权、R0相对动量前3、E1/R1再加月末沪深300TR200日趋势，可选缩放随后生效；负动量未被禁止，真实D锚点/D+1晚决策/D+2执行，实际按持仓差额下单。没有新闻/政策Alpha。只归档当前R1B，不概括所有ETF失败；R1I原一级行业槽位路线未测试，细分/主题须另定边界。下一轮先补共同数据/执行，R1I有限可行性评估可列候选；正式收益实验仍R2优先，R3独立先准入可先行，无本轮新增授权。R2/R3不是宽基成分池，固定M5案例不是永久候选名单；完整股票池和调度仍未接线。收尾增量、旧调仓只读摘录、哈希和额外会话成本见reports/m5_review/closeout_scope_binding.json。

下文保留第一阶段历史交接任务，其“未实现/无绩效”等表述属于当时状态；当前事实以以上M5入口及版本化历史包为准。第一阶段后续阶段名称不授予本轮holdout/paper/live权限。

版本 phase1-v0.1；编制日期2026-11-14；时区Asia/Shanghai。

你接手的是中国A股系统化量化研究项目。用户具有Python与机器学习能力，目标是在真实成本、交易约束和模型失效风险下，检验长期正向绝对收益与风险调整后超额收益。不能保证盈利，不得虚构回测。首轮是研究基础设施和最小实验，不是立即实盘。

本任务书无需聊天记忆；需要本包其他规范文件。若只有本文件，先取得同版文档包，不根据猜测实现未提供的策略参数。

## 1 开始前读取

依次读取 README.md、AGENTS.md、docs/IMPLEMENTATION_STATUS.md、docs/RESEARCH_BRIEF.md、docs/DATA_CONTRACT.md、docs/STRATEGY_SPEC.md、docs/EXPERIMENT_PLAN.md、docs/RISK_POLICY.md、docs/DECISION_LOG.md。文献/制度边界见 evidence/。

第一阶段交接时没有项目行情数据、回测结果或代码引擎；研究与规范已完成初稿。第二阶段已核验远程仓库为 https://github.com/FeiyangHong/Quant-Research.git；当前工程事实以 IMPLEMENTATION_STATUS.md 为准。

## 2 已确定的研究边界

- 资金四档：1万、10万、50万、100万元人民币，分别做整数份额/最低费用/容量。
- 无融资杠杆，主要现货做多，允许现金。用户确认主板、创业板有权限；科创板个股、北交所没有购买权限；相关ETF逐产品核验。
- 研究全A与外生信息不等于账户可交易。主题/行业/指数/财务/宏观均使用当时版本。
- 先R1 ETF同池等权/相对排名×简单趋势开关；R2低频价值+盈利质量、R3短期残差反转随后；R4公告后漂移须PIT通过。
- 简单规则→线性→有限树模型；HMM/主题NLP/神经网络/高频不在首轮授权搜索中。
- 时间截止21:00，次交易日执行；日期精度公告按数据契约额外延迟。不能收盘后得知数据却假定无条件同收盘成交。
- 所有策略尚为假设；当前没有任何项目绩效数字。论文收益不能填入报告成绩单。

## 3 M0 数据与注册

### 任务

1. 检查环境与现有工作区指令，建立轻量模块边界。Python、Parquet/Arrow、DuckDB和明确类型schema足够作为候选；依实际环境选择并锁版本，不为此引入分布式平台。
2. 列出实际可访问数据源与用途许可；不得购买、借用账号或绕过地域/访问限制。无token时用官方合法样本做契约/会计fixture，明确synthetic，不给投资结论。
3. 获取最小security master和ETF样本、原始行情/公司行为、交易日历、历史状态/费用；保存原始快照和hash。优先2016后可审计交易区间，2010后用于历史覆盖/暖启动。
4. 逐条核对2020创业板、2023主板注册制/税费、2024北向披露、2025程序化规则、2026交易规则。下载2026规则与暂缓条文，归档URL/publication/effective/hash；不能把草案当生效版。
5. 财务数据先用至少20个真实重述/公告时点案例人工对账，取得原始vintage才启用R2；事件首发去重合格才启用R4。PIT失败不阻断R1。
6. 在看策略收益前，冻结样本分期、benchmark、主要本金、规则配置、费用假设、参数网格、搜索额度、主端点和经济hurdle；记录哪些历史已经知道或看过。

### 验收

输出M0_DATA_AUDIT.md、dataset/rule manifests、schema、config与trial registry；每接口字段/覆盖/时延/许可/缺失明确。关键规则或PIT失败须明确BLOCKED范围。若实际数据权限缺失，完成所有不受阻工作后集中列最少待用户提供项，不能用不合格数据伪造成功。

## 4 M1 引擎与会计

### 必需模块及接口

| 模块 | 输入 | 输出 | 硬验收 |
|---|---|---|---|
| Data/PIT | provider snapshots、query cutoff | versioned tables | available_at不越界、修订可追溯 |
| Instruments | 历史security master、规则、账户mask | Research/Tradable/Proxy universes | IPO/退市/权限按日期正确 |
| Features | PIT observations | FeatureFrame | 历史前缀不变、缺失原因可见 |
| Signal/model | features、固定模型版本 | Scores | 不读成交未来、训练标签成熟 |
| Portfolio | scores、existing holdings、risk/cash | TargetWeights | 目标集中度/行业/现金可行 |
| Independent risk | 订单意图、已确认现金、锁仓与挂单、权限/限额 | RiskCheckedOrder或可解释拒单 | 联合最坏暴露不超限，策略不能绕过 |
| Execution | intents、规则、价格/量事件 | orders/fills/rejects | T+1、限价、容量、部分成交 |
| Accounting | fills、corporate actions、tax | lots/cash/NAV | 资金和股数守恒、费用一次计入 |
| Evaluation | ledger+benchmarks | metrics/CI/attribution | 同期同口径、全部失败run可见 |
| Monitoring | data/order/position state | alerts/review packet | 失败关闭新增风险、可重演 |

### 必要测试

- 买入当日不得非法卖出；卖出可用/可取资金分开。
- 100股/份与科创200起、北交所100起的历史规则配置不混淆；权限拒单可解释。
- 停牌、单边涨跌停、部分成交、无报价、订单过期、连续无法退出保留库存与损失。
- 分红/除权/税追扣、拆股/配股/基金分红、退市权益：不凭空创造NAV，不重复扣基金内部费用。
- 佣金最低额按真实订单计费粒度，含规费不重复；税费按有效日切换。
- 严格前缀不变性：增加未来行不改变过去特征、信号、可交易集和历史订单；纠错/版本更换须有明确revision。
- 历史规则变更日、IPO/退市边界、公告在21:00之后、海外时区与日期精度延迟用例。
- 固定数据/config/code/seed重复运行得到相同账簿与摘要；基线NAV可从原始账簿独立重算。
- 委托冻结/撤单解冻不改变NAV；买单不预支未成交卖单回款；被锁旧仓和未成交买单联合验风险。
- 长期陈旧价、退市未清偿权益的估值与零回收压力符合实验计划，不能靠不更新价格降低回撤。

测试针对真实泄漏与会计风险，不堆砌镜像实现的无意义测试。通过后生成被动ETF与同池等权报告，不立即搜索最好参数。

## 5 M2 最小研究实验

按STRATEGY_SPEC实现R1B、R1I，若行业PIT映射不合格先只R1B并明确R1I阻断。四变体E0/R0/E1/R1，各四档本金，真实历史费用+研究滑点，保留所有结果。先日线筛查标DAILY_SCREEN_ONLY；看起来有希望才做真实分钟09:35—10:00窗口的成交复核，不能凭日线声明实盘可行。

报告排名、趋势和风险缩放各自增量；对照相同池等权、被动ETF、全收益指数与现金/风险匹配。测试费用2×/3×、额外1日延迟、流动性参与率、参数小范围敏感性、少数年份/品种贡献及ETF历史覆盖。不能拿当前明星ETF回测其上市前指数收益。

如果费用或合理成交已经消灭优势，给出停止证据；不要擅自改成主题新闻/更高频/更小股票。R1失败可以仍交付合格研究框架。

## 6 M3—M4 和独立审查

R2/R3按各自数据门槛与预算执行；R4须首发信息通过。可使用数据审计、实现、统计、执行验证subagents，分开职责。统计agent不替实现者挑最好曲线，执行agent不默认日线能成交。

M4冻结最多每族一个主候选、主要本金、主基准和claim_type，登记后才开启2025—2026历史留出。主端点为配对交易成本后增量均值，增量固定费用门槛不得重复扣。四族只做一组预注册Holm；不可把辅助趋势/质量/模型/因子回归结果替代失败的主检验，未就绪族保留p=1。预先规定的滚动学习可用已成熟过去标签，人为调参不能看最终结果。所有配置与负结果纳入搜索数，多重检验/置信区间按实验计划执行。前瞻paper开始后每日自动存档，不能因不赚钱删除启动时期。

## 7 自治范围与返回研究端的条件

允许自主：合法数据下载重试、接口适配、缺陷修复、重构、性能优化、已注册网格、诊断与测试、报告和文档同步、独立子智能体审计。

以下才返回研究审查：核心假设被否定、重大数据/PIT/测试污染、需要改收益机制、超风险预算或不可修复执行限制、新策略方向、搜索额度将超限、完成M0/M2/M3/M4等约定里程碑。每次提交具体结果和变更提议，不让用户重贴完整聊天。

## 8 Review packet

每次提交 reports/<milestone>/REVIEW_PACKET.md，至少含：

1. 结论与请求决定，不超过一页的摘要。
2. git commit、数据/规则/config/environment hashes、样本和run_id。
3. 预注册问题、全部试验与排除/失败原因。
4. 净收益/回撤/费用/换手/风险/容量及基准表，明示真实结果或NOT_RUN。
5. 置信区间、多重检验、风格与行业/择时归因。
6. 数据缺口、不可成交、极端时期和反证。
7. 继续/停止/补数据/进入paper的建议及依据。
8. 已更新的DECISION_LOG和IMPLEMENTATION_STATUS及需要审阅的diff。

仓库可访问时研究端读此包；不可访问时导出同一包上传。不要宣称Pro和Codex会自动轮流运行、账户额度互通或必然拥有同一连接。

## 9 实盘限制

本任务没有授权真实下单。live_enabled=false。M4通过后，先完成券商API/交易权限/程序化报告/数据用途许可/实际费用/风险预算与明确上线授权，再讨论M5。不得把审批边界改写成自动通过，也不因本期实盘未授权而停止已授权的离线研究。

## 10 交付完成定义

M0—M2交付完整可复现实验框架、所有运行及失败记录、可信数据与执行边界、至少一套ETF基线与规定消融、四档真实资金可行性表、独立复核和下一里程碑建议。每档/每策略允许结论为不可实施，不为凑齐可行结果擅自放宽集中度或最低费用。发现没有净Alpha也是合格研究结果。只交一张高Sharpe图、只跑当前成分股或只写建议不实现，不满足交接要求。
