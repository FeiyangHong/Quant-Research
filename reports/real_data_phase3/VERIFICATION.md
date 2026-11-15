# 执行冻结与报告评估验证记录

冻结运行代码：`b308ccce541b6e60207808d4d55bc1f4dfd61928`；执行源码内容哈希：`d8d265eed26337ba8a58e2dff809af3acc71550232ecbddaa2b94a7a3da6ba7a`。下面325项结果保留为该执行冻结版的验证记录，后处理新增测试不回写到这一历史计数。

- 本地完整套件：325 passed，35.24秒，Python3.9.19及锁定依赖。
- GitHub Windows CI：325 passed，22.20秒。[运行记录](https://github.com/FeiyangHong/Quant-Research/actions/runs/43624924582)。
- 金额边界：运算前Decimal化，佣金、法定费用、零股成交、滑点金额、股息/清算金额及预留资金共用明确的按分舍入；相关72项回归通过。
- 策略提速：16组合成规则及352份已完成旧决策逐字段完全一致；直接真实数据oracle同时包含rank及暖启动字段。见OPTIMIZATION_EQUIVALENCE.md/json。
- 账簿提速：修复金额后的实现作为oracle，两个真实样本配置的11张结果表与投影/解析优化后逐字节一致。见ENGINE_PROJECTION_EQUIVALENCE.json。
- Git检出保护：70份执行输入源码文件、16份跟踪中的准入证据已逐项确认Git索引blob与登记SHA256一致；保留实际CRLF/LF，不转换已签认内容。

后处理评估版本为 `7d6169f0be2138292a1c708ac3e3e44dcd55a620`，源码集合SHA256为 `0187faf98b8c04b3ae689622238751100f8acaf2b11162b39369b3b904e6af04`。这一身份只用于报告复算，448项v2执行身份保持b308/d8。

- 中间评估提交 `0840aa9`：新增2项金额复算回归；23项相关测试通过，5.47秒。这不是整套327项测试通过的记录，也不是最终评估提交。
- 最终评估提交 `7d6169f`：本地完整套件 **329 passed，32.27秒**，包含相对325项执行冻结套件新增的4项后处理回归。覆盖半分金额的正确接受/篡改拒绝，以及统计定义或身份逻辑偏离冻结快照时拒绝评估。
- 最终7d6169f的GitHub Windows CI测试步骤：**329 passed，21.16秒**，官方job日志于2026-11-14 18:34:39 UTC记录。[运行43627213059 / job132545695194](https://github.com/FeiyangHong/Quant-Research/actions/runs/43627213059/job/132545695194)。中间0840aa9的 [CI运行](https://github.com/FeiyangHong/Quant-Research/actions/runs/43626985870) 不替代这份最终评估版本证据。
- 评估器只允许报告编排/核算脚本独立修复，仍要求 `src/quant_research/evaluation.py` 与 `src/quant_research/provenance.py` 等于b308/d8执行快照。实际后处理代码与环境已保存在 [evaluation_provenance.json](evaluation_provenance.json)、[evaluation_source_snapshot/](evaluation_source_snapshot/) 和结果内同名身份字段。

这些测试和等价证明不替代真实矩阵的逐笔复核。当前[执行工程复核](EXECUTION_REVIEW.md) 已对v2的448/448项给出PASS：67,016笔成交、1,459,715条持仓估值，严格Decimal差异为0，16项toy故障注入自检通过。机器证据为 [execution_review.json](execution_review.json)。[正式描述性报告](RESULTS.md) 和 [results_summary.json](results_summary.json) 已生成，448项账簿复算 `ALL_PASS`、总体状态 `DESCRIPTIVE_DAILY_SCREEN_ONLY`；[独立统计审查](STATISTICAL_REVIEW.md) 已完成，全部24项bootstrap复算一致，22项正常与2项退化不确定均保留；结论仅为DESCRIPTIVE_VALIDATION_ONLY。工程及描述性复算PASS不证明Alpha有效。

v1全部结果已因金额错误失效，旧库存/日历通过也不恢复其研究资格。旧v1的352条已审记录和63处数值差异继续保存在 [execution_review_v1_failed.json](execution_review_v1_failed.json)，不混入当前v2验证结论。未知年度增量费用继续使正式经济确认保持 `BLOCKED_HURDLE`，2025—2026最终留出仍锁定。

审查程序归档在review_code/。旧失败尝试、源码、数据身份及结果表哈希完整保留在superseded_v1/及本地runs/；原供应商数据不上传Git。

发布前另检查71份评估源码快照均与7d6169f对应Git blob逐字节一致，448条配置身份均与registered_plan_v2一致，见[PUBLICATION_CHECK.json](PUBLICATION_CHECK.json)。只读检查源码归档为review_code/check_report_publication.py；此核验不追加统计检验或策略运行。