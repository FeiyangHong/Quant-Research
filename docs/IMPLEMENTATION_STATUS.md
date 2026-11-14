# 实现与实验状态

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