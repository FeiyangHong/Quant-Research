# 未入选退市ETF生命周期补充核证

这是冻结数据以外的旁证补充，不是新准入、不计算收益、不回写现有净值。六只历史标的均保留在候选与原始数据中；核对冻结阶段的完整季度代表名单，六只均从未胜出。新增材料没有改动冻结清单、源代码、配置、既有公告或实验输出。

六只中五只为清算，**159927 为基金转型（TRANSFORMATION），不是清算**。退出交易所交易不等于权利归零；清算请求权或后续基金份额应保留。下列日期及金额来自对应原始公告，完整URL、公告日、保守可用时点、实际采集时间、原件SHA256见同目录机器文件 `retired_lifecycle_supplement.json`。

| 代码 | 类型 | 清算期间 | 退市日 | 清盘分配登记日 | 公告计划发放日 | 公告每份金额/总额（元） |
|---|---|---|---|---|---|---|
| sh.510520 | LIQUIDATION | 2019-07-08—2019-07-18 | 2019-10-31 | 2019-10-08 | 2019-10-14 | 1.22036 / 未单列 |
| sh.515930 | LIQUIDATION | 2023-06-13—2023-06-21 | 2023-07-31 | 2023-07-11 | 2023-07-17 | 4.90207 / 19974357.68 |
| sz.159846 | LIQUIDATION | 2021-12-28—2022-01-07 | 2022-01-05 | 2022-01-24 | 2022-01-25 | 未列每份 / 20048681.66 |
| sz.159927 | TRANSFORMATION | 不适用 | 2018-02-14 | 不适用 | 不适用 | 不适用：转基金份额 |
| sz.159955 | LIQUIDATION | 2022-11-23—2022-12-13 | 2022-11-30 | 2022-12-26 | 2022-12-27 | 未列每份 / 12777757.75 |
| sz.159999 | LIQUIDATION | 2023-03-14—2023-03-22 | 2023-03-20 | 2023-04-14 | 2023-04-17 | 未列每份 / 43044924.81 |

表中计划发放不是投资者实际到账、可交易现金或可取现金；六只的个人实际账户到账/可取日期均为空。对五只清算基金，也未取得完成注销/退出登记的独立回执，因此完成日为空；公告表示将办理退出登记，不能把该将来安排写成已完成。

公告日期按交易所检索记录及文件正文核对，不用附件URL目录日期替代。保守时点为公告日期后的首个交易日21:00；这属于历史公开资料重建，不是当时实际采集时间。所有本次原件实际采集于2026年11月15日前后，时间完整保存在capture。清算报告的编制日/净资产截止日不能当作公开日，报告净资产不能当作最终分配金额。

