# 实现与实验状态

## 当前集中决策与个股准备（2026-11-15）

**R1：ARCHIVE_CURRENT_CONFIGURATION / STOP_ETF_PARAMETER_SEARCH。R2、R3：分别NOT_RUN_BLOCKED_ADMISSION。** 本轮完成R1现有448实验的只读机制/成本/风险复核，启动阶段一既定个股路线的实际源数据审计与工程准备；未运行新增ETF或真实个股绩效实验。

| 本轮交付 | 实际状态 | 证据与边界 |
|---|---|---|
| R1集中审查 | 完成并归档当前配置 | 排序跨期不稳、趋势八项主要消融为负、缩放降险伴随现金；主本金16条base路径均超过12%回撤参考线；无新R1实验提案 |
| 增量固定成本 | 算术容量已测算，正式门槛仍未过 | R1−E1缩放开，验证2,096.61元/年、开发−237.87元/年；真实费用未知，不能据验证值承诺预算 |
| 免费个股实采 | 数据难例审计完成，完整研究池未准入 | 股票SDK35请求34成功1失败、日历2成功、HTTP51请求49成功2失败；178个原件/manifest对象，完整性独立复核 |
| R2财务 | BLOCKED | 20个更正事件候选原PDF，仅1个完整发行人/报告期原稿—修订对账、独立人工签核0；全池原三表版本链未完成 |
| R3独立数据门槛 | BLOCKED | 历史行业、总股本/市值、风险状态、公司行为与费用输入未全池覆盖；不以R2财务或R1收益作为阻断理由 |
| PIT财务及因子核 | PASS_RESEARCH_KERNEL_ONLY | 原文版本/时钟/TTM、三因子、固定中性化、R2月度30只/45缓冲及R3残差窗口；21仓库测试与21独立探针通过，六项审查发现已修复 |
| 股票执行与会计 | 准入防护及独立组件已实现，主账户尚未就绪 | 权限、状态类型、历史费率可得时点、整数送转误放行、未知退市权益/陈旧估值；FIFO红利税与历史限价组件仍需完整主账簿集成和真实对账 |
| 个股真实实验 | 注册0、运行0；绩效null | preparation配置不是实验注册，不通过R1B标签、synthetic标记、删除退市样本或修订后财务绕过门槛 |
| 最终集/实盘/采购 | LOCKED / DISABLED / NONE | 2025—2026未用于策略选择；主板和创业板，主本金10万元、四档对照不变 |

本轮[集中审查](../reports/m3_equity_admission/REVIEW_PACKET.md)、[独立数据/执行审查](../reports/m3_equity_admission/INDEPENDENT_ADMISSION_REVIEW.md)、[研究核审查](../reports/m3_equity_admission/FEATURE_REVIEW.md)及[最终测试与复现记录](../reports/m3_equity_admission/VERIFICATION.md)为当前入口。具体缺字段和最低现金成本路线见[数据审计](../reports/m3_equity_admission/DATA_AUDIT.md)。免费官方补建已显示可行，当前未收集完整不等于免费永远不可得；尚无购买建议或报价。

后续可复用工作顺序：全池身份/状态、行业公开时钟、股本与日市值、完整行为与税类；R2原稿配对和全池财务链并行。股票税务/公司行为接线属于待完成工程，不混称外部不可补的数据缺口。只有各自数据与执行全部通过，才冻结真实配置和版本、运行既定对照；研发细则见[EQUITY_RESEARCH_PROTOCOL](EQUITY_RESEARCH_PROTOCOL.md)。

## 已完成的ETF日频里程碑（冻结历史）

更新：2026-11-15，Asia/Shanghai；phase2-mvp-0.1。**阶段二真实日频回测里程碑：E0/R0/E1/R1的448条既定实验全部完成，账簿与执行复核通过；独立统计审查完成：DESCRIPTIVE_VALIDATION_ONLY。数据准入为ADMIT_DAILY_SCREEN，正式经济确认仍为BLOCKED_HURDLE。**

