# 本轮验证与复现

2026-11-15。当前原始代码基线为`a57ad77cd1f49ffab5d06166628faaac723b6053`；本次新增代码与报告由随后开发分支提交保存，独立审查绑定实际文件SHA256，不把工作区修改冒称已存在于旧基线。运行环境Python 3.9.19、NumPy 1.26.4、pandas 2.2.3、SciPy 1.13.1；其余依赖由仓库requirements.lock固定。

## 已实际执行

| 检查 | 结果 | 范围 |
|---|---|---|
| 仓库完整pytest | **424 passed，29.62秒** | 新增股票准备与拒绝路径、原ETF执行/数据/报告等全部回归；合成工程测试不等于真实Alpha样本 |
| 独立股票执行反例 | **28 passed，1.07秒** | 主代理最终复跑；独立审查者另行复跑28项通过，其审查记录保留修前3项失败 |
| 研究核独立探针 | **21组全部PASS** | 独立审查者构造；对应21项仓库目标测试已经包含在424内，不重复相加 |
| 原始数据完整性 | **178对象哈希/字节数一致** | 股票SDK35、日历2、HTTP51请求及失败记录；语义/全池覆盖不由哈希自动通过 |
| R1原结果只读复算 | **REVIEW_COMPLETE / PASS** | 24项bootstrap诊断复现，22正常、2退化保留；56排名压力配对均值误差0，未运行新策略 |

作者相关174与独立审查158等定向回归存在重叠，见各自报告，不能与424或28简单相加成新增独立证据数量。本轮真实个股绩效实验注册0、运行0；指标为null。旧ETF冻结版329项是旧版本验证记录，不冒称当前GitHub CI结果。本文件记录本地实际结果；发布后GitHub Actions状态以对应提交的实际工作流为准。

在仓库根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest review_code/equity/test_independent_execution_admission.py -q
```

以上不需要供应商Token、网络数据或真实账户。独立特征探针源码完整保存在feature_review.json；先恢复再运行，无需重建假想市场数据：

```powershell
.venv\Scripts\python.exe -c "import json,pathlib; j=json.loads(pathlib.Path('reports/m3_equity_admission/feature_review.json').read_text(encoding='utf-8')); p=pathlib.Path(j['independent_probe_restore_path']); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(j['independent_probe_source_utf8'].encode('utf-8'))"
.venv\Scripts\python.exe work/equity_feature_review/independent_probes.py
```

真实原件和R1完整账簿按既有规则留在本地，不把供应商原始数据自动发布到Git。迁移复现需连同data/raw_equity_admission及旧R1运行档案保存；仅克隆仓库可以跑工程测试，不能假称已重建全部实采证据。拥有原始档案时运行：

```powershell
.venv\Scripts\python.exe review_code/equity/verify_admission_evidence.py
.venv\Scripts\python.exe reports/m3_equity_admission/review_code/r1_milestone_review.py
```

第二条只读旧2016—2024账户，输出本目录R1审查，不重跑策略；根状态和决策日志变化后，审查输入文档哈希会随之变化，原结果数字不得变化。冻结448结果摘要SHA256必须为`c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb`。本轮没有修改reports/real_data_phase3、旧runs或其参数。

首次采集支持的入口为scripts/audit_equity_sources.py，固定BaoStock 0.9.4、显式范围截止2024及排他会话锁；指定新output，不能覆写已有原件。完整补充采集及报告源代码快照见[reproduction/README.md](reproduction/README.md)。网络重新查询可能返回修订后的字节，属于新数据版本，不保证重取与原快照逐字节相同；复现原审计应优先使用已归档原件。

本轮不提供`run R2/R3`命令：正式runner尚未准入个股数据、税务/公司行为与完整对照。直接调用研究核、改成R1B标签、将真实数据标synthetic、删除困难样本都不能产生已验收实验。准备协议及配置保存设计，不消耗或替代后续真实注册。

版本、实验处置、当前源码/报告指纹及测试输出保存在[experiment_disposition.json](experiment_disposition.json)和[verification.json](verification.json)。字节敏感文件由.gitattributes保留原始换行，独立报告各自记录输入哈希。最终留出仍LOCKED，采购NONE，live_enabled=false。
