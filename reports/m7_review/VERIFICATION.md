# M7验证、复现与边界

实际32账户全部使用执行提交`679e80813daefea0b5fb312d120e7ada9b8cc40a`，事前登记`18eeba4d37039f3cffb8e83e34fc6a3198f18a0d`，审查基准`da1003a5c783d9bf4cd86e56816637d7b3af79f9`。报告/独立测试后续提交没有重放账户。源内容哈希`91868508b3a79b5cb935f1967f2e5b6d918df79e03ae9587f8e838f1fa16b85c`在32条间相同；执行目录保存实际源快照，Git提交不是对dirty状态的隐瞒。

## 已执行检查

|检查|实际结果|证据|
|---|---|---|
|本地完整回归|829 passed、0 skipped、1既有FutureWarning，73.97秒|local_full_tests.txt；不是只跑M7测试|
|统计缺陷复现与独立oracle|13独立统计检查通过；None/0/1000描述不变，经济门槛分离|independent_baseline_statistics.json、independent_statistics.txt、review_code/m7/test_independent_statistics.py|
|策略/主账户边界|首轮11、唯一修正后14独立检查通过；作者相关61项通过|independent_cohort.txt、independent_correction.txt；独立Decimal有仓合成账户不是历史绩效|
|原始数据核验|13 SDK响应页、15,225日、七上市及退出/拆分原件、107资格及57趋势ON|independent_raw_probe、independent_document_probe、independent_opportunity_probe及stage_review|
|base检查点|8账户/8,748日通过，会计误差0|BASE_CHECKPOINT、independent_base_checkpoint；利润不是继续条件|
|完整真实矩阵|32账户/34,992日、40配对描述、144账户年/1,008产品年通过|independent_all32_accounts、independent_evaluation_probe；没有NOT_RUN伪造现金|
|旧档案|旧R1B/M4/M5/M6报告树相对基准无diff，保护hash一致|FROZEN_ARTIFACTS.json；旧448未重跑|
|初次CI|816 passed、12 skipped、1 failed，76.93秒|ci_initial_failure.txt；旧Git提交在浅克隆不存在，非账户故障|
|CI测试修正|固定基准blob SHA核验，未跳过；聚焦3项通过|independent_ci_portability_fix.txt；同时纠正reviewer旧summary路径及exists守卫|
|交付内容CI|817 passed、12 skipped、1既有warning，74.48秒|ci_receipt.json、ci_job_log.txt；缺原件的跳过不算通过|