**sh.510520 诺安中证500ETF**：发行人10月25日公告回顾10月14日发放；这仍不构成个人券商现金到账证据。清算报告净资产与随后每份分配额分开保留，不用前者推算个人款项。
- [诺安基金管理有限公司关于诺安中证500交易型开放式指数证券投资基金清算报告](https://www.sse.com.cn/disclosure/fund/announcement/c/2019-09-23/510520_20190923_1.pdf)，公告 2019-09-23；原件 SHA256 `5afba587c7aa30c2653e55943f347502c2a006894419e66d207b30043a765519`。
- [关于诺安中证500交易型开放式指数证券投资基金清算资金发放公告](https://www.sse.com.cn/disclosure/fund/announcement/c/2019-09-30/510520_20190930_1.pdf)，公告 2019-09-30；原件 SHA256 `975fff8f5544437913ce7bc01221bf1a48f3777f62bb77a8f42605b7b7788f0a`。
- [诺安中证500交易型开放式指数证券投资基金终止上市的公告](https://www.sse.com.cn/disclosure/fund/announcement/c/2019-10-25/510520_20191025_1.pdf)，公告 2019-10-25；原件 SHA256 `ea46255fe36ccc5f393542c57dfe7ff08227b35fb27661232b1981555d773646`。

**sh.515930 永赢沪深300ETF**：分配公告和后来的退市公告均提示具体到账以销售机构为准。报告截止日净资产与最终拟分配总额不同，不能混用。
- [永赢沪深300交易型开放式指数证券投资基金清算报告](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-07-06/515930_20230706_F09K.pdf)，公告 2023-07-06；原件 SHA256 `62697118e5afb6c4bae096ff7fb371701811058d0562935c6c0164d39e062360`。
- [永赢沪深300交易型开放式指数证券投资基金剩余财产分配的公告](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-07-07/515930_20230707_2YT5.pdf)，公告 2023-07-07；原件 SHA256 `88ac2ee1111c69a871f6ba1df99422667604a9aec36687fa0dcc94deac5aca61`。
- [永赢基金管理有限公司关于永赢沪深300交易型开放式指数证券投资基金终止上市交易的公告](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-07-26/515930_20230726_CC6Z.pdf)，公告 2023-07-26；原件 SHA256 `7ca5effd41c3486a39084814ece730709cb1b9232d51f5f4830f4fac271064df`。

**sz.159846 建信中证1000ETF**：退市早于最终清算报告和分配，退市权益登记日与清盘分配登记日不同。公告未列每份支付数值/个人舍入规则；不以总额除份额伪造可执行金额。
退市权利登记日为 2022-01-04，与表中清盘分配登记日独立保存。
- [中证1000ETF基金：建信中证1000交易型开放式指数证券投资基金清算报告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-01-18/b5d4d982-4f08-41f6-960b-e2e235dab083.PDF)，公告 2022-01-18；原件 SHA256 `94e93c06286fc32a402aa3fc076fe0b5b52d815f27370b3ee9f75ebb4be659df`。
- [中证1000ETF基金：建信中证1000交易型开放式指数证券投资基金剩余财产分配的公告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-01-20/817f60ca-9b7d-4e5b-99ee-841bbd7201f1.PDF)，公告 2022-01-20；原件 SHA256 `22dd0e55eb25262ef65b5fa7c7964219ea11020c587b59b7322cfa1216929e9b`。
- [中证1000ETF基金：关于建信中证1000交易型开放式指数证券投资基金终止上市交易的公告](https://disc.static.szse.cn/download/disc/disk02/finalpage/2021-12-30/3374aad1-94ec-430a-ad80-1fdb5df6c87e.PDF)，公告 2021-12-30；原件 SHA256 `9916774aed68661bd1c662c199f67f30735dd5f9e846f4516377cb1a97f55393`。

**sz.159927 鹏华沪深300ETF**：非清算、非自动现金支付。原ETF份额转为场外混合基金份额并转登记系统；完成确权后方可申请赎回。2018年半年报仅用于事后核对转换日期，不倒灌为2月已知精确转换参数。
退市权利登记日为 2018-02-13，与表中清盘分配登记日独立保存。
- [A300ETF：终止上市公告](https://disc.static.szse.cn/download/disc/disk01/finalpage/2018-02-09/a24ddf8d-be25-4db0-8d7e-16927f00950c.PDF)，公告 2018-02-09；原件 SHA256 `c493017ae43b8f2c449c045ba42f877c65ee23f103a4861b58a89ec4eb7fcabf`。
- [A300ETF：基金份额“确权”登记指引](https://disc.static.szse.cn/download/disc/disk01/finalpage/2018-02-06/755aa7ba-100c-4b12-89c2-b6f158703d13.PDF)，公告 2018-02-06；原件 SHA256 `6d31e2f86ecb2ebc72da5ee6c892b353861e3fbafee6e5656ca0842ac00cc53f`。
- [鹏华量化先锋混合2018年半年度报告摘要](https://static.cninfo.com.cn/finalpage/2018-08-27/1205335937.PDF)，公告 2018-08-27；原件 SHA256 `ed73ccf3252a0a15be84af85afb06188529fc08c831081a4a7eebc34be73d2f3`。

**sz.159955 嘉实创业板ETF**：分配公告日期与计划发放日同为12月27日；页面附件路径12月26日不证明提前公告。保守公告可用时点12月28日21:00晚于记录/支付，未来若持有须保持未知权利并按实际知识更新，不能回填现金或金额。
退市权利登记日为 2022-11-29，与表中清盘分配登记日独立保存。
- [创业板ETF嘉实：嘉实创业板交易型开放式指数证券投资基金清算报告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-12-23/3c232afa-24d7-4012-a67e-ae7e7d911159.PDF)，公告 2022-12-26；原件 SHA256 `3d80434517dc9082fe2effa69123c5f605bbde1b7dcaeddde091f9217c7f623d`。
- [创业板ETF嘉实：嘉实创业板交易型开放式指数证券投资基金剩余财产分配公告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-12-26/3b87fe45-08a3-4875-bf85-35e86ae32a8d.PDF)，公告 2022-12-27；原件 SHA256 `2f155f1a110236dd9e109dd5297f314c7382351862319354c58c2ddc57df8ccd`。
- [创业板ETF嘉实：关于嘉实创业板交易型开放式指数证券投资基金终止上市交易的公告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-11-24/bc616225-1cde-4fb0-959b-a5088d80e1ff.PDF)，公告 2022-11-25；原件 SHA256 `5433a15288d77ffef40726624d3da255a0c06e3f7d86a78f74582e5fc2decf0a`。

**sz.159999 永赢中证500ETF**：退市不等于灭失后续清算请求权。计划发放晚于退市近一个月；公告未给个人每份精确支付/舍入规则，实际账户可用仍未知。
退市权利登记日为 2023-03-17，与表中清盘分配登记日独立保存。
- [永赢中证500ETF：永赢中证500交易型开放式指数证券投资基金清算报告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2023-04-07/342ebe6f-d579-4f62-825d-2def1ee0fbf5.PDF)，公告 2023-04-10；原件 SHA256 `0e5f79dc71c7bda036e6bb2a1a49c98320d81fcce94ca122e612fbd086702f3f`。
- [永赢中证500ETF：永赢中证500交易型开放式指数证券投资基金剩余财产分配的公告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2023-04-10/09c2e702-024d-45bd-9a43-5c13204e27ef.PDF)，公告 2023-04-11；原件 SHA256 `44b56f1df457fef45c6516485f6c92b0c54667a3de180dfe888fca3652bf0bd3`。
- [永赢中证500ETF：永赢基金管理有限公司关于永赢中证500交易型开放式指数证券投资基金终止上市交易的公告](https://disc.static.szse.cn/download/disc/disk03/finalpage/2023-03-14/8d52a9d3-fdd0-4dab-9401-a8b050867e76.PDF)，公告 2023-03-15；原件 SHA256 `0aeac1a487278a529fb488c8f12988ab7c39bc99f637d4ec6fd1aaf30674d6df`。

**当前执行模型边界**：场外基金转型、个体确权和随后赎回不在现有执行模型内。未来若159927或类似标的成为持仓/特征依赖，须先实现份额承继、转换比率与舍入、可赎回时间及估值并补原始证据，不允许自动当作普通清算，不允许删样本规避。159927的2018年半年报第2–3、20页事后证实2月22日日终转换、2月23日新合同生效；本补充未取得原最终转换结果公告的精确比率与个体舍入证据，不能据总份额倒算后回填。

只读核查冻结 `src/quant_research/execution.py` 的未知事件分支，并以已有fixture在 `work/probe_retired_transformation.py` 中注入 `TRANSFORMATION`，结果为 `ExecutionBlockedError: Unsupported corporate action`。证据保存于 `work/retired_transformation_block_probe.json`，冻结源码未改。现有 `tests/test_execution.py::test_unsupported_fractional_split_and_delisting_recovery_block` 覆盖其他未支持经济情景；它不是转型专用测试，因此本补充单独记录探针，不声称已有转型完整实现。

若未来真持有五只清算基金：须在未知回收金额期间保留未定价权利，分别核对权利登记、金额认识时点、支付和注销。尤其159955最终分配公告按规则到2022-12-28 21:00才可用，晚于12月26日登记与12月27日计划支付，不能反向确认此前精确金额或实际现金。159846/159955/159999尚缺公告明确的个人支付舍入规则；本报告保留最终拟分配总额，不自行除以份额当作已验证每份款项。

原始抓取共45份六基金生命周期PDF，另1份159927后续基金半年报；分页查询完整性、检索窗口和每份raw/text哈希在新的 `data/raw_retired_audit/six_funds_v1/` 中保留。前两次不完整采集尝试也保留；最终成功清单是 `collection_manifest_v3.json`。本次只补公开资料，没有联系机构或访问个人账户；公开可下载不代表允许重分发，原件继续仅存本地，不上传。

重放核验（PowerShell，仓库根目录；不会生成或修改策略结果）：

```powershell
.venv/Scripts/python.exe -c "import runpy; runpy.run_path('work/probe_retired_transformation.py', run_name='__main__')"
.venv/Scripts/python.exe -c "import runpy; runpy.run_path('work/build_retired_lifecycle_supplement.py', run_name='__main__')"
```
