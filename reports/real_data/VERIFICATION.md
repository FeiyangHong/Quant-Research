# 真实数据阶段验证记录

日期：2026-11-14。环境：Windows PowerShell；项目venv Python3.9.19；锁定的numpy1.26.4、pandas2.2.3、scipy1.13.1、pytest8.3.5。BaoStock0.9.4是可选依赖，本次采集使用隔离解包的SDK；不修改全局Python或交易账户。

## 实际执行

| 命令/检查 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **177 passed in 25.68s**；完整工程测试，不是真实策略收益检验 |
| `scripts/collect_real_sample.py --sdk-path work/data_probe/baostock_sdk` | 27/27请求首次SUCCESS；7只ETF/9,176日线、12历史截面/8,714观察；原始目录和总hash见DATA_COLLECTION |
| `scripts/audit_real_sample.py data/raw_baostock/r1_audit_2019_2024_20261114T153136Z --output runs/real_audit_v2` | integrity_status=PASS；27计划/27验证；errors=[]；整体BLOCKED_DATA，strategy_runs_permitted=false |
| `scripts/normalize_csi_benchmark.py --raw data/raw_official/h00300_history_attempt.payload --calendar-collection data/raw_baostock/r1_audit_2019_2024_20261114T153136Z --output data/normalized_csi/h00300_2019_2024_v1 --expected-sha256 c29d358ab2a3edaa62bbf9c31226032b9513bbb52aebf35425499467012867c3` | STAGING_ONLY；1,456交易日，1非交易日保留并显式隔离；不是PIT准入 |
| 独立原始文件及事件复核 | 23份PDF哈希；官方H00300原件；非master历史响应均无2025起观察；见INDEPENDENT_REVIEW |
| setuptools包发现和模块列表 | quant_research.providers与两个数据源模块/worker可打包；离线CI不依赖匿名数据源在线 |
| `git diff --check` | 无差异格式错误 |

v1审计在独立修复前产生，保留以便追溯；最终复制到本报告目录的是v2审计及源码指纹，不能混用。`audit_provenance.json`记录实际审计时的Git基准提交与dirty=true，以及准确源码内容hash和每个文件hash；完整源码副本在v2的source_snapshot。后续把这些文件提交Git不改变已经运行的代码内容，提交本身不是回填的执行时点。

基准标准化目录另含原始HTTP响应副本、日历证据、标准化观察、排除日期日志及8个文件摘要。其嵌入日历审计属于该次标准化时点，不覆盖后续v2报告；原始日历和价格字节一致。

## 实验和解释边界

真实策略执行次数为0、统计检验次数为0。320个开发/选择验证预定配置均保存为NOT_RUN_BLOCKED_DATA，指标null。原M0/M1的160个合成场景保持其原始源码/数据版本，不以本次代码更新冒称已经重跑。

没有使用2025—2026最终测试来选模型、参数或本金；没有新增策略方向；没有发送数据采购咨询、购买服务、连接券商或下单。后续数据准入和真实对照需另立不可变运行目录。
