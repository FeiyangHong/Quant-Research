"""Publish the independent review from already completed, hash-bound checks.

This is report assembly, not a strategy run, new statistical test or selection.
Run from the repository root after restoring the archived work/ code paths.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'reports/real_data_phase3'
CODE = P / 'review_code'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def copy_exact(source, target):
    payload = source.read_bytes()
    if target.exists():
        assert target.read_bytes() == payload, str(target)
    else:
        target.write_bytes(payload)
    assert sha(source) == sha(target)


def main():
    now = datetime.now(timezone.utc).isoformat()
    expected_main = 'c238b235722bc73468ef1cc3af29f083c160a92d0ff18edead6c36d3b129aebb'
    assert sha(P / 'results_summary.json') == expected_main
    main_results = read(P / 'results_summary.json')
    inventory = read(P / 'independent_inventory_matrix_review_v2.json')
    bootstrap = read(P / 'independent_bootstrap_reference.json')
    years = read(P / 'independent_year_attribution.json')
    diagnostics = read(ROOT / 'work/independent_statistical_diagnostics_v2.json')
    assert main_results['run_count'] == 448
    assert inventory['status'] == 'ALL_448_PASS'
    assert bootstrap['status'] == 'ALL_24_MATCH'
    for item, field in ((inventory, 'summary_sha256'), (bootstrap, 'summary_sha256'),
                        (diagnostics, 'main_results_sha256'), (years, 'main_results_sha256')):
        assert item[field] == expected_main
    assert main_results['economic_confirmation'] == 'BLOCKED_HURDLE'
    assert main_results['final_holdout_accessed'] is False

    # Verify the separate postprocessing snapshot and its exact declared inventory.
    ep = read(P / 'evaluation_provenance.json')
    assert ep == main_results['evaluation_provenance']
    source_files = ep['source_files']
    canonical = json.dumps(source_files, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    assert hashlib.sha256(canonical).hexdigest() == ep['source_hash']
    snapshot = P / 'evaluation_source_snapshot'
    actual_files = {f.relative_to(snapshot).as_posix(): sha(f) for f in snapshot.rglob('*') if f.is_file()}
    assert actual_files == source_files
    first_run = main_results['runs'][0]
    run_path = Path(main_results['provenance']['matrix_roots'][first_run['period']]) / first_run['directory']
    rp = read(run_path / 'provenance.json')
    for name in ('src/quant_research/evaluation.py', 'src/quant_research/provenance.py'):
        assert ep['source_files'][name] == rp['source_files'][name]

    copied = []
    for name in ('independent_statistical_diagnostics_v2.json',
                 'independent_invalidated_v1_history_review_v2.json',
                 'independent_retired_scope_review.json',
                 'evaluation_source_review_v2.json'):
        source, target = ROOT / 'work' / name, P / name
        copy_exact(source, target)
        copied.append(target.relative_to(ROOT).as_posix())

    new_code = []
    for name in ('independent_year_attribution.py', 'publish_independent_statistical_review.py'):
        source, target = ROOT / 'work' / name, CODE / name
        copy_exact(source, target)
        new_code.append({'original_path': source.relative_to(ROOT).as_posix(),
                         'archived_path': target.relative_to(ROOT).as_posix(), 'sha256': sha(source)})
    code_manifest = {
        'schema_version': 1, 'reviewer': '/root/independent_admission', 'created_at': now,
        'status': 'FINAL_REPORT_ASSEMBLY_AND_DESCRIPTIVE_YEAR_DIAGNOSTIC',
        'files': new_code,
        'main_results_sha256': expected_main,
        'prior_review_manifest': 'reports/real_data_phase3/review_code/independent_review_code_manifest_v2.json',
        'prior_review_manifest_sha256': sha(CODE / 'independent_review_code_manifest_v2.json'),
        'replay': [
            'Restore original_path files from archived_path after SHA256 verification; do not overwrite differing bytes.',
            'Use repository root and locked .venv Python; retain absolute matrix paths and source/data snapshots.',
            'See README_INDEPENDENT_REVIEW_V2.md for the full inventory and diagnostic replay commands.',
            'Year-attribution original script writes its fixed output with exclusive creation; replay in a separate checkout, or use runpy.run_path to load calculate(), then JSON-serialize calculate() into a new work/replayed_year_attribution.json file.',
            'This publisher assembles reports from the fixed original diagnostics; it does not rerun strategies or inference.',
            'Replay the publisher in a separate checkout or preserve existing reports first; reviewed_at timestamps change hashes.'
        ],
        'year_rules': 'Report candidate best compounded calendar-year net return and maximum paired annual CNY PnL increment simultaneously; also retain previously announced maximum annual mean-daily increment. Remove identical dates from both series, earliest-year ties, no new p-values.',
    }
    write(CODE / 'independent_final_review_code_manifest.json', code_manifest)

    primary = [r for r in main_results['paired_effects'] if r['initial_cash'] == 100000 and r['path'] == 'base']
    assert len(primary) == 8
    primary_years = [r for r in years['year_deletion_rows'] if r['initial_cash'] == 100000 and r['path'] == 'base']
    assert len(primary_years) == 24
    primary_runs = [r for r in main_results['runs'] if r['config']['initial_cash'] == 100000 and r['path'] == 'base']
    assert len(primary_runs) == 16
    base_validation = [r for r in primary_runs if r['period'] == 'validation']
    assert len(base_validation) == 8 and all(r['metrics']['total_return'] < 0 for r in base_validation)
    primary_contrasts = [r for r in diagnostics['four_contrasts'] if r['initial_cash'] == 100000 and r['path'] == 'base']
    primary_decisions = [r for r in diagnostics['decision_diagnostics'] if r['initial_cash'] == 100000 and r['path'] == 'base']
    primary_tails = [r for r in diagnostics['run_tail_and_dependence_diagnostics'] if r['initial_cash'] == 100000 and r['path'] == 'base']

    label_period = {'development': '开发', 'validation': '验证'}
    label_scale = lambda v: '开' if v else '关'
    lines = [
        '# 独立统计审查：真实数据 R1B v2', '',
        '结论：`REVIEW_COMPLETE / DESCRIPTIVE_VALIDATION_ONLY / NO_CONFIRMED_ECONOMIC_INCREMENT`。已完成全部 448 次修正运行的审查，未发现新的技术阻断；数据和工程通过仅限所声明的日频历史模拟范围。验证集存在探索性的正相对增量，尚不足以确认可兑现、扣除增量固定成本后的经济收益。未选择最终候选，未开放 2025–2026 最终留出集或实盘。', '',
        '审查人：`/root/independent_admission`（独立于策略实现与主评估器的统计复核角色）；时间：' + now + '。下列结论由已保存的原始运行表、独立复算代码与机器证据支持。', '',
        '范围为 2016–2021 开发账户和 2022–2024 独立起始验证账户，分别 1,461 和 726 个完整交易日。每段 224 个配置：四种变体、两种风险缩放、四个资本档位及七条基准/压力路径；主资本固定为 10 万元，其余 1 万、50 万、100 万元只作稳健性检查。448 条路径共享历史冲击，不是 448 个独立样本。', '',
        '执行冻结于 `b308ccce541b6e60207808d4d55bc1f4dfd61928`，源摘要 `d8d265eed26337ba8a58e2dff809af3acc71550232ecbddaa2b94a7a3da6ba7a`。报告层单独修复金额复算器并于 `7d6169f0be2138292a1c708ac3e3e44dcd55a620` 评估，摘要 `0187faf98b8c04b3ae689622238751100f8acaf2b11162b39369b3b904e6af04`；统计核心与来源身份核心仍逐字节等于执行快照。已核验报告源快照完整清单及哈希。报告修复未改变有效 v2 运行表、统计定义或判定容差。', '',
        '旧版 353 次注册尝试（352 次完成、1 次中止）全部保留并作废：独立工程检查发现 46 项佣金、6 项成交额、11 项滑点金额舍入问题。复核了 3,872 份旧完成表的哈希，未用旧收益选参数；一次早期结构读取曾意外显示首条旧指标，已记录，之后只投影身份字段并校验字节。先前库存侧 PASS 只涵盖数量/日历/分红模型，不能推翻金额失败。修正后 448 个经济配置和数据快照均与登记一致。', '',
        '**全部主配对均报告。** 下表单位为 bp/交易日；95% 区间是主块长 60 的边际探索性区间，p 是单侧零增量固定成本假设下的诊断，未作多重检验确认。交易成本已在账户中扣除，未知的是额外运营、时间等固定成本。', '',
        '| 样本 | 配对 | 缩放 | 日均净增量 | 95% 区间 | 探索性 p |',
        '|---|---|---|---:|---:|---:|',
    ]
    for r in primary:
        b = next(x for x in r['uncertainty']['exploratory_zero_hurdle']['blocks'] if x['block_length'] == 60)
        lo, hi = b['ci95']
        lines.append(f"| {label_period[r['period']]} | {r['candidate']}−{r['baseline']} | {label_scale(r['risk_scaling'])} | {r['mean_daily_net_increment']*1e4:.6f} | [{lo*1e4:.6f}, {hi*1e4:.6f}] | {b['p_net']:.6f} |")
    lines += [
        '',
        '验证集 R1−E1 缩放开启的相对增量为 +0.831987 bp/日，三种块长区间均为正；主 p=0.003199，20/120 日块 p=0.010598/0.004799，HAC p=0.020994。这是应如实保留的探索性证据，但开发期对应日均增量为 −0.094392 bp。验证集 R0−E0 缩放开启的主区间仍跨零，主 p=0.029994，而 20 日块 p=0.050990、HAC p=0.073175，显示方法敏感性。其他主配对的 60 日块区间均跨零。', '',
        '独立程序从 16 份主 NAV 表重新构造 8 个配对、3 种块长、各 5,000 次抽样，24 个结果全部复现：p 数值完全一致，最大区间误差约 1.14×10⁻¹⁸。开发期两个 R1−E1 的 120 日块各出现一个退化抽样，保留 `INCONCLUSIVE_DEGENERATE_BOOTSTRAP`，未丢弃后重算。数值复现不证明平稳性或经济有效性。重叠 252 日窗口亦只作描述，不能增加独立样本数。', '',
        '**删除最佳年：两种规则同时保留。** A 取候选自身最高的复合年度净收益；B 取候选减基线的最大年度人民币 PnL 贡献。两边删除同一年日期后按剩余交易日直接求均值，不重新拟合、重跑、复利拼接或增加 p 检验；并列取最早年。下表给出删除年 / 剩余日数 / 剩余 bp/日。全部原年度结果仍在机器证据中；此前宣布的“最大年度日均增量”第三规则也保留，主 8 配对与 B 选择相同年份。', '',
        '| 样本 | 配对 | 缩放 | A：候选最佳年度 | B：最大配对年度贡献 |',
        '|---|---|---|---:|---:|',
    ]
    for r in primary:
        choices = {x['rule']: x for x in primary_years if all(x[k] == r[k] for k in ('period', 'candidate', 'baseline', 'risk_scaling'))}
        cols = []
        for rule in ('candidate_best_year_return', 'maximum_paired_annual_pnl_increment'):
            x = choices[rule]
            cols.append(f"{x['removed_year']} / {x['remaining_sessions']} / {x['remaining_mean_daily_net_increment']*1e4:.6f}")
        lines.append(f"| {label_period[r['period']]} | {r['candidate']}−{r['baseline']} | {label_scale(r['risk_scaling'])} | {cols[0]} | {cols[1]} |")
    lines += [
        '',
        '验证集未缩放的两个配对删除最大增量年后均转负；仅删除候选最盈利年会遗漏这种依赖。缩放后两个验证配对按两种规则均保持正方向，但对应开发结果为负或删除最佳年后转负。因此不能选择某种删除口径来宣称一致稳健。', '',
        '**绝对收益与风险。** 验证集 10 万元基准下八条账户全部亏损；这不否定一个配对可能具有正相对增量，也不支持绝对盈利宣称。', '',
        '| 变体 | 缩放 | 累计净收益 | CAGR | 最大回撤 | 平均总敞口 |',
        '|---|---|---:|---:|---:|---:|',
    ]
    for r in base_validation:
        mt = r['metrics']
        lines.append(f"| {r['config']['variant']} | {label_scale(r['config']['risk_scaling'])} | {100*mt['total_return']:.4f}% | {100*mt['cagr']:.4f}% | {100*mt['max_drawdown']:.4f}% | {100*r['mean_gross_exposure']:.4f}% |")
    lines += [
        '',
        '趋势过滤在开发 72 个决策中关闭 26 次，在验证 36 次中关闭 25 次。两样本的所有主趋势增量（E1−E0、R1−R0，两种缩放）日均值均为负；缩放开启的验证 R1 平均总敞口仅 19.4880%。较低回撤和尾部损失伴随大量现金及不同风险暴露，不能直接称为择时 Alpha。月度、年度、下尾均值、Sortino/Calmar、HAC Sharpe、自相关及滚动诊断已全量保留；未做因子 Alpha 估计。', '',
        '主样本没有不足三个代表或风险历史不足 45 日造成的决策阻断。开发/验证的上市不足 252 日排除分别为 32/37 次，流动性排除 45/49 次，均为“标的×决策”出现次数。季度代表、资格时间和 D039 锚点已跨变体核对；同执行延迟下的资本、成本和现金压力不改变目标信号。2016–2017 两类排名增量为零，早期共同资格约束限制了策略分化。', '',
        '固定压力与资本路径全部报告，未挑最好结果。验证缩放后 R1−E1 的 10 万元七条路径点估计均为正，约 0.776765–0.949783 bp/日；开发对应七条路径均为负。验证未缩放 R0−E0 在三倍成本/滑点路径转为 −0.126900 bp/日。四资本基准下验证缩放后 R1−E1 为 0.844669、0.831987、0.813016、0.812883 bp/日；跨资本点估计一致不是独立验证。成本改变成交和现金约束，结果可非单调；现金延后 +1 日的 64/64 对、+3 日的 54/64 对运行与匹配基准的期末累计收益完全相同。这里仅比较期末收益，不表示整条净值路径、现金与应收构成或支付事件日期相同。', '',
        '16 条主账户逐标的 PnL（期末市值＋卖出−买入−费用＋确认分红）均与净资产增量核对至 10⁻⁶ 元；分红支付没有二次计入收益。正收益标的集中度和前五个盈利日集中度已保存。这不是 FIFO 完整往返交易归因，也不是因子因果归因，不能据此断言盈利由少数独立交易产生。', '',
        '**工程证据及其边界。** 独立库存审查覆盖 448 条完整日历、1,459,715 行持仓、67,016 笔成交、1,539 项分红权益及 3,078 项分红现金事件；无期末未付分红。检查了 2,240 条来源份额事件，其中 1,792 次在账户期应用（包括零持仓事件）。489,888 是重复的“运行×交易日”条数。原始价格、tick、T+1、容量、手续费及零股由执行工程作者另行复核，全部 448 条通过；该复核不冒称独立统计审查。未持有的退市样本包括五只清算和一只 ETF 转混合基金，后者不能称为现金清算，本次也没有验证持仓转型权益的实际执行。', '',
        '数据准入结论不变：110 个候选、16 个历史代表均保留，未删除数据贫弱代表；15 个必要全收益依赖不包含仅有 247 个交易日的 159573，未放宽 252 日资格。公开历史日线采用当前修订版本，缺少原始 vendor first-seen；“可得时间”包含来源支持的模型，不是观测到的精确发布钟点。H00300 日期精度导致所有变体共同执行 D039：锚点 D，D+1 日 21 点决策，D+2 执行，延迟压力为 D+3；特征和资格仍截至 D。', '',
        '实际分红到账未被观测，采用明确的规则模型并保留 +1/+3 日现金压力。日线不能证明 09:35–10:00 分钟成交、排队或真实盘口容量；容量仅为历史 ADV 的 1% 模型。账户权限及费率是假设，不是券商实际执行记录。数据未进入 2025–2026 策略留出区间；下载响应中曾有未经请求的当前行情字段，已隔离且未纳入研究，不能声称从未收到任何当前字段。', '',
        '正式状态仍为 `BLOCKED_HURDLE`：增量固定成本未知，最终主候选未冻结。四研究家族的 p=1 是未就绪占位值，不是四个已完成检验，也不能用探索性最优项替换。所有 8 个主配对公开，区间和 p 均为边际诊断；未完成多重边界上的确认。没有证据支持开启实盘、宣称因子 Alpha 或提前解锁最终留出集，也没有据此证明策略永远不存在增量。', '',
        '复现入口及精确文件哈希见 `statistical_review.json`、`review_code/independent_final_review_code_manifest.json` 与 `review_code/README_INDEPENDENT_REVIEW_V2.md`。原始 work 脚本按原字节归档，恢复其原路径后可重放；时间戳可能变化，绑定输入、检查结果和数值应一致。准入 attestation 和原审查报告未修改。', '',
    ]
    (P / 'STATISTICAL_REVIEW.md').write_text('\n'.join(lines), encoding='utf-8')

    evidence_names = [
        'results_summary.json', 'evaluation_provenance.json', 'registered_plan_v2.json',
        'registered_plan.json', 'admission_attestation.json', 'ADMISSION_REVIEW.md',
        'independent_inventory_matrix_review_v2.json', 'independent_bootstrap_reference.json',
        'independent_year_attribution.json', 'independent_statistical_diagnostics_v2.json',
        'independent_invalidated_v1_history_review_v2.json', 'independent_retired_scope_review.json',
        'evaluation_source_review_v2.json', 'execution_review.json', 'EXECUTION_REVIEW.md',
        'execution_review_v1_failed.json', 'superseded_v1/invalidated_attempts.json',
        'STATISTICAL_REVIEW.md', 'review_code/independent_final_review_code_manifest.json',
        'review_code/independent_review_code_manifest_v2.json',
        'review_code/independent_bootstrap_reference_code_manifest.json',
        'review_code/independent_reconciler_probe_manifest.json',
        'review_code/README_INDEPENDENT_REVIEW_V2.md',
    ]
    evidence = {(P / n).relative_to(ROOT).as_posix(): sha(P / n) for n in evidence_names}
    for period in ('development', 'validation'):
        f = ROOT / 'data/admitted_r1/phase2_v1' / period / 'manifest.json'
        evidence[f.relative_to(ROOT).as_posix()] = sha(f)
    for item in new_code:
        evidence[item['archived_path']] = item['sha256']

    report = {
        'schema_version': 1, 'reviewer': '/root/independent_admission', 'reviewed_at': now,
        'status': 'REVIEW_COMPLETE', 'decision': 'DESCRIPTIVE_VALIDATION_ONLY',
        'economic_conclusion': 'NO_CONFIRMED_ECONOMIC_INCREMENT',
        'formal_economic_status': 'BLOCKED_HURDLE', 'unresolved_technical_blockers': [],
        'final_candidate_selected': False, 'live_authorized': False,
        'final_holdout_accessed': False, 'factor_alpha_claimed': False,
        'new_hypothesis_tests': False, 'multiplicity_confirmed': False,
        'primary_capital_cny': 100000,
        'execution_provenance': {'git_commit': rp['git_commit'], 'source_hash': rp['source_hash']},
        'evaluation_provenance': ep,
        'evaluation_snapshot_verification': {
            'status': 'PASS', 'source_file_count': len(source_files),
            'complete_inventory_and_hashes_match': True,
            'summary_and_standalone_provenance_equal': True,
            'source_files_canonical_digest_matches': True,
            'statistical_and_identity_core_equal_execution_snapshot': True,
            'scope': 'Byte identity and local recorded chronology, not authenticated historical timestamps.'
        },
        'scope': {'run_count': 448, 'periods': main_results['periods'],
                  'grid': main_results['grid'], 'dataset_checks': diagnostics['dataset_checks'],
                  'local_chronology': diagnostics['local_chronology'],
                  'registered_plan_sha256': sha(P / 'registered_plan_v2.json'),
                  'main_results_sha256': expected_main},
        'checks': {
            'inventory': {'status': inventory['status'], 'totals': inventory['totals'], 'limitations': inventory['limitations']},
            'independent_inference_reproduction': {'status': bootstrap['status'],
                'status_counts': bootstrap['status_counts'], 'maximum_absolute_errors': bootstrap['maximum_absolute_errors'],
                'diagnostic_count': bootstrap['diagnostic_count'],
                'qualification': 'Numeric reproduction is not stationarity, multiple-testing or economic confirmation.'},
            'd039_and_cross_variant_qualification': diagnostics['decision_d039_and_cross_variant_qualification_checks'],
            'target_identity_groups_checked': diagnostics['target_identity_groups_checked'],
            'qualification_anchor_groups_checked': diagnostics['qualification_anchor_groups_checked'],
            'all_registered_configs_and_funded_sessions_verified': diagnostics['all_registered_configs_and_funded_sessions_verified'],
            'annual_and_daily_compounding_verified': diagnostics['annual_and_daily_compounding_verified'],
            'execution_review': {'status': 'PASS_ALL_448', 'reviewer_role': 'execution_implementation_author',
                                 'independent_statistical_review': False,
                                 'evidence': 'reports/real_data_phase3/execution_review.json'},
        },
        'invalidated_generation_history': diagnostics['superseded_v1_history'],
        'primary_rank_contrasts_all8': primary,
        'primary_year_deletion_all24': primary_years,
        'primary_accounts_all16': [{k: r[k] for k in (
            'period', 'path', 'directory', 'config', 'metrics', 'mean_gross_exposure', 'fees_cny',
            'maximum_single_instrument_weight', 'maximum_position_stale_sessions', 'year_contributions')}
            for r in primary_runs],
        'primary_four_contrasts': primary_contrasts,
        'primary_decision_diagnostics': primary_decisions,
        'primary_tail_and_dependence_diagnostics': primary_tails,
        'primary_scaling_effects': [r for r in diagnostics['scaling_effects'] if r['initial_cash'] == 100000 and r['path'] == 'base'],
        'primary_trend_ranking_interactions': [r for r in diagnostics['trend_ranking_interactions'] if r['initial_cash'] == 100000 and r['path'] == 'base'],
        'all_primary_capital_stress_rank_contrasts': [r for r in main_results['paired_effects'] if r['initial_cash'] == 100000],
        'all_capital_base_rank_contrasts': [r for r in main_results['paired_effects'] if r['path'] == 'base'],
        'cash_delay_terminal_return_comparison': {
            'comparison': 'stress_effects.terminal_return_difference == 0; exact terminal cumulative return equality only',
            'counts': {path: {'comparisons': len([r for r in main_results['stress_effects'] if r['path'] == path]),
                'equal_terminal_returns': sum(r['terminal_return_difference'] == 0 for r in main_results['stress_effects'] if r['path'] == path)}
                for path in ('cash_delay1', 'cash_delay3')},
            'limitation': 'Does not establish equal NAV paths, cash/receivable composition or payment-event dates.'
        },
        'primary_instrument_attribution': years['primary_base_instrument_attribution'],
        'descriptive_output_counts': {'four_contrasts': len(diagnostics['four_contrasts']),
            'scaling_effects': len(diagnostics['scaling_effects']),
            'trend_ranking_interactions': len(diagnostics['trend_ranking_interactions']),
            'tail_and_monthly_records': len(diagnostics['run_tail_and_dependence_diagnostics']),
            'year_deletion_records': len(years['year_deletion_rows'])},
        'formal_families': main_results['formal_four_families'],
        'interpretation': {
            'validation_scaled_R1_rank': 'Positive exploratory zero-fixed-cost relative evidence, including all three block intervals; corresponding development mean is negative. Not ignored, not confirmed.',
            'validation_absolute_performance': 'All eight 100k/base accounts lose money; absolute loss does not logically negate positive relative paired increments.',
            'year_deletion': 'Both candidate-best compounded year return and maximum paired annual CNY PnL contribution rules are reported symmetrically, with identical dates removed. No new p-values.',
            'cash_and_risk': 'Trend and scaling materially change market exposure; drawdown/tail reductions cannot be called timing alpha without exposure/factor identification.',
            'concentration': 'Instrument and positive-day PnL concentration is descriptive; individual FIFO round-trip concentration was not independently reconstructed.',
            'formal_family_placeholders': 'p=1 values are NOT_READY placeholders, not completed tests or adjusted evidence.',
            'evidence_limit': 'No winner chosen after results; no investment profitability or live-execution claim.'
        },
        'qualifications': [
            'Daily public-as-of research with current corrected vintage; original vendor first-seen and exact historical publication clock unobserved.',
            'All variants retain anchor D and shared D039 release: D+1 21:00 decision, D+2 base execution, D+3 delayed execution; anchor-bounded features and eligibility.',
            'Dividend actual receipt null; explicit rule-based modeled dates and +1/+3 session stresses are not broker receipt evidence.',
            'Daily OHLC cannot establish intraday queue, 09:35-10:00 prices or executable liquidity; historical ADV1% is a model.',
            'Broker permission, commission and initial account assumptions are counterfactual research inputs.',
            'Six retired candidates include five liquidations and one ETF-to-mixed-fund conversion; none selected/held. Conversion rights execution unsupported in this run scope.',
            'No 2025-2026 strategy holdout data admitted; unsolicited current envelope fields were received but quarantined, not parsed/admitted as strategy data.',
            'R1I and other research families not evaluated; no factor-alpha estimate.',
            'Unknown incremental fixed costs and unfrozen final primary candidate block economic confirmation.',
            'Marginal bootstrap/HAC diagnostics assume approximate dependence regularity; all paths/overlapping windows are dependent observations.',
            'Prior353 attempts remain invalidated; corrected448 are replacement runs with unchanged economics, not hidden discarded trials.',
        ],
        'evidence_files': evidence,
        'review_script_sha256': sha(Path(__file__)),
    }
    write(P / 'statistical_review.json', report)
    # Validate exact identities and key publication counts after writing.
    saved = read(P / 'statistical_review.json')
    assert len(saved['primary_rank_contrasts_all8']) == 8
    assert len(saved['primary_year_deletion_all24']) == 24
    assert saved['invalidated_generation_history']['attempts_retained'] == 353
    for path, digest in saved['evidence_files'].items():
        assert sha(ROOT / path) == digest, path
    for path in ('STATISTICAL_REVIEW.md', 'statistical_review.json'):
        print(json.dumps({'path': 'reports/real_data_phase3/' + path, 'sha256': sha(P / path), 'bytes': (P / path).stat().st_size}))
    print(json.dumps({'evidence_files': len(evidence), 'evaluation_source_files': len(source_files), 'status': report['decision']}))


if __name__ == '__main__':
    main()
