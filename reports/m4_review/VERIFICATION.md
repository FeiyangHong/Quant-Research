# M4验证与复现

日期2026-11-15，Asia/Shanghai。基准提交7d5bceb，当前开发分支codex/phase2-research-mvp。独立报告与verification.json绑定本轮实际源码/证据哈希；随后Git提交保存这些字节，不把新实现声称为旧基准已具备。

## 工程测试

```powershell
Set-Location F:\QuantTrade\Quant-Research
.venv\Scripts\python.exe -m pytest -q tests review_code
```

本地最终结果：**538 passed，38.74秒**；一项来自独立合成fixture的pandas FutureWarning保留在完整日志中。GitHub Windows工作流同步执行上述命令，包括仓库测试与独立审查反例。精确输出与输入版本见本目录verification.json及对应提交的GitHub Actions。独立审查发现的失败输出保留在本目录，修复后才纳入最终通过；早期501项阶段性通过不代替最终代码验收。

不需要真实数据即可执行的主账户工程回放：

```powershell
.venv\Scripts\python.exe scripts/replay_equity_engineering.py
```

六个输入明确synthetic，所有表标ENGINEERING_REPLAY_NOT_STRATEGY_PERFORMANCE。只核对股数/权益/现金/税及会计守恒，不输出策略绩效。入口只核验显式工程用途、synthetic声明及账户条件，不能独立鉴别任意输入的原始来源。本轮没有将真实数据改标synthetic；未提供真实R2/R3运行命令。

## 原档案上的只读复现

Git保存报告、机器归因与代码；原始供应商字节和旧完整账户仍保存在本地归档。迁移时需要完整旧data/admitted_r1/phase2_v1、runs/real_r1_development_v2、runs/real_r1_validation_v2，以及本轮data/raw_m4_equity和复用的M3原件；不能仅clone仓库就声称完成真实证据复算。

```powershell
.venv\Scripts\python.exe scripts/m4_frozen_review.py
.venv\Scripts\python.exe review_code/m4/verify_frozen_impact.py
.venv\Scripts\python.exe scripts/m4_data_build.py
.venv\Scripts\python.exe review_code/m4/audit_integrity.py
.venv\Scripts\python.exe review_code/m4/finalize_independent_review.py
```

这些命令不生成新策略账户、不改变ETF规则、不访问最终留出。冻结审查使用原运行manifest中的绝对归档路径；异机迁移须恢复或显式映射归档位置，不能悄悄改写原manifest或改用今天查询的数据。数据构建需要PATH上的pdftotext（本机Poppler24.04.0）；独立PDF审查源码及独立PDF环境要求见[原码快照](reproduction/README.md)，数据步骤另见[数据复现说明](../m4_data/VERIFICATION.md)。重新采集得到新字节时建立新数据版本，不覆盖原件。

交付检查另发现归因脚本的两个CSV文件名误加空格，现已仅修复输出路径并重跑只读归因和独立核对。重复的同字节ETF文件移除，只有浮点求和末位差异的账户表保存在[文件名修复记录](../m4_frozen/superseded_audit_draft/filename_spacing_repair/provenance.json)。这不改变旧策略账户、模型或配置；数值复算采用已登记的对账容差，非所有浮点聚合的逐字节相等。

旧448结果摘要必须保持SHA256 `c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb`。本轮未修改reports/real_data_phase3或reports/m3_equity_admission，也未重跑原注册策略；353失效/中止记录仍为原归档。

## 检查边界

- A四项基准反例和新增独立反例必须通过；原审计器字段覆盖故障的注入反例必须能发现真实持仓影响。
- 独立冻结核查检查4,356主表边界、全部448账户1,459,715仓位与78,545订单，并将年度ETF合计与原年度贡献比对。
- 六工程场景420日会计行由不读取引擎成交的独立期望计算器核对，另有非作者混合批次、部分卖出、时钟与风险指令用例。
- 58源对象的哈希/字节、全池身份与字段数、财务文档原页/值/时钟分层检查；哈希通过不代表全池完整或人工验收。human签核0，agent签核单列。
- 原风险估计器通过AST与基准版本比较确认未改；设计反例不更换协方差模型或扫描参数。
- 任何审计缺口或明确未支持事件保持BLOCKED，不靠删除困难样本使测试通过。

最终结果见[独立安全审查](INDEPENDENT_REVIEW.md)、[独立文档/截面审查](DATA_INDEPENDENT_REVIEW.md)、[集中审查包](REVIEW_PACKET.md)。M4完成不自动准入真实R2/R3、最终holdout、paper、live或采购。
