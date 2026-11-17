# M10集中审查：数据能力阻断，没有股票Alpha结果

**最终研究状态BLOCKED_DATA_CAPABILITY。R2真实注册0、账户运行0；24个草案格均未授权、未运行，收益/净增量/CI为null。** 数据、执行和human门槛同时缺失，不是READY_FOR_HUMAN_REVIEW。先读[结果首页](../m10_r2/RESULTS.md)，其中明确下一外部输入及本轮停止原因。

## 一次需要的数据决定

请确定是否已有合法授权的历史PIT数据服务或冻结导出，并提供服务名称/权限范围/项目配置或目录位置；密钥留本地。最低需求见[字段/时钟合同](../m10_r2/DATA_CONTRACT_ADDENDUM.md)：2016—2024及必要前史，全历史身份含退出、历史状态/行业版本/股类股本、原价量额、原稿与修订财务完整链、行为和退出权益以及相应许可。若没有，保持停止，另作来源/资源决定；本轮没有采购、注册试用或联系供应商。

项目配置范围内没有核验到足够的另一主源。已有BaoStock/官方档案可访问，故主状态是能力不足，不断言“用户没有任何权限”。Tushare官方字段说明只构成能力线索，RQData当前文档两次超时，不把文档、品牌或PIT字段名当实际权限/返回/完整性证据。[ACCESS_DECISION](../m10_r2/ACCESS_DECISION.md)逐源列访问、字段、许可、缺口和UNKNOWN成本；已到足够证据的停止边界，不自动再开网页pilot。

## 任务完成、失败和未做

|任务|实际结果|
|---|---|
|附件/增量/计划|PASS。本地及远端基准3e19797无后续增量；原附件原字节入docs，计划5d3b4e先提交并安全推送，旧私有HEAD/资料保留。|
|来源/覆盖决定|完成有限核查，数据准入BLOCKED。265/265原始档案hash一致；271引用中270一致，1旧采集代码漂移单列，无原始对象缺失。3,779仅单日诊断分母，108个所需月末完整共同池未验收。|
|人工案例材料|已有20候选PDF均hash匹配，固定队列4文档对/3冲突/13未配原稿，康美另1共5对。完整M10卡0、human0。已有材料和逐例缺项已索引，不伪造20个通过案例或请求盲签。|
|财务/估值工程|旧A-only门槛与新约定冲突已修复为显式全普通股选项，默认旧行为不变。源语义/数量/时钟/单位/乘积及未知保护经非作者Decimal检查；仅合成合同工程，不证明真实F01或完整数据。|
|运行准备|24格DRAFT_NOT_AUTHORIZED、主COMBINED−VALUE、原分期/10万元/股票成本/6区间均固定。离线preflight可运行并明确不放行。普通股票数据绑定、全池构建和真实策略runner尚未实现；没有虚构供应商适配器。|
|股票事件|原康美有限ST工程PASS保留；茅台普通/特别分红仍因过户费证据BLOCKED、0成交。三案broker流水UNVERIFIED。没有重跑旧事件或用toy替代。|
|真实股票收益|NOT_RUN；没有账户、CAGR、Sharpe、配对CI、质量Alpha或部署结论。不是失败的24条实验，也不是全现金0收益。|
|范围外|M9及旧ETF不重跑，十ETF搜索停止；无R3/ML/新闻/2025以后市场因子策略/采购/paper/live/真实交易。|

不具备主源时未扩采20公司网页，是任务书B的明确停止路径。没有仅以缺human为由停止：全池版本、最新报告覆盖/披露时效、历史行业方案、股本/全规模分母、源释放时钟、事件接线及R2 runner均明确未完成。这些技术缺项在[工程就绪表](../m10_r2/ENGINEERING_READINESS.md)逐项定位；并非永远无法实现，但现在不能声称就绪。

## 独立核验与测试

独立agent与作者分工，非human：20队列PDF、31个案例/事实来源对象、22个指定PDF页数值token、22事实时钟、9个前2025案例时钟、两个既有年报/Q3的Decimal F02/F03及全档案hash逐项核对。002528晚发修订的2025可得元数据保留但不复验/使用该后期市场日历；三项金额/文本冲突仍隔离。

