# A 股量化研究 MVP

本仓库是研究规范、实现与实验记录的事实来源。阶段二只进行离线研究。账户研究权限：主板、创业板允许；科创板个股、北交所禁止；ETF 独立核验。`live_enabled=false`，没有券商连接或下单代码。

首个研究策略为阶段一预注册的 R1B：ETF 中期相对强弱；透明基线为同池等权。四组 E0/R0/E1/R1 分离排名和趋势效应，共同波动缩放单独比较。所有结果都必须区分合成工程验证、真实日线筛查和最终确认性证据。

## 当前决策：归档R1，推进既定个股路线（2026-11-15）

已完成448条R1实验的机制、固定成本容量和风险审查，**归档当前配置，停止ETF参数搜索**。排序缺少跨期一致优势，趋势八个主要消融均为负，波动缩放降低风险但不能证明Alpha。10万元账户R1开启缩放的验证期年度增量费用容量点估计2,096.61元，开发期为−237.87元；这不是可承诺预算。验证最大回撤20.05%，超过风险政策12%的paper复核参考线。没有提出或执行新ETF方案；未来依据已看验证结果形成的方案必须标探索性。

R2、R3各自完成第一轮免费真实数据准入审计，**分别BLOCKED，真实个股绩效实验0次**。历史退市股和官方行业、原财务文档可取得，但全池历史状态/股本/公司行为尚未重建；R2原稿—修订完整案例仅1/20。R3不因R2财务或R1收益受阻，它有自己的行业、市值、状态和执行依赖。已经实现并独立检查PIT财务、价值/质量与R3残差研究核，修复股票执行误放行，红利税FIFO组件尚未接入完整主账簿；不将组件测试称作真实策略验收。

当前入口：[集中决策包](reports/m3_equity_admission/REVIEW_PACKET.md)、[R1归因与停止条件](reports/m3_equity_admission/R1_MILESTONE_REVIEW.md)、[真实个股数据审计](reports/m3_equity_admission/DATA_AUDIT.md)、[执行准入](reports/m3_equity_admission/EXECUTION_ADMISSION.md)、[独立准入审查](reports/m3_equity_admission/INDEPENDENT_ADMISSION_REVIEW.md)、[研究核审查](reports/m3_equity_admission/FEATURE_REVIEW.md)、[工程准备规范](docs/EQUITY_RESEARCH_PROTOCOL.md)、[当前验证与复现](reports/m3_equity_admission/VERIFICATION.md)。2025—2026最终集继续锁定；没有采购、paper或实盘。

## 已完成的真实ETF回测里程碑（冻结历史）

E0/R0/E1/R1的448条既定真实日频实验全部完成：开发2016—2021、验证2022—2024，两种波动缩放、四档本金和七条成本/执行/到账压力路径；主要本金固定10万元。免费路线已完成限定数据准入，保留历史退出产品；修复会计边界后，全部账簿/执行检查通过，本地及GitHub Windows CI均329项测试通过。

10万元base验证期的四组策略累计净收益均为负；R1的缩放关/开结果为−27.14%/−18.05%。相对基线的改善不等于已证实Alpha。正式经济确认仍BLOCKED_HURDLE，2025—2026最终测试集继续锁定，没有实盘。旧v1的353次完成/中止尝试全部保留并标记失效，当前只读评估与执行代码分别版本化。

当前入口：[里程碑审查包](reports/real_data_phase3/REVIEW_PACKET.md)、[全部448结果](reports/real_data_phase3/RESULTS.md)、[独立统计审查](reports/real_data_phase3/STATISTICAL_REVIEW.md)、[重现步骤](reports/real_data_phase3/REPRODUCE.md)、[数据限制](reports/real_data_phase3/DATA_LIMITATIONS.md)、[实现状态](docs/IMPLEMENTATION_STATUS.md)。下方免费探针与七产品采集段落是早期历史阶段，原320个NOT_RUN状态不代表当前已完成的448项矩阵。
## 安装与测试（Windows PowerShell）

```powershell
Set-Location F:\QuantTrade\Quant-Research
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest -q
```

当前验证环境 Python 3.9.19；依赖直接和间接版本见 `requirements.lock`，不修改系统 Python 环境。原始数据与 `runs/` 不进入 Git。

