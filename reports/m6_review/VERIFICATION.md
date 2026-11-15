# M6 可复现验证与版本绑定

审查基准`5df2fc9f74dcc8ffc498e0a08562bb7f6156c958`；事前计划、原附件和56格登记提交`02d0f0d`。最终实现commit、树及Windows CI见本目录`release_binding.json`/`ci_receipt.json`；交付收据另列，避免文档自引用SHA。工作分支codex/phase2-research-mvp，保留原开发树、原结果，不merge主分支。

## 验证事实

|检查|实际结果|日志/边界|
|---|---|---|
|最终本地全套|779 passed、0 skipped、1 warning，62.07秒|`full_pytest_final.txt`；全部已归档源检查在本机实际执行|
|独立M6集合|70 passed、0 skipped，4.05秒|`independent_final_pytest.txt`，另有原件XLS/PDF/分页探针；agent不称human|
|旧诊断契约修正复查|91 passed，2.66秒|`diagnostic_contract_recheck.txt`，零成交保护未放宽|
|首次全套|778 passed、1 failed，62.33秒|`full_pytest_local.txt`原样保留；仅具体拒因字符串与旧笼统期待不同|
|R1I独立两轮|首轮18pass/2fail，最终23pass|中途指数恢复及混分类版本已修，不追加第三轮|
|真实事件|康美41日有仓PASS；两茅台34/35日BLOCKED|独立从固定指令/原价/手写Decimal推预期，不从fills/NAV反推|
|离线数据复现|两R1I生成器退出0、9份输出hash一致，新增网络0|`../m6_r1i/offline_verification.json`|
|源完整性与预算|69请求均终态，无超额；M4/M5保护hash不变|`source_budget_snapshot.json`、`integrity.json`、`COLLECTION_INCIDENT.md`|

warning为旧M4测试中pandas拼接空/all-NA列的FutureWarning，不是新增数据错误；未为消除警告扩大修复范围。独立费率baseline首次有2条浮点oracle过严断言，改按金额分位后11真实失败/18pass；原13fail和修正后的baseline日志均保留。股票源生成器首次一个括号语法错误已在生成结果前纠正，没有请求重试或额外采集；不记为Alpha实验失败。

GitHub CI只拥有Git版本化文件，不含ignored原件。预期缺源跳过为旧M5八项+M6四项（发现原件hash、采集事故原账本、真实manifest账户原件、股本原响应），实际数量与节点以`ci_receipt.json`和`ci_job_log.txt`为准；**跳过不算通过**。XLS/PDF独立探针依赖本机已有E:/Anaconda下xlrd2.0.1/PyMuPDF1.26.5，未声称干净CI自动运行该工具环境。没有新安装或网络补齐来掩盖缺原件。

## 复现命令

在仓库根，使用已锁Python3.9.19、numpy1.26.4、pandas2.2.3、scipy1.13.1、pytest8.3.5：

```powershell
.venv/Scripts/python.exe -m pytest -q tests review_code -ra
.venv/Scripts/python.exe scripts/m6_r1i_data_audit.py
.venv/Scripts/python.exe scripts/m6_r1i_data_finalize.py
.venv/Scripts/python.exe scripts/m6_stock_source.py inspect
.venv/Scripts/python.exe scripts/m6_stock_execution.py
E:/Anaconda/python.exe review_code/m6/independent_source_probe.py
.venv/Scripts/python.exe scripts/m6_closeout.py verify
```

后五个工程/审计命令要求hash匹配的归档源，缺源明确失败或特定测试显式skip；不能用网络重采不同版本代替。账户脚本将每次工程重放追加run_history/attempts，不覆盖M5原账；复现会生成新的工程尝试收据，不是新Alpha。数据脚本保留绝对来源路径；迁移机器需按source_manifest的hash将原档案映射到对应data目录，不能仅靠搜索结果恢复PIT。

本轮已执行一次股票`collect`及有限ETF/规则源pilot；复现应使用离线命令，**不要自动再次执行采集入口**。`m6_closeout.py bind`仅用于本次交付生成56条NOT_RUN侧表、保护文件核验及内容集合；以后验证用verify，不能重写已交付绑定隐藏差异。Git操作/CI查询不是研究来源采集，仍计入root会话等待；数据源请求口径见下表。

## 实际预算和代码/数据/规则hash

|分支|HTTP等价|SDK底层|可观察正文bytes|登记子边界|
|---|---:|---:|---:|---|
|R1I数据|46|0|4,508,462|初始有限pilot≤48 HTTP；主线总子额仍≤964|
|股票规则|20|0|473,893|40 HTTP/40MiB/4会话小时|
|股票批量合同|3|0|2,290,722|20 HTTP/20MiB/4会话小时|
|总计|69|0|7,273,077|1024 HTTP/1024 SDK/1GiB/24累计并行会话小时|

其中62次直接HTTP、7次外部发现工具；失败、分页全部计。SDK未新增；外部搜索后台请求及传输字节不可观察，不宣称实际网络绝不超过可见正文值。新预算原文件SHA256 `bcfbf8bf905338a5d4116f2168320db0bff5c9385b6fabc54ef329f7623f4757`。会话按保守共同起点12:54UTC到各agent结束/根交付检查点，包含等待并行求和；精确秒数与两个股票子额的保守计入见`session_usage.json`，不是人类工时或交期预测。

`content_manifest.json`逐文件绑定生产模块、采集/审计脚本、独立测试、规则/固定账户输入、全部M6机器表、审查文档及日志；其规范化路径→SHA集合还有整体hash。来源实际bytes及URL/终态/hash在预算快照，来源位置/用途/公开与有效时钟在各分支manifest/证据表。源码/规则的包含关系不依赖聊天记忆。

保护值：

- 原448汇总：`c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb`。
- M4原账本：`44658bc3ba757c5bd3951e11106f42631143dac651fb40e089d3b1dbcb0ee8f6`。
- M5原账本：`89e0c9f7088c3f8bffa9af4f5d1cfe36347cd041ff1342ce578a91d9a78d8a82`。
- M6原56格注册：`9e799ccb30fddf9e51a4c1637362c9573a77f68dd5cc481004be2878992def96`。

原R1B报告、M5财务/账户/市值/审查报告与configs相对基准无修改；448+353未重放。共享双时间默认行为保持，仅增加显式历史有效日查询用于已知版本下的季度内身份核验。普通R1I/R2/R3策略入口仍关闭。

## 已通过、未通过与未做

通过的是有限正确性/独立oracle/真实康美固定账户/批量能力及停止证据。未通过的是完整R1I历史依赖与识别门槛、两茅台有仓分红事件、股票全池PIT市值及R2/R3正式准入。未做56收益、bootstrap、IC、经济增量及新风险模型，因为真实数据gate未过；未获取全历史PDF/全389页股本，因为固定范围与预算事前限制。搜索未来片段暴露、政府媒体转载级别、scope字节全局停、未知固定成本/CI返回依赖均如实披露于集中包和独立报告。