独立34个针对性探针通过，覆盖全普通股代理独立手算、负利润、非法/未知/未来输入、源响应与原稿身份、旧模式、封锁期和伪造human/data标记；预期不从作者结果或NAV倒推。作者57项目标回归通过。root完整离线集成 **946 passed / 10 skipped / 1既有FutureWarning，77.21秒**；只运行测试，没有运行真实策略账户。三组数量存在重叠，不相加夸大验证量。

10个本地skip均是旧M5/M6缺原件依赖：M5实际源builder1、原PDF6、原市值响应1；M6原采集事故账本1、旧准入原件1。另两项旧M6本地测试可发现外部绝对路径原件，公共CI可能再skip，不把其缺原件计PASS。新M10纯代码测试可公开执行，最终远端真实数量以发布收据/PR检查为准，不引用M9 CI冒充。

[独立审查](INDEPENDENT_REVIEW.md)、[独立验证及逐项收据](VERIFICATION.md)、[本地集成日志](local_integration_tests.txt)、[本地集成收据](local_integration_tests.json)。原件检查不是新的全池数据验证；指定页token核对不是新的人类视觉验收。

## 实际命令和复现范围

工作根 `F:/QuantTrade/Quant-Research-M9`，解释器 `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe`。

```text
python scripts/m10_source_inventory.py --archive-root F:/QuantTrade/Quant-Research --output reports/m10_r2/COVERAGE_REPORT.json
python -X utf8 review_code/m10/inspect_existing_evidence.py
python -X utf8 review_code/m10/check_archive_manifest.py
python scripts/m10_preflight.py
python -m pytest -q tests/test_m10_preflight.py tests/test_equity_features.py tests/test_m5_financial.py
python -m pytest -q review_code/m10/test_independent_m10.py
python -m pytest -q -rs tests review_code
```

源inventory与两个证据脚本需要既有私有原件/PDF工具；无原件不得假称复现，不自动下载。纯估值/草案测试可在公开源码与锁定依赖环境运行。`m10_preflight.py`成功返回只表示所列草案检查通过，永远`strategy_runs_permitted=false`，不是全字段准入引擎。没有`DATA_BINDING.json`，因为实际策略数据尚未就绪；不创建空壳补清单。

## 版本、预算和交付边界

审查基准 `3e19797ecaa88ce5c7c7f9f138b7dabfac4ea30a`；M10计划 `5d3b4eadc66d7e8155c3f3bffc29ecba1e09e41c`。附件SHA256 `01723c04baeb292d08380f98efc77b68b0f547f52c3e2019667319cf0cf65f70`；草案SHA256 `01c6627c813b536d0b304128d0252f28d390518d0aaaaabb97f55d2009f5197c`。草案定义文件hash更新仅反映M10现行说明前缀，旧hash及0实际运行记录保留；不据收益改规则。最终准备代码/文档/结果hash、真实提交/CI见交付收据与artifact清单；实际账户代码/数据/规则hash保持null。

阶段A实际6官方文档请求等价（含2次RQData超时）、0 SDK/新市场请求；保存工具提取响应52,441字节，隐藏后台网络和wire字节未知；旧原件重读101,060,224字节不算新增下载。阶段A在07:47:26Z主动停止，四槽位全时段计等待的上界0.8965小时，低于2；总预算24累计小时/4096请求/8GiB/采购0均未因子任务重置。后续只本地实现/核验/交付。完整[资源账本](RESOURCE_LEDGER.json)及最终收据如实记录，不称人类工时。

公开分支`codex/m10-r2-data-and-screen`只增加实际源码、固定草案、合法元数据和独立材料；原始受限响应、财报全文及凭据不进入新增提交链。旧M9结果/原件不变，私有祖先未推送。按DELIVERY_POLICY安全推送并核验远端和CI，不自动合并main。完成本轮可达终点后停止，不能据工程通过写“股票Alpha已验证”。
