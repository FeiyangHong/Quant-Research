"""Publish a completed strict review; never edit datasets, runs or review tolerances."""
import argparse
import hashlib
import json
from pathlib import Path

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='work/execution_review_v2_final')
    p.add_argument('--output',default='reports/real_data_phase3')
    a=p.parse_args();source=Path(a.input);out=Path(a.output)
    report=read(source/'execution_review.json')
    code=Path(__file__).with_name('review_real_execution.py')
    toy=Path(__file__).with_name('test_execution_review_toy.py')
    old=out/'execution_review_v1_failed.json'
    expected_source='d8d265eed26337ba8a58e2dff809af3acc71550232ecbddaa2b94a7a3da6ba7a'
    assert report['status']=='PASS' and report['reviewed_runs']==448 and report['numerical_finding_count']==0
    assert len(report['periods'])==2 and {r['period'] for r in report['periods']}=={'development','validation'}
    assert report['audit_code_sha256']==sha(code)=='374cb0865d2be3c71819eec6a8d666bf9dd884a1cd9a6a19db815fbd0b4a94a5'
    for period in report['periods']:
        assert period['status']=='PASS' and period['reviewed_runs']==224
        assert len(period['runs'])==224 and all(r['status']=='PASS' and not r['findings'] and r['source_hash']==expected_source for r in period['runs'])
        summary=Path('runs/real_r1_'+period['period']+'_v2/matrix_summary.json')
        assert sha(summary)==period['summary_sha256']
    assert sha(old)=='18321d305197c4b051b2a2f4790bdc629837e17906197041cd7040cae9eba654'
    selfcheck=read('work/execution_review_toy_checks.json')
    assert selfcheck['status']=='PASS' and selfcheck['tests_run']==16
    assert selfcheck['review_code_sha256']==sha(code) and selfcheck['selfcheck_code_sha256']==sha(toy)
    report.update(execution_git_commit='b308ccc',execution_source_hash=expected_source,
        execution_version='real_r1_development_v2 + real_r1_validation_v2',
        toy_selfcheck=selfcheck,
        review_code_files={x.name:sha(x) for x in (code,toy,Path(__file__))},
        prior_rejected_execution_review=dict(path=old.as_posix(),sha256=sha(old),status='FAILED_ENGINE_FEE_ROUNDING'),
        total_counts={k:sum(r['counts'][k] for r in report['periods']) for k in ('fills','buy_fills','sell_fills','odd_lot_sales','position_rows')},
        review_input_location=source.as_posix(),
        publication_note='Both complete matrices passed unchanged strict-decimal audit before current report publication. Rejected v1 retained; report-only evaluator revisions do not alter execution identity.')
    text=(source/'EXECUTION_REVIEW.md').read_text(encoding='utf-8')
    text+='\n执行版本固定为 `b308ccc`，源码集合SHA256为 `'+expected_source+'`。两批共核验 '+str(report['total_counts']['fills'])+' 笔成交和 '+str(report['total_counts']['position_rows'])+' 条持仓估值，严格Decimal差异为0。全部来源来自冻结输入与已有账簿，未生成新回测。\n'
    text+='\n16项toy故障注入自检已通过；其代码与本审查/发布代码SHA保存在机器报告。旧v1的63处数值差异及352条已审记录继续保存在 `execution_review_v1_failed.json`，未删除或改写。当前工程PASS只针对v2模拟执行一致性，不恢复旧v1资格，也不是收益确认或实盘许可。\n'
    text+='\n正式统计报告使用的评估代码另记SHA与Git提交。即使报告核算helper单独修订，本报告核验的交易执行仍是以上固定版本；原始数据的当前修订版本和历史可用时间重建限制仍适用。\n'
    out.mkdir(parents=True,exist_ok=True)
    (out/'execution_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'EXECUTION_REVIEW.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(status=report['status'],reviewed_runs=448,counts=report['total_counts'],json_sha256=sha(out/'execution_review.json'),markdown_sha256=sha(out/'EXECUTION_REVIEW.md'))))

if __name__=='__main__':main()
