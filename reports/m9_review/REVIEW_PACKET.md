# M9集中审查：固定风险预算实验已完成

**动态VE相对固定CE的效用增量仍为INCONCLUSIVE。24/24路径完成，0失败、0未运行。** 验证日均评分差+0.0000330792，95%主区间[−0.0000934824,+0.0001522180]；开发及固定压力符号检查通过，不能替代主区间。验证VE波动11.69%低于CE14.55%，累计收益−9.23%低于−7.46%，最大回撤27.11%略高于26.99%。更多现金伴随更低风险，不能称已识别纯波动择时Alpha。

先读[投资结果](../m9_risk/RESULTS.md)与[净值图](../m9_risk/base_nav.png)。评分与净收益、绝对效用与相对差、开发与已观察验证分别报告。保留直接篮子风险工程和CE研究基准；归档当前动态政策的确认性主张及VR兼容收益实验，停止本轮搜索，不改变旧M8结论或开放下一阶段。

## 已完成与边界

|任务|状态与证据|
|---|---|
|附件/增量/登记|PASS。公开540fdf3无后续增量；完整本地8d8796c为已有M8工作，未回退。附件原字节入docs，M9_PLAN与24格在a696c13先提交推送。|
|实际源码恢复|PASS。M8公开补丁恢复至src/scripts/tests，134源文件核对中133与原账户版本相同，绘图一项为已公开后续修正；18个独立M8脚本恢复。公开CI真实运行M8/M9，不再只测旧M7。|
|原数据绑定|PASS（原准入范围）。558个原件/证据指针与14个两期准入文件核对，数据hash与M8一致；新市场请求0。保留DAILY_SCREEN_ONLY与历史来源重建局限。|
|风险与固定c|PASS。当前未缩放篮子60日样本std、至少45同步日、双端点时钟、重复暴露不变、零/未知分开。首锚点2020-01-23，c=0.6295030564604313，两期/四路径同值；独立差<10⁻¹²。|
|6base→18压力|PASS。先六条信号与Decimal账簿核验，精确绑定公开及私有表哈希后才18条；无收益条件、无账户重放。|
|全部账簿/统计|PASS。14,544账户日、4,453成交、4,841原始意图、720目标；独立最大NAV差9.03×10⁻¹¹元。12个预定区间、60账户年、1,000产品分组、480个月份配对与18个首次执行差异核对。|
|投资判断|INCONCLUSIVE，ROBUSTNESS_SIGN_CHECK_PASSED；三臂验证绝对平均效用均负。固定费用未知null，经济确认BLOCKED_HURDLE。|
|未运行|按边界未跑M7/M8旧矩阵、股票/新市场采集、最终留出、额外参数/资本、新闻/ML、paper/live或采购。不是24格中的缺失路径。|

审查区分工程通过与投资支持。10%是预测预算，不保证实现波动或回撤；实际rolling60超过10%的比例和所有年度负结果均保留。VR辅助改善不能替换失败的主端点。独立agent签核不冒充人类验收。

## 版本、结果与复现

- 公开基准：`540fdf3a1946dfb12fe54698a22584446cbcf91a`。
- 登记提交：`a696c13dc2f6bf7aba4820fc1ee16ed55dd19ad5`，先于任何新账户。
- 全部24条执行提交：`a2fbb04e76c6e80c262eb86ab621e2dc49f29635`；共同源码hash `dc4e7a79f6f5373d5af15d71def409d54e7209d3ae927c818c72d31d5a96e6a3`。后续交付只增加结果/审查/交接文件，不更改绑定源码、规则和数据。
- 运行期间产生未提交的审查/账户文件，因此provenance中的git_dirty如实保留；157个执行源文件均与该公开提交逐字节相同，不能把dirty标记误解为策略源码漂移或省略检查。
- 数据hash：开发`ca047a986bd5312a35bb787eaa9d7a14a645a153342e8b9bfd1426c80d365f4b`；验证`3bc3addb293330bc0354cce2a1799c38099de399c18f6779d8db689ca1fa1e8c`。
- 原形成hash `d70a12d508e6abfda0ca45f23c348c48d650b2fc6ffea690d32bd682c66dc42a`；M9绑定hash `c0a85d0f6b06325b9e4a5eff30b443b2ff5a667cb7d0528a29b8a06c1af50b44`；初始化内容hash `7c7b0f5e9e7aaabb9bba8da895c313854503d87f69673292e409ccca79148417`。

