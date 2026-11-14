# 真实 R1B 日线研究重现说明

本文记录可执行入口、固定输入和验收条件，不声明真实实验已完成，也不填入尚未运行的收益、回撤或检验数字。执行状态以目标目录中的追加注册日志、`matrix_summary.json` 和评估器实际输出为准。准入范围是 **DAILY_SCREEN_ONLY**；`live_enabled=false`，没有实盘授权。

主要统计本金固定为 **100,000 元**；10,000、500,000、1,000,000 元是整手、最低佣金和容量敏感性账户。开发账户从2016年开始、截至2021年；验证账户从2022年重新注资、截至2024年，不继承开发账户持仓或现金。更早价格只作暖启动。**2025—2026最终留出仍锁定**，本流程不能开启它。

## 1. 环境与路径

以下命令以 Windows PowerShell 和仓库根目录为准。依赖版本由 `requirements.lock` 固定；当前研究环境为 Python3.9。已经安装的环境无需重新安装。

```powershell
Set-Location -LiteralPath 'F:\QuantTrade\Quant-Research'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest -q
```

正式研究优先使用 `python -m quant_research.cli`。本机工具链直接执行含非ASCII源码的脚本时偶有编码故障，因此下面的独立脚本入口统一通过 `-c` 加 `runpy.run_path`，参数仍由原脚本解析。这不会更改输入编码或源文件。

归档原件不随Git提供。要重放已审查版本，须在本地保留下表和其清单引用的所有原件，包括 `work/policy_rule_probe/` 中已被哈希绑定的规则证据。不要转换文件换行、重新排版JSON或手改路径；字节变化会使原准入签认失效。迁移路径或重建快照须重新核对和审查。

| 固定输入 | 用途 |
|---|---|
| `data/raw_r1_universe/r1_2010_2024/universe_manifest_v3.json` | 2010—2024日历、首日及60个季末历史成员截面、原始请求和失败/修复记录 |
| 同目录 `inventory_documentary_v6.json`、`candidates_documentary_v6.json`、`documentary_manifest_v6.json` | 保留1,148个发现身份；110个有官方分类证据的竞争产品；不可只保留当前存续产品 |
| 同目录 `histories_b87b8e5ad646_v4.json` 及 `query_cache/`、`raw/`、`normalized/`、`manifests/` | 110个历史行情请求、127,090条原始观察和逐层哈希 |
| 同目录 `provisional_dependencies_v7.json` | 最终117条主表版本对应的独立成交额代表计算；该旧字段名下列的是16只代表并集，不等于15只可达特征依赖 |
| `data/raw_r1_actions/listing_110/master_records.json` | 110个身份的117条原始/变更主表版本，保留159908转换及六个退市竞争产品 |
| `reports/real_data_phase3/event_manifest.json` 及其 `source_root` | 29个核对后的经济事件、公告修订/取消记录和官方PDF；不能只复制解析后的数值 |
| `data/normalized_csi/h00300_2010_2024_v1/` | 中证H00300全收益基准的原件、标准化表、日历对账；不是ETF替代基准 |
| `configs/r1_build_policy.json` | 历史规则、明确的假设账户、原始/全收益可用时间、事件现金模型、来源哈希 |
| `data/staged_r1/phase2_build_v3/` | 独立审查所绑定的完整暂存表和构建报告；v2不在此次准入范围内 |
| `reports/real_data_phase3/admission_attestation.json` | 独立签认、逐门槛限定范围、原始证据与暂存表哈希 |

## 2. 采集与原始证据链

采集链为：历史成员发现 → 官方原始身份/转换/退市核对 → 全部竞争者行情 → 独立成交额代表计算 → 可达事件与全收益依赖 → 第二来源对账及争议裁决。既有免费采集和限定范围见 [UNIVERSE_AUDIT.md](UNIVERSE_AUDIT.md)、[EVENT_AUDIT.md](EVENT_AUDIT.md)、[ADMISSION_REVIEW.md](ADMISSION_REVIEW.md)。SDK快照保存的是SDK返回字段/行，不声称捕获了交易所原始网络报文。

重新联网会取得供应商**当前修订版**，不保证复现旧下载字节。新抓取必须使用新目录，保留失败/空响应，重新走官方核对、哈希、policy和独立准入。以下是新采集入口，不是更新已签认快照的命令；本次重放若已有完整归档，应从第3节开始。