| 验收项 | 实际状态 | 证据与边界 |
|---|---|---|
| 研究规范与权限 | REVIEWED | 八份阶段一文档齐全；主板/创业板允许，科创板/北交所个股禁止，ETF独立处理；没有新增策略方向 |
| 历史数据 | ADMIT_DAILY_SCREEN | 1,148个发现身份、110个候选、117条历史主表、127,090日线；16个代表并集、15个可达完整依赖、91个必要证券年 |
| 交叉核验 | 有限定地通过 | 东财96/110；14个缺第二源仍保留；41只816个价格差异字段第三来源支持原主源 |
| 事件与会计 | 依赖已核验 | 29规范事件；BOD/EOD折算、取整、取消计划、旧报价、登记股息与规则现金；六个退出产品为五次清算及一次转型 |
| 基线与优先策略 | E0/R0/E1/R1完成真实对照 | 等权/排名/趋势及共同波动缩放；没有选择最好本金或缩放替换原主要检验 |
| v1真实实验 | INVALIDATED_ENGINE | 开发224、验证128完成，另1验证中止；63处浮点半分钱边界差异，全部保留并作废，不作为Alpha证据 |
| v2完整矩阵 | COMPLETED 448/448 | 两时期×四策略×两缩放×四本金×七压力路径；主要本金100,000元；执行b308ccc/d8d265ee |
| 会计与执行 | ALL_PASS | 67,016笔成交、1,459,715条持仓估值、341整仓零股卖出；严格Decimal金额差异0；无估值不确定或时序不合格运行 |
| 报告与独立统计 | 评估及独立审查完成 | 224成对比较、384压力差、336本金差，独立24项bootstrap完全复现；NO_CONFIRMED_ECONOMIC_INCREMENT，正式经济确认BLOCKED_HURDLE |
| 自动化验证 | 329测试通过 | 本地32.27秒；GitHub Windows CI21.16秒；冻结执行版本325项与后处理新增回归分别记录 |
| 重现与归档 | 完成 | 追加注册、失败尝试、配置/代码/数据/表哈希和源码副本；评估版本7d6169f独立于执行版本；供应商原件仅本地保存 |
| 最终留出 | LOCKED | 2025—2026策略行情/结果未进入研究；边界日历、回溯公告与夹带字段隔离另有日志 |
| Paper/live | NOT_STARTED / DISABLED | 没有券商连接、真实订单或采购 |

主要本金10万元的base验证期（2022—2024），E0/R0/E1/R1在缩放关/开时累计净收益均为负。R1为−27.14%/−18.05%，对应E1为−30.78%/−22.90%；相对改善不能称为正收益或已证实Alpha。开发期R1−E1日均增量两个缩放均为负。完整指标、区间、成本/本金/年度归因和审查见[当前里程碑](../reports/real_data_phase3/REVIEW_PACKET.md)、[全部448结果](../reports/real_data_phase3/RESULTS.md)、[独立统计审查](../reports/real_data_phase3/STATISTICAL_REVIEW.md)。不以某个探索性p值选出最终候选。

开发账户固定2016—2021（1,461交易日）；验证账户固定2022—2024（726交易日），重新注资；更早数据只暖启动。验证集不是最终测试集。未知年度增量固定费用不能当作0，四族NOT_READY的p=1仅占位，不是正式检验结果。

复现与审计入口：[数据准入](../reports/real_data_phase3/ADMISSION_REVIEW.md)、[执行复核](../reports/real_data_phase3/EXECUTION_REVIEW.md)、[v1失败保全](../reports/real_data_phase3/superseded_v1/invalidated_attempts.json)、[生命周期旁证](../reports/real_data_phase3/RETIRED_LIFECYCLE_SUPPLEMENT.md)、[重现说明](../reports/real_data_phase3/REPRODUCE.md)、[验证记录](../reports/real_data_phase3/VERIFICATION.md)、[数据限制与最低成本补证](../reports/real_data_phase3/DATA_LIMITATIONS.md)。旧reports/real_data及m0_m1报告保留当时状态，不代表当前结果。

尚未实现分钟窗口/队列、完整ETF成分穿透、股票复杂公司行为与税务、场外基金转型/确权/赎回。未来若成为持仓依赖，必须补实现与证据，不能删样本绕过。当前冻结R1B日频研究无必须先采购的新硬缺口；R1I、R2、R3、R4继续保持各自数据门槛。历史修订版本、重建可得时钟、规则模拟到账与研究费率的限制持续有效。
