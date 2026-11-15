# M5复现、验证与版本边界

基准 `8a9977cb5538a3ffd3c07506035c0dca7c3a0f14`；最终实现及交付提交由同目录verification.json和后续release_binding.json绑定。避免自引用commit：实现提交之后的纯交付收据只绑定既有实现及CI，不冒称基准已含新代码。所有M5源码、规则、输入与结果文件逐项SHA256见机器记录；此前独立审查快照保留原哈希。

## 可复现命令

PowerShell，仓库根目录；Python3.9.19，锁定环境requirements.lock。安装未增加实时交易接口。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.venv\Scripts\python.exe -m pytest -q tests review_code
```

完整本地档案可用时，以下均离线。前四条不会发出新请求；账户输出为工程账，不是Alpha回测。

```powershell
.venv\Scripts\python.exe scripts/m5_dependency_review.py
.venv\Scripts\python.exe scripts/m5_financial.py
.venv\Scripts\python.exe scripts/m5_execution.py
.venv\Scripts\python.exe scripts/m5_market_cap.py
```

这些构建器需要既有`data/admitted_r1/phase2_v1`、`data/raw_equity_admission`、`data/raw_m4_equity`、`data/raw_m5_equity`原档案，路径/URL/哈希分别列于各目录manifest、canonical facts、provenance及预算收据。原档案不默认外传；不自动重新抓取缺件。不同机器须按相同哈希映射原路径；不能把新的供应商响应当原档案。干净克隆仍可运行契约、已提交事实算术和独立反例；缺原件只跳过标记的归档核验，具体跳过范围见portability附录。

6份财务PDF的原始文本提取使用pdftotext24.04，独立视觉核对使用PyMuPDF1.26.5/Pillow10.0.0（单独工具环境），并保留原物理页/哈希和抽取方法。自动测试不声称每次重复人类视觉验收。真实日历fixture取自已核验的2015—2024日历，单独记来源及哈希；不含2025+数据。

## 结果与失败保全

最终本地全套：**689通过、0跳过，56.51秒**。保留一条M4夹具的pandas FutureWarning，不更改旧测试以消除提示。[干净克隆M5专测](PORTABILITY_ADDENDUM.md)：143通过、8项缺原件检查跳过，17.38秒；各机制断言仍执行。这两组计数范围不同，不能相加。

最终全套测试输出保存为`final_pytest.txt`，精确通过/跳过数、耗时、命令和运行时间进入verification.json；远程CI单独绑定其实际commit，不将本地测试当远程通过。没有原件的检查跳过不作为真实源PASS。

独立作者与reviewer的中间结果保留：依赖基准7失败；预算初轮2失败；账户初轮4失败；市值初轮2失败，均有具体反例和一次纠正。账户作者的固定数量开盘跳空反例在抓真实价格前登记修正。只读历史影响脚本首稿把原directory键误当run_id导致KeyError，保留日志并改为原字段后完成比较，未触发任何策略重放。预算恢复的调用方终态错误及Windows换行哈希初验失败分别保全。

测试与报告不输出CAGR/Sharpe/Alpha主张。110真实账户日无差异仅表示已阻断规则下的拒绝账一致；三例实仓事件验收仍BLOCKED。财务只有F02/F03数值通过，不能合称三因子通过。

原448 summary SHA256须严格等于`c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb`；M4原采集账本SHA256仍`44658bc3ba757c5bd3951e11106f42631143dac651fb40e089d3b1dbcb0ee8f6`。Git增量没有旧reports/m4或real_data_phase3改写。2025-01-01至2026-11-13市场/因子/策略结果未读；搜索索引夹带的未来规则标题仅隔离，不作为历史规则或留出证据。