```powershell
# 可选数据通道使用隔离环境；不修改冻结研究环境。
python -m venv work/provider_env
.\work\provider_env\Scripts\python.exe -m pip install baostock==0.9.4 pandas==2.2.3
.\work\provider_env\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_r1_universe.py', run_name='__main__')" --stage inventory --output data/raw_r1_universe/replay_01

# 对已冻结110候选重新取原始行情；新发现的身份须另做官方核对，不能自动继承v6分类。
.\work\provider_env\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_r1_universe.py', run_name='__main__')" --stage histories --candidates data/raw_r1_universe/r1_2010_2024/candidates_documentary_v6.json --output data/raw_r1_universe/replay_01

# 为CSI标准化导出既有日历清单项；不修改原始日历内容。
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from quant_research.providers.baostock import write_immutable; p=Path('data/raw_r1_universe/replay_01'); write_immutable(p/'calendar_query.json',json.loads((p/'universe_manifest.json').read_bytes())['calendar'])"
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_csi_history.py', run_name='__main__')" --start 2010-01-01 --end 2024-12-31 --output data/raw_csi/replay_01
$csiRawSha = (Get-Content -Raw -Encoding UTF8 -LiteralPath 'data/raw_csi/replay_01/manifest.json' | ConvertFrom-Json).sha256
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/normalize_csi_benchmark.py', run_name='__main__')" --raw data/raw_csi/replay_01/response.payload --calendar-collection data/raw_r1_universe/replay_01 --expected-sha256 $csiRawSha --start 2010-01-01 --end 2024-12-31 --output data/normalized_csi/replay_01
```

BaoStock匿名会话串行运行；不要同时启动多个采集进程。`--repair-failed` 是保留原失败对象的有界修复入口，不是覆盖失败或无限重试。新CSI下载应先确认捕获成功并核对清单SHA256；`--expected-sha256` 固定原始响应，但不使新下载继承旧快照的准入结论。

官方公告收集器也支持重新核对。以下以已保存且已核验的日历作为公告时间基准，使用独立新输出；若改用新日历，应从其清单读取真实路径并核对哈希。

```powershell
$calendarRaw = 'data/raw_r1_universe/r1_2010_2024/raw/6c53baad9d880219_fba4a743f5_a1_00ea4bd4d692d85808180cd9884c9ab9b85777cbae6ae197bfd08873cec626fe.json'
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_r1_actions.py', run_name='__main__')" --listing-only --original-index-documents --candidates data/raw_r1_universe/r1_2010_2024/candidates_documentary_v6.json --calendar $calendarRaw --output data/raw_r1_actions/replay_listing_01 --report work/replay_listing_manifest_01.json
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_r1_actions.py', run_name='__main__')" --candidates data/raw_r1_universe/r1_2010_2024/candidates_documentary_v6.json --calendar $calendarRaw --output data/raw_r1_actions/replay_actions_01 --report work/replay_event_manifest_01.json
```

原始上市公告、招募书、转换及退市通知必须分别定时。`--identify-dead`、`--global-index-changes`、`--conversion-documents`、`--delisting-documents` 是补足身份链的入口；官方文件筛选、取消计划与最终条款核对仍是有证据的人工作业，采集脚本不会自动证明完整性。2025年公布的2024年度报告只用于回溯完整性审计，不进入当年的信号特征，更不能作为2025价格输入。

冻结版本的离线身份核对、独立代表计算命令见 `UNIVERSE_AUDIT.md`。完整的当前依赖计算入口如下；采用新版本号避免覆盖旧诊断，旧v6仍保留其原始输入快照。

```powershell
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/collect_r1_universe.py', run_name='__main__')" --stage dependencies --output data/raw_r1_universe/r1_2010_2024 --candidates data/raw_r1_universe/r1_2010_2024/candidates_documentary_v6.json --universe-manifest data/raw_r1_universe/r1_2010_2024/universe_manifest_v3.json --history-manifest data/raw_r1_universe/r1_2010_2024/histories_b87b8e5ad646_v4.json --master-records data/raw_r1_actions/listing_110/master_records.json --revision 8
```

v7是已冻结基准；上述v8只作新的重放诊断，若v8已存在再选择未占用版本，不能覆盖旧清单。

第二来源的三个入口是 `collect_eastmoney_check.py --codes ... --output ...`、`reconcile_eastmoney.py --primary ... --secondary ... --output ...`、`adjudicate_price_disputes.py --audit ... --root ... --output ...`。准确原始输入路径由 `SECONDARY_PRICE_AUDIT.json` 及其引用清单固定。对账不能按哪条价格产生更好收益选择主源；第三源响应中非请求日期的当前行情字段须继续隔离。

## 3. policy与暂存构建

生成器把声明的规则和账户场景映射到有哈希的证据，不赋予数据准入资格。先写到独立核对目录，再与冻结policy比较，不覆盖已签认文件。

```powershell
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/create_r1_build_policy.py', run_name='__main__')" --output work/reproduce/r1_build_policy.json --report work/reproduce/RULE_MAPPING.md
Get-FileHash -Algorithm SHA256 -LiteralPath 'configs/r1_build_policy.json'
Get-FileHash -Algorithm SHA256 -LiteralPath 'work/reproduce/r1_build_policy.json'
```

