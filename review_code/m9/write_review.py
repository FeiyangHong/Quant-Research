"""Render human-readable independent conclusions from completed receipts only."""
import csv
from pathlib import Path
from independent_accounts import ROOT,read,sha


def main():
    directory=ROOT/'reports/m9_review'
    account=read(directory/'ALL_ACCOUNT_INDEPENDENT_REVIEW.json')
    stats=read(directory/'INDEPENDENT_STATISTICS.json')
    assert account['decision']=='PASS_DATA_AND_ACCOUNTING' and len(account['accounts'])==24
    assert stats['decision']=='PASS_INDEPENDENT_STATISTICS'
    evaluation=read(ROOT/'reports/m9_risk/UTILITY_EVALUATION.json')
    records=read(ROOT/'reports/m9_risk/ACCOUNT_PATHS.json')
    primary=next(r for r in evaluation['pairs'] if (r['period'],r['path'])==('validation','base'))
    development=next(r for r in evaluation['pairs'] if (r['period'],r['path'])==('development','base'))
    p_ci=primary['utility_intervals'][0]['utility_ci']
    d_ci=development['utility_intervals'][0]['utility_ci']
    n_ci=primary['net_return_intervals'][0]['ci95']
    total=lambda field:sum(r[field] for r in account['accounts'])
    maximum=max(float(r['maximum_nav_difference_cny']) for r in account['accounts'])
    with (ROOT/'reports/m9_risk/account_metrics.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    lines=[]
    for variant in ('VE','CE','VR'):
        row=next(r for r in rows if (r['period'],r['path'],r['variant'])==('validation','base',variant))
        lines.append(f"| {variant} | {float(row['total_return']):+.2%} | {float(row['annual_volatility']):.2%} | {float(row['max_drawdown']):.2%} | {float(row['mean_cash_weight']):.2%} | {float(row['mean_utility']):+.8f} | {float(row['rolling60_above_10pct_fraction']):.2%} |")
    text=f'''# M9 独立复核

独立审查结论：**24 条预登记账户的目标、风险及必要会计通过；独立统计结论为 {stats['primary_statistical_state']}。** 工程验收不等于投资成功或实盘许可。

验证 base 的 VE−CE 平均效用评分差为 {float(primary['mean_utility_difference']):+.10f}/日，60 日块 95% 区间 [{float(p_ci[0]):+.10f}, {float(p_ci[1]):+.10f}]。开发分别为 {float(development['mean_utility_difference']):+.10f}/日，区间 [{float(d_ci[0]):+.10f}, {float(d_ci[1]):+.10f}]。固定稳健性标记：{evaluation['robustness_sign_check']}。

验证 base 的净日收益差另为 {float(primary['mean_net_return_difference'])*10000:+.6f} bp/日，60 日块区间 [{float(n_ci[0])*10000:+.6f}, {float(n_ci[1])*10000:+.6f}] bp/日。效用评分与净收益使用不同字段；评分没有乘本金换算成费用空间。

| 验证 base | 累计净收益 | 年化波动 | 最大回撤 | 平均现金 | 平均效用评分/日 | rolling60 波动 >10% |
|---|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(lines)+f'''

零收益现金的效用评分为 0。正的 VE−CE 差值只表示相对这个固定缩放政策更好；不能由此推导正绝对效用、正复利、优于现金或独立 Alpha。固定 c 对照并非全期精确风险匹配，VE−CE 包含平均暴露和动态调整两方面差异。10% 是预测预算，实际账户波动并不保证小于 10%。

## 已直接核验

- 事前登记在公开提交 `a696c13dc2f6bf7aba4820fc1ee16ed55dd19ad5` 内，24 格、60/45 窗口、gamma=5、两个时期、主端点和停止规则均在新增账户前核对。未按结果改登记。
- 复核了 558 个复用 M8 原件指针的 SHA256。该项确认字节身份，不重新认证供应商的历史事实或真实发布时间。
- 新写 Decimal 风险计算，不调用生产风险函数作预期。首个非空合法锚点 2020-01-23，2020-02-03 21:00 释放，base 2020-02-04 执行。60 个同步收益日，独立 sigma=0.1588554638039089476，c={account['independent_fixed_c']}。2019 年末空目标没有初始化。
- 内存中替换全部锚点之后 TR，初始化 c 和风险输入哈希不变。合成反例验证相同回报拆分不降低风险，45 日通过、44 日阻断，起止端点可得时钟，以及合法零 sigma 与缺失/NaN/无穷的区别。50% 对角收缩的 0.75 倍方差反例只作数学说明，没有增加候选估计器。
- 核对全部 {sum(r['decisions'] for r in account['signals'])} 个账户月目标及风险计算，每条非空信号均有 60 个同步日。所有时期、成本和延迟路径共享同一 c，VR 使用自己的未缩放篮子。
- 六条 base 先通过独立账簿审查，收据绑定公开和私有全部表哈希后才允许其余 18 条。最终从 100000 元现金、零库存重建 {total('sessions')} 个账户日，审查 {total('fill_checks')} 笔成交、{total('original_intent_checks')} 个原始再平衡意图、{total('capacity_checks')} 次累计容量检查；最大 NAV 差 {maximum:.12g} 元。
- 分红应收/支付和拆分来自已准入原件规则；独立维护现金、份额与锁定批次，核对整手、T+1、价格、手续费/滑点、原始再平衡意图及三重共享绝对容量。实际 NAV 不参与构造预期 NAV 或订单数量。
- 从独立账簿重算 24 账户主要指标、尾部样本数及均值、rolling60 风险分布、现金和费用；复核 {stats['annual_account_checks']} 账户年、{stats['annual_and_paired_product_buckets']} 个年度/配对产品分组、{stats['paired_month_checks']} 个配对月份。保留 2024 年 1 月等全部月份。
- 对开发/验证 base 的效用差及净收益差分别独立重算 60/20/120 日 circular block bootstrap-t/HAC，共 12 个区间，每项 5000 次、seed=20261114。压力只核点估计；VR−VE 只作描述。退化合成输入不制造有效区间。

## 范围和边界

本次使用实际恢复的 M8 执行核与新增 M9 薄风险层，无旧账户重跑、无新市场请求、无 2025 以后市场序列。独立账簿把经逐笔规则审查的实际成交作为输入，并未另写第二套完整撮合器。实际来源与逐笔全账在本地；公开代码、派生 NAV/风险/统计和哈希可独立检查，公开检出无法凭这些文件重建受限原件。

成交价格是既有日线模型，真实日量仅给容量上界，保持 DAILY_SCREEN_ONLY。未核验用户券商成交或个人费率。未知年度增量固定费仍为 null，经济确认 BLOCKED_HURDLE。验证期已反复观察，全部结果只支持本组探索性描述；不解锁最终留出、更多参数、股票机制、paper/live 或部署。

独立计算代码位于 `review_code/m9/`。M8 Decimal 账簿和独立 bootstrap/HAC 核复用并作路径适配；风险计算、M9 目标审查及效用/单位审查为本轮独立新增。
'''
    (directory/'INDEPENDENT_REVIEW.md').write_text(text,encoding='utf-8')
    receipts=['PREREGISTRATION_REVIEW.json','INITIALIZER_REVIEW.json','RISK_PROBES.json','UTILITY_PROBES.json',
              'BASE_INDEPENDENT_REVIEW.json','ALL_ACCOUNT_INDEPENDENT_REVIEW.json','INDEPENDENT_STATISTICS.json']
    hash_lines='\n'.join(f'| `{name}` | `{sha(directory/name)}` |' for name in receipts)
    verification=f'''# M9 独立验证记录

所有最终实证验证使用既有冻结环境 `F:/QuantTrade/Quant-Research/.venv/Scripts/python.exe`，工作目录 `F:/QuantTrade/Quant-Research-M9`。

| 检查 | 结果 |
|---|---|
| 事前登记 | PASS，提交 a696c13dc2f6bf7aba4820fc1ee16ed55dd19ad5，检查时 ACCOUNT_PATHS 尚不存在 |
| 复用原件字节身份 | 558/558 |
| 固定初始化及未来 TR 扰动 | PASS |
| 独立风险/效用合成反例 | PASS，9+6 类检查 |
| base 先行账簿 | 6/6，公开/私有表精确哈希门控 |
| 最终目标/风险/账簿 | 24/24；{total('sessions')} 账户日；{total('fill_checks')} 成交 |
| 最大 NAV 差 | {maximum:.12g} 元 |
| 独立配对区间 | 12/12；两时期 × 两指标 × 60/20/120 块；各5000次 |
| 年度账户/产品分组/月份 | {stats['annual_account_checks']} / {stats['annual_and_paired_product_buckets']} / {stats['paired_month_checks']} |

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
{hash_lines}

账户执行源内容哈希：`{records[0]['code_hash']}`。所有 24 条账户必须具有该同一内容哈希；私有完整表和公开表在独立收据中逐项绑定。
'''
    assert len({r['code_hash'] for r in records})==1
    (directory/'VERIFICATION.md').write_text(verification,encoding='utf-8')
    print('INDEPENDENT_REVIEW.md VERIFICATION.md written')


if __name__=='__main__':main()