[实验登记](../m9_risk/EXPERIMENT_REGISTRY.json)、[数据/事件/形成绑定](../m9_risk/DATA_BINDING.json)、[固定初始化](../m9_risk/INITIAL_RISK_ANCHOR.json)、[实际路径](../m9_risk/ACCOUNT_PATHS.json)、[评分及净收益](../m9_risk/UTILITY_EVALUATION.json)、[独立审查](INDEPENDENT_REVIEW.md)、[独立验证](VERIFICATION.md)。逐路径公开目录有NAV、配置、指标、风险/目标和源hash；完整订单/成交/持仓及失败保护文件在安全检出本机`runs/m9_real`，不进入公共Git。原件仍在原F:/QuantTrade/Quant-Research，未复制或改写进公开祖先链。

实际已执行命令（工作根目录F:/QuantTrade/Quant-Research-M9，Python使用原项目锁定环境）：

```text
python scripts/m9_bind.py --evidence-root F:/QuantTrade/Quant-Research
python scripts/m9_prepare.py --dataset-root F:/QuantTrade/Quant-Research/data/m8_rotation/admitted_v1 --evidence-root F:/QuantTrade/Quant-Research
python -m pytest -q -rs tests review_code
python scripts/m9_run.py --dataset-root F:/QuantTrade/Quant-Research/data/m8_rotation/admitted_v1 --evidence-root F:/QuantTrade/Quant-Research --phase base
# 非作者BASE_INDEPENDENT_REVIEW.json绑定六条的公开/完整私有表
python scripts/m9_run.py --dataset-root F:/QuantTrade/Quant-Research/data/m8_rotation/admitted_v1 --evidence-root F:/QuantTrade/Quant-Research --phase stress --base-receipt reports/m9_review/BASE_INDEPENDENT_REVIEW.json
python scripts/m9_evaluate.py
E:/Anaconda/python.exe scripts/m9_plot.py
```

独立复算命令另见VERIFICATION。现有绑定/初始化/账户目录不可覆盖，已执行的prepare重试会明确拒绝；需要获准原件和独立空输出目录才能复现新副本，压力必须获得该副本的独立六条账簿回执，不能复用不匹配的旧哈希。公开缺原件环境只能验证可公开源码/边界和派生结果，不能假称完整来源回放。

## 测试、实际失败与预算

本机执行前完整套件 **895 passed / 10 skipped / 1既有FutureWarning**。两项旧M6测试通过已有外部绝对路径找到原件，故本机不是完全无原件环境。真实公开实现CI [43812326361](https://github.com/FeiyangHong/Quant-Research/actions/runs/43812326361)为 **893 passed / 12 skipped / 1 warning，62.24秒**；作业133116525543测试合并检查`7faaadf6f862708c30967b9a8f6d4ba5009a7fd7`，源分支a2fbb04。12个跳过是旧M5/M6原件依赖，不计PASS。最后结果提交后的真实远端状态另见发布收据和PR检查，不把源实现CI冒充尚未观察的最终HEAD。

没有账户失败。工程过程中保留的已解决问题：公开补丁应用的行尾上下文差异；误用系统pandas1.5.3导致合法时间戳解析失败（未写绑定，切回锁定环境）；可选事件文字哈希未知保留null；root重复prepare被不可变保护拒绝、未覆盖原初始化。M8公开包14个文件的检出CRLF变化仅从已有Git原对象恢复，并固定`-text`；50个清单载荷与52个现有公开包文件均核对原字节，没有改旧结果。

本轮市场请求预算/实际均为0；原M4—M8来源账本不重置。并行会话按共同起点2026-11-16T05:19:00Z到最终收据、四槽位全时段计入的保守上界，含等待及完成后的空闲，不称人类工时；必须低于8小时。最终数值、代码/配置/源/规则/结果哈希、实际公开分支/远端SHA见`DELIVERY_RECEIPT.json`。

已验证事实是限定数据身份、时钟、数学一致性、账户会计和描述统计。动态政策可持续优于固定政策、优于现金、实际开盘可成交、个人风险偏好适用和独立Alpha仍未被证明。固定研究矩阵到此停止，无后续自动搜索或合并main。