本次签认的policy SHA256为 `be5c0acb71ab795ff8b425ea33b96620c69174c085635ad865030ef048696e29`。Windows相同输入可生成相同字节；其他平台的换行差异也属于字节差异，不能手工替换签认哈希。

原始行情保持未复权报价；全收益链另由事件生成，并保存独立可用时间。晚公布的2015份额比例不能回填早期持仓或特征。逐账户FLOOR/CEIL、BOD/EOD、停牌旧单位报价和拆分后分红权益均依事件证据处理。16个季度代表保留在竞争中；15个可达特征/持仓依赖需完整公司行为。159573截至2024年只有247个上市交易日，未达252日门槛，不能用替代产品填它的名额。

已有v3不得覆盖；重建使用新目录：

```powershell
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/build_r1_dataset.py', run_name='__main__')" --collection data/raw_r1_universe/r1_2010_2024 --benchmark data/normalized_csi/h00300_2010_2024_v1 --events reports/real_data_phase3/event_manifest.json --policy configs/r1_build_policy.json --output data/staged_r1/phase2_build_replay_01
.\.venv\Scripts\python.exe -m quant_research.cli audit --data data/staged_r1/phase2_build_replay_01 --output work/reproduce/stage_audit.json
```

暂存状态仍为 `STAGING_ONLY`，门槛未晋升时审计阻断是预期保护。`build_report.json` 中结构错误、构建阻断和独立依赖必须逐项解决，不能只改状态。重建会记录新的处理时间，因此新暂存manifest通常不同；经济输入相同也不等于旧签认可直接复用。

## 4. 独立签认与物理分样本准入

独立审查人核对完整来源链、原始和解析哈希、原始身份时间线、可达事件范围、价格争议、规则、假设账户与许可后，形成 `admission_attestation.json`。签认不是由生成器自动写出，也不是实盘批准。任何新输入、不同stage或策略语义变更都需要重新审查。

此次现成签认只绑定 `data/staged_r1/phase2_build_v3/manifest.json`，SHA256为 `6daef61590b4a659d35e42043f5ac6706fda78908f6b631ac5acb40316d07340`。可以先只读验证，再机械准入：

```powershell
.\.venv\Scripts\python.exe -c "from quant_research.admission import verify_attestation; r=verify_attestation('data/staged_r1/phase2_build_v3','reports/real_data_phase3/admission_attestation.json','.'); print(r['decision'])"
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/admit_r1_dataset.py', run_name='__main__')" --stage data/staged_r1/phase2_build_v3 --attestation reports/real_data_phase3/admission_attestation.json --output data/admitted_r1/phase2_v1 --repo .
.\.venv\Scripts\python.exe -m quant_research.cli audit --data data/admitted_r1/phase2_v1/development --output work/reproduce/development_audit.json
.\.venv\Scripts\python.exe -m quant_research.cli audit --data data/admitted_r1/phase2_v1/validation --output work/reproduce/validation_audit.json
```

准入器核对签认、所有引用证据、stage各表及原始源哈希；重新计算分样本依赖并要求审计 `PASSED`。结果包括各样本的 `manifest.json`、`admission_audit.json` 和上级 `sample_manifest.json`。开发表物理截至2021年；验证表可带早期暖启动，但账户从2022年初始现金开始。2025-01-02仅用于给2024-12-31基准观察打可用时间戳，不增加2025模拟交易日或价格。

## 5. 冻结源码后运行448项预注册实验

执行前固定 `src/`、`scripts/`、`configs/`、`tests/`、`requirements.lock`、`pyproject.toml` 和四份研究规范；这正是runner保存源码哈希/快照的范围。两个样本的全部运行必须使用同一源码快照。先完成工程检查，不在矩阵途中修策略、重排源文件或改费用。

两组矩阵各224项：四档本金 × E0/R0/E1/R1 × 波动缩放关/开 × 七条路径。E0等权、R0排名、E1等权加趋势、R1排名加趋势；不事后挑一个最好本金或配置作为主要检验。

| 路径 | 非税成本倍数 | 滑点倍数 | 决策后执行间隔 | 模型现金额外延迟 |
|---|---:|---:|---:|---:|
| base | 1 | 1 | 1交易日 | 0 |
| cost2_slip2 | 2 | 2 | 1交易日 | 0 |
| cost3_slip3 | 3 | 3 | 1交易日 | 0 |
| slip0 | 1 | 0 | 1交易日 | 0 |
| delay2 | 1 | 1 | 2交易日 | 0 |
| cash_delay1 | 1 | 1 | 1交易日 | 1交易日 |
| cash_delay3 | 1 | 1 | 1交易日 | 3交易日 |

