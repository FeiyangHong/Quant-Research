# 实现与实验状态

更新：2026-11-14；phase1-v0.1。此文件是状态记录，不是策略成绩单。

## 当前事实

| 工作项 | 状态 | 证据 |
|---|---|---|
| 用户需求与研究范围 | 完成规范 | RESEARCH_BRIEF、RISK_POLICY |
| 市场/文献/数据来源审查 | 完成第一轮，保留缺口 | evidence/ |
| 候选策略与统计协议 | 初稿完成，待数据审计后冻结 | STRATEGY_SPEC、EXPERIMENT_PLAN |
| 独立规范审查 | 已完成一轮并整合修订 | D016—D017；仅文档逻辑审查，非数据/引擎测试 |
| GitHub远程仓库 | 未创建、未连接 | 本包只给结构与文档 |
| 数据账号/付费/下载 | 未执行 | 无数据manifest |
| 真实行情/财报验证 | 未执行 | 无M0审计报告 |
| 因子/回测/模型代码 | 未开发 | 无engine commit |
| 策略实验 | NOT_RUN | 无run_id、无净值、无绩效数字 |
| Paper/live | NOT_STARTED / DISABLED | 无真实订单 |

## 绩效字段

所有 R1/R2/R3/R4 的 CAGR、Sharpe、Sortino、Calmar、最大回撤、IC、换手、费用、Alpha、Beta、IR、置信区间、容量：N/A（NOT_RUN）。不使用0占位，因为0会被误读为实际结果。

## 下一步

1. 依 CODEX_HANDOFF 完成 M0 数据能力探查和原始规则归档。
2. 冻结配置/切分/基准/搜索预算，随后实现 M1 账簿与被动基线。
3. 完成 R1 的 M2 筛查，先判断是否值得继续，再引入基本面/反转/事件。

## 已知阻断与非阻断问题

- 实盘阻断：用户未授权下单；账户权限、券商API、费用和报告未核验。
- 财务研究阻断：尚无已验收的历史原始财务vintage。
- 事件研究阻断：R4a尚无公告首发时间、预告快报去重及季报vintage；R4b另缺历史一致预期。
- 早期交易回测阻断：2010—2015部分规则/费用尚待完整归档。
- 不阻断离线规范与价格基线：无GitHub链接、具体券商未知、财务PIT暂缺。

## 每轮结果追加格式

milestone / run_id / hypothesis_id / git_commit / config_hash / dataset_manifest_hash / rule_snapshot_hash / sample_period / holdout_access / status / metrics_path / trades_path / failed_orders_path / cost_breakdown_path / exposure_path / uncertainty_path / reviewer / next_action。

状态只用 PLANNED、RUNNING、FAILED_DATA、FAILED_ENGINE、COMPLETED_NEGATIVE、COMPLETED_INCONCLUSIVE、COMPLETED_PROMISING、REVIEWED、RETIRED。不得将无显著性自动改为“策略无效”，也不得将初步正收益自动改为“可实盘”。