首次CI：[run43729568526](https://github.com/FeiyangHong/Quant-Research/actions/runs/43729568526)，job132858800768。修正后交付内容提交`2ca1b0ed235180dfba6b35521012ff13aa9c9dcf`的[CI43730783785](https://github.com/FeiyangHong/Quant-Research/actions/runs/43730783785)成功，job132862501864，实际PR合并检查SHA`70efb7f16ec257a2b2e118856c5629e9c3b3a7e1`，不等于已合并PR。修正只在review_code，未改变32账户的源码hash或原结果。旧测试原先要求未知费CI=null的断言随授权接口语义更新，原失败日志legacy_assertion_before.txt保留；经济阻断与null费用断言增强。之后版本收据提交只保存这些事实，不伪称该收据已在前一次CI中出现。

生产各组件首稿加一次有依据的修正；统计描述无参数变化。来源同标签不同URL的组装问题、32条低额成交量价微差、reviewer名称/期望/路径错误和CI故障全部记录，见DATA_AUDIT与independent_probe_history。真实差值恒0，30个登记区间状态在退化检查处返回，未声称实际执行了无意义的5000次重采样；非退化合成独立检验确实执行5000次。

## 复现

本机使用`.venv/Scripts/python.exe`，Python3.9.19、numpy1.26.4、pandas2.2.3、scipy1.13.1、pytest8.3.5。包由requirements.lock固定。源PDF渲染/手核使用本机既有Poppler和PyMuPDF，不是CI自带能力。

只读核验现有账户：

```powershell
.venv/Scripts/python.exe -m pytest -q tests review_code
.venv/Scripts/python.exe review_code/m7/independent_raw_probe.py
.venv/Scripts/python.exe review_code/m7/independent_account_probe.py --expected-count 32
.venv/Scripts/python.exe review_code/m7/independent_evaluation_probe.py
```

后3个命令要求本机哈希匹配的已归档源；没有原件不能宣称完成独立源核验。它们只生成同名审查收据，不重跑旧ETF或股票。账户运行实际命令如下；若需完整重建，应在执行提交679e808的隔离副本中恢复source_manifest所列已授权原件及stage_v1，再作同一准入。**不要在交付目录重跑覆盖；m7_run会拒绝已有trial_id，任何正确性重放须另登记并保留本版。**

```powershell
.venv/Scripts/python.exe -c "from quant_research.cohort_runner import admit_cohort_samples; admit_cohort_samples('data/m7_fixed_cohort/stage_v1','reports/m7_review/independent_admission_attestation.json','data/m7_fixed_cohort/admitted_v1','.')"
.venv/Scripts/python.exe scripts/m7_run.py --admitted data/m7_fixed_cohort/admitted_v1 --output runs/m7_real --phase base
# 已核base会计有效；本轮继续不以盈利或用户逐格批准为条件。
.venv/Scripts/python.exe scripts/m7_run.py --admitted data/m7_fixed_cohort/admitted_v1 --output runs/m7_real --phase stress
.venv/Scripts/python.exe scripts/m7_evaluate.py
```

本轮没有再采集命令待自动运行。raw_m7原件留本地，Git保留可分享身份/源索引及衍生账户表。不得把今天重采的不同字节替换哈希不一致的历史版本。当前研究入口仍只允许已登记32格；普通R1I、股票Alpha、最终留出和实盘不开放。

## 哈希与资源

|对象|SHA256|
|---|---|
|开发Dataset内容|f29b515bee89e89bfba01be007399b81de3d6b866555187d8eb0288fd7ed3317|
|验证Dataset内容|9dd8408154132efb43c9981b4864f9faaf723f2b11158d8dbc51bd5bdc0677d9|
|32注册表原文件|a00588737fcd5d2cd85e0c18df896821d1614bc3fed04305a07b59ca8940ce01|
|计划/规范/注册绑定集合|b8582383246d6913cd0c25d58e59422827b4613c019058d724714c245fcdbc3a|
|独立准入收据|15e34c8f6e721c8739ed5a1ed342700bf185ab2395f27c20853e592c4c81179e|
|实际ACCOUNT_PATHS|7c56d215b0afaec04cc44e428e905bf6141e2a226b41e52ef85e50edffdb7304|
|RESULTS_SUMMARY|b3dde40ba73bd5065cfe545e33ba9067437be09ea521d2dee5ddf22c29191c97|
|原主账户execution.py|9198a41981dc2e968964a61c5f71b5f3427f0e28cca670ec20bb4432d70ba863|
|M7来源预算账本|777aa36ce2d67527438e624541df2b7ccd55b83100306070ca2a5dec9159247a|

各账户config/source/data/规则文件和15账表哈希均在其provenance/table_hashes及ACCOUNT_PATHS，完整衍生文件集合另在ARTIFACT_HASHES。报告提交不会冒充原运行提交。

来源56/256 HTTP等价、15/128 BaoStock底层、9,842,572/268,435,456可观察字节（9.3866MiB）；SDK含登录/退出和分页。M4/M5/M6账本未重置。共享预算实际字节可核，不保证SDK网络传输绝不先超包。本轮没有来源超限；Git/CI传输不计研究来源采集，但等待纳入root会话记录。

并行会话按14:55:00Z保守共同起点、真实可观察结束时点求和，含等待，不是人工工时：数据1,626秒、策略1,601秒、独立2,157.718475秒；root截至最终收据的持续时间与合计见RUN_PROVENANCE，12小时上限不变。没有把零网络reviewer说成零会话投入。

CI无ignored本机原件，12个跳过项为M5费用规则1、财务PDF6、股本原响应1，加M6采集事故账本/身份原响应/真实账户原件/股本批次各1；完整节点清单见ci_skip_inventory.json。跳过不算通过。M7原件和32真实账户的独立核验在本地单独执行，不声称CI重新下载或重放了真实来源。
