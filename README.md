# A 股量化研究 MVP

本仓库是研究规范、实现与实验记录的事实来源。阶段二只进行离线研究。账户研究权限：主板、创业板允许；科创板个股、北交所禁止；ETF 独立核验。`live_enabled=false`，没有券商连接或下单代码。

首个研究策略为阶段一预注册的 R1B：ETF 中期相对强弱；透明基线为同池等权。四组 E0/R0/E1/R1 分离排名和趋势效应，共同波动缩放单独比较。所有结果都必须区分合成工程验证、真实日线筛查和最终确认性证据。

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

## 免费数据源探针

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