所有路径保留同一月末D信号锚点；基准日期精度导致D+1交易日21:00才决策，基准执行为D+2，delay2为D+3。D+1参考价格/ADV仅用于下单资金与数量，不把信号锚点移到D+1。佣金基准3bp、每实际订单最低5元，是冻结研究场景，不是已核验历史券商报价。

```powershell
.\.venv\Scripts\python.exe -m quant_research.cli matrix --data data/admitted_r1/phase2_v1/development --config configs/r1b_real_development.json --output runs/real_r1_development_v2 --stress
.\.venv\Scripts\python.exe -m quant_research.cli matrix --data data/admitted_r1/phase2_v1/validation --config configs/r1b_real_validation.json --output runs/real_r1_validation_v2 --stress
```

旧v1因精确十进制佣金、成交金额和滑点金额的舍入缺陷，已标为 `FAILED_ENGINE_FEE_ROUNDING` 并保留。开发224条及停止前验证128条的工程核证见 [旧v1审查归档](execution_review_v1_failed.json)，不能用它们形成最终结论。上述v2要求修复后的源码重新冻结并完整运行；若v2已经存在，请另用未占用的新重放版本，并将下方审查/评估参数同步修改。不能把再次完整运行追加到已完成矩阵后只留下最后的summary。当前CLI没有自动断点续跑。失败原因及已注册尝试不得删除；异常中断须确认进程确已停止，才可处理残留锁，并记录重跑和修复的对应关系。

每次尝试先写 `trial_registry.jsonl`，再保留配置、环境、源码快照、数据审计、决策、订单及订单事件、拒单、成交、费用、现金事件、持仓、NAV、权益和份额事件。成功有表哈希和 `COMPLETED`，失败有 `failure.json` 和 `FAILED`；只在完整矩阵结束后形成 `matrix_summary.json`。run_id中的时刻可变化；核对的是配置/源码/数据身份和账簿内容，不是要求所有尝试共用一个run_id。

## 6. 评估与验收

两组矩阵完成、写者锁释放后，运行：

```powershell
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/evaluate_real_runs.py', run_name='__main__')" --development runs/real_r1_development_v2 --validation runs/real_r1_validation_v2 --output reports/real_data_phase3
```

评估器要求两个样本分别具备全部224个唯一配置，核对注册/终态、输入配置、源码快照、数据和输出表哈希、账户日历以及保留的失败尝试；独立重算现金、持仓、应收与NAV账簿算术和收益指标。失败时拒绝发布新的结果，不能用残留旧结果充当本次验收。此独立算术核对不替代市场数据事实审查。

执行工程复核代码与toy故障注入源码保存在 [review_code](review_code/README.md)，不依赖临时未归档实现，不复制供应商raw。先验证审查器能检出预设错误，再读取完整矩阵：

```powershell
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('reports/real_data_phase3/review_code/test_execution_review_toy.py', run_name='__main__')"
.\.venv\Scripts\python.exe -c "import runpy; runpy.run_path('reports/real_data_phase3/review_code/review_real_execution.py', run_name='__main__')" --development runs/real_r1_development_v2 --validation runs/real_r1_validation_v2 --data data/admitted_r1/phase2_v1 --output reports/real_data_phase3
```

该脚本只读已有运行，不调用策略或执行引擎。未完成的矩阵标为待完成，全部448条实际核验通过才会写总状态PASS；任何数值差异均保留，不作容差吞并。输出为 `EXECUTION_REVIEW.md` 和 `execution_review.json`，代码SHA与逐运行表SHA随报告绑定。本复核由实现者进行，不能替代另行出具的独立统计和库存审查。

只有成功后才产生 `results_summary.json` 和 `RESULTS.md`。报告须展示全部448项、年度贡献、费用/滑点、现金/敞口/集中、换手、拒单及配对压力结果。主本金base路径的排名配对诊断分别为R0−E0、R1−E1，并保留两个缩放设置；不能将开发和验证拼成一次最终测试。

未知年度增量运行费用保持 `annual_incremental_cost=null`、正式经济确认 `BLOCKED_HURDLE`。探索性零固定费用假设下的bootstrap只是有标签的辅助诊断；四假设族未就绪的p=1是占位值，不是证实结果。没有因子收益输入便没有因子Alpha，日线成交不证明分钟窗口/队列可实施，所有输出都不等于个人真实盈亏。后续边界见 [DATA_LIMITATIONS.md](DATA_LIMITATIONS.md)。

## 7. 本地保存与分享

此次来源许可审查仅覆盖本地非商业研究。原始行情、SDK响应、官方PDF归档、第三方完整价格表和含这些原件的数据包不得自动推送Git、云端或公开发布；可访问不代表可再分发。`data/`、`runs/` 的本地归档要另行备份，分享代码/摘要时先检查没有夹带原始表、访问凭据或未授权内容。商业使用、数据托管、公开再分发和执行服务须另行取得相应授权。本流程不要求采购，也不授权下单。