## 可复现的工程回放

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli fixture --output data/synthetic
.\.venv\Scripts\python.exe -m quant_research.cli audit --data data/synthetic --output reports/m0/synthetic_audit.json
.\.venv\Scripts\python.exe -m quant_research.cli run --data data/synthetic --output runs/smoke
.\.venv\Scripts\python.exe -m quant_research.cli matrix --data data/synthetic --output runs/core
# 加入成本2/3倍、零滑点、额外一天延迟；不从这些路径挑赢家
.\.venv\Scripts\python.exe -m quant_research.cli matrix --data data/synthetic --output runs/stress --stress
```

合成价格、合成证券和工作日日历只验证程序；不是中国市场数据，也不能证明 Alpha、策略可行性或真实样本外收益。相同数据、配置、源码与依赖下各账簿内容哈希应一致；run_id 中的时间仅区分重复尝试。

每次运行先注册，再保存配置、代码提交/未提交状态/源码哈希、数据哈希、环境版本、决策、订单、拒单、成交、费用、持仓、权益和结果表哈希。失败也写入追加日志，不覆盖旧结果。日志目录有单写者锁；异常终止后必须确认进程已停止再手工移除残留 `.runner.lock`。

## 真实数据接入与留出保护

按 `docs/DATA_SCHEMA.md` 导出带来源、许可、PIT 与历史覆盖证据的 JSON 数据包，先运行 `audit`。`load_dataset` 验证快照哈希；审计不合格的数据不能进入历史研究。不能将最新证券清单或前复权行情包装成合格历史样本。

`sample=development` 只接受截至2021年的数据；`sample=validation` 可带此前暖启动数据，账户评价从2022年开始，且仅为选择验证集。2025起数据必须物理分开；本 MVP 拒绝开启最终 holdout。M4 需补齐数据门槛、冻结候选、唯一主要本金、固定费用门槛及一次性访问记录后再扩展，而非传一个开关绕过。

R1I、财务 R2、股票 R3 和事件 R4 按其各自数据门槛推进。分钟撮合、完整股票公司行为和税务、历史行业穿透及实际费用核验未完成时，不能声称整个 A 股回测框架已验收。

进度与缺口见 `docs/IMPLEMENTATION_STATUS.md`、`docs/M0_DATA_AUDIT.md`；决策见 `docs/DECISION_LOG.md`；里程碑报告见 `reports/m0_m1/REVIEW_PACKET.md`。

## 历史记录：免费数据源探针

用户已确认主要统计本金10万元。免费数据源选择及实际接口记录见 `reports/data_sources/DATA_SOURCE_DECISION.md`。先评估BaoStock日线与交易日历，再与东财及官方公告对账。探针只取2023/2024固定小样本，不生成策略收益、不替代完整数据准入。

```powershell
# 标准库HTTP探针，无新增依赖
.\.venv\Scripts\python.exe scripts/probe_free_etf.py --output data/provider_probes/http
# 可选BaoStock通道放在独立环境，避免改变回测环境
python -m venv work/provider_env
.\work\provider_env\Scripts\python.exe -m pip install baostock==0.9.4 pandas==2.2.3
.\work\provider_env\Scripts\python.exe scripts/probe_baostock.py --output data/provider_probes/baostock
```

本次原始探测实际执行成功；上面整理后的两份重放脚本通过语法校验，未重复联网执行。供应商错误或空响应也保存，不将空值填成0。原始快照只留本地，不自动提交供应商数据到Git。

## 历史记录：首批真实样本采集与审计

已实际采集2019—2024七只ETF、十二个历史ETF截面及交易日历，保留512320退市样本。可在上面的独立provider_env中重放：

```powershell
.\work\provider_env\Scripts\python.exe scripts/collect_real_sample.py --output data/raw_baostock/replay_01
.\.venv\Scripts\python.exe scripts/audit_real_sample.py data/raw_baostock/replay_01 --output runs/real_audit_replay_01
```

也可使用本机已隔离解包的SDK：`.venv\Scripts\python.exe scripts/collect_real_sample.py --sdk-path work/data_probe/baostock_sdk`。新机器应优先使用显式安装的provider_env；本机临时SDK目录不随仓库分发。每次必须指定新目录，防止覆盖原始快照。采集器固定BaoStock0.9.4、单次20秒进程上限、请求间隔至少1秒、最多一次暂时错误重试；请求和响应均检查2024年末上界。

`data_audit.json`是观察层审计，`experiment_disposition.json`逐项保存开发/选择验证两区间的320个既定配置；数据尚未准入时均为NOT_RUN_BLOCKED_DATA，结果为null，不生成虚构收益。源码副本、源码哈希、Git状态和输入总清单哈希同时保留。报告见[真实数据里程碑](reports/real_data/REVIEW_PACKET.md)、[采集明细](reports/real_data/DATA_COLLECTION.md)和[独立审查](reports/real_data/INDEPENDENT_REVIEW.md)。历史快照重放可复现其审计；重新联网下载可能遇到供应商修订，因此必须另存并比较新旧哈希。

本轮另已保存中证H00300免费历史响应。使用已保存原件标准化基准（`--raw`为原始HTTP响应，不是ETF代用序列）：

```powershell
.\.venv\Scripts\python.exe scripts/normalize_csi_benchmark.py --raw data/raw_official/h00300_history_attempt.payload --calendar-collection data/raw_baostock/r1_audit_2019_2024_20261114T153136Z --output data/normalized_csi/replay_01 --expected-sha256 c29d358ab2a3edaa62bbf9c31226032b9513bbb52aebf35425499467012867c3
```

原始端点见脚本`--help`和`reports/real_data/benchmark_manifest.json`；新下载必须另存并重新审计，不要求与旧快照字节相同。该标准化保留全部原件，将唯一非交易日放入单独日志；1,456个交易日齐全也不代表历史PIT版本已验收。该步骤只处理已获取的原件，不隐式联网。
