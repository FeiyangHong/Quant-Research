# M9 独立验证记录

所有最终实证验证使用既有冻结环境 `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe`，工作目录 `F:/QuantTrade/Quant-Research-M9`。

| 检查 | 结果 |
|---|---|
| 事前登记 | PASS，提交 a696c13dc2f6bf7aba4820fc1ee16ed55dd19ad5，检查时 ACCOUNT_PATHS 尚不存在 |
| 复用原件字节身份 | 558/558 |
| 固定初始化及未来 TR 扰动 | PASS |
| 独立风险/效用合成反例 | PASS，9+6 类检查 |
| base 先行账簿 | 6/6，公开/私有表精确哈希门控 |
| 最终目标/风险/账簿 | 24/24；14544 账户日；4453 成交 |
| 最大 NAV 差 | 9.0222e-11 元 |
| 独立配对区间 | 12/12；两时期 × 两指标 × 60/20/120 块；各5000次 |
| 年度账户/产品分组/月份 | 60 / 1000 / 480 |

执行命令（以以上 Python 环境运行）：

```text
review_code/m9/registration_review.py
review_code/m9/probe_risk.py
review_code/m9/probe_statistics.py
review_code/m9/review_initializer.py --private-root F:/QuantTrade/Quant-Research
review_code/m9/review_accounts.py --private-root F:/QuantTrade/Quant-Research --phase base
review_code/m9/review_accounts.py --private-root F:/QuantTrade/Quant-Research --phase all
review_code/m9/review_statistics.py
review_code/m9/write_review.py
```

`registration_review.py` 专门要求账户未创建且当时 HEAD 已包含登记，故完成后不能以新 HEAD 重跑来伪造事前时点。base 收据不覆盖重写；最终全账户收据单独生成。全部独立预期账簿位于被排除的 `work/m9_independent/ledgers/`，公开仅保留各自哈希及核验计数。

最初一次历史初始化诊断误用了系统 Python（pandas 1.5.3），因不支持当前时间解析格式报错；没有运行账户、没有修改数据。切换已锁定项目环境后通过。系统环境上的两项合成 probe 亦在锁定环境重跑通过。

独立脚本修改仅限 `review_code/m9/` 和审查输出，未编辑生产代码、参数、登记或历史原件。源依赖缺失时不能将此复核误称公共全原件回放。公开 CI 的最终状态由交付收据另列，本文件不以本地测试替代 CI。

| 收据 | SHA256 |
|---|---|
| `PREREGISTRATION_REVIEW.json` | `57366d9a1045b52b3740cd60317325a40903f3efd72a5aa96fd1f2a477b3dbf5` |
| `INITIALIZER_REVIEW.json` | `73bafad5370b905539028f0ee09414ce512ed90497be2d249c28e8fba6c625aa` |
| `RISK_PROBES.json` | `0d465bdb2d8f97363df904482c7e759f72e5e3d836f738cdb012edc8c122396b` |
| `UTILITY_PROBES.json` | `7c1b2c481726dc5dea4183d825f561a2358ff3689c630847d82eae0acf0a39ff` |
| `BASE_INDEPENDENT_REVIEW.json` | `186842f97314b55ec3b36d0c2b186c370589cd63759adba85bdc0f8c924ff5fd` |
| `ALL_ACCOUNT_INDEPENDENT_REVIEW.json` | `a6ef36b5ab9fa22cd72e5888e1d40f44e99689a49b1e391130a604ac9329704d` |
| `INDEPENDENT_STATISTICS.json` | `3123d1148ebc20a58a5077ed41667c068293db6a8e1c8de707d678aed10dc957` |

账户执行源内容哈希：`dc4e7a79f6f5373d5af15d71def409d54e7209d3ae927c818c72d31d5a96e6a3`。所有 24 条账户必须具有该同一内容哈希；私有完整表和公开表在独立收据中逐项绑定。
