# M4 D 验证

命令：`.venv/Scripts/python.exe -m pytest tests/test_m4_data_feasibility.py -q`

结果：**10 passed**。覆盖请求尝试事前计数、失败也占预算、字节上限、未知/非HTTPS源与2025+原件拒收、真实休市边界、缺字段不缩池、现名不推历史状态、行业解析冲突拒收、财务冲突字段隔离、零人工放行和3,779固定分母。

离线重建：`python scripts/m4_data_build.py`成功。`source_manifest.json`中58个本地证据对象的SHA256全部匹配。实际3份全日期BaoStock响应日期/复权口径/代码去重均通过构建检查。没有运行真实策略、收益统计、R1实验或任何2025行情查询。

保留失败：本地BaoStock辅助接口导出错误、空CNInfo搜索、缺orgId时返回其他发行人的查询、旧M3 SSE PDF URL返回HTML、3个财务来源冲突。失败没有被改成成功，也没有从候选队列或覆盖分母删除。

独立agent复核与人工签认区分：本文件记录本执行agent验证；另一独立agent已完成原件/截面复核，范围与限制见[独立数据审查](../m4_review/DATA_INDEPENDENT_REVIEW.md)。agent复核不代替人类签认，本批独立人工验收数仍为0。
