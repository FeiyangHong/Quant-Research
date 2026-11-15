# B：共享持久预算

基准8a9977c的离线6字节响应/5字节上限反例于2026-11-15T10:55:55Z复现：`finish`抛出Body byte cap breached，但磁盘`used.new_body_bytes=0`，attempt没有终态。临时账本位于`C:/Users/ELESSA~1/AppData/Local/Temp/m5_budget_baseline_qu0xk8jb/budget.json`；没有触碰M4原账本。

修复为`quant_research.budget.BudgetLedger`：排他账本锁、原子replace/fsync、请求前持久预扣次数、响应对象先落盘，再将实际字节和请求终态及stopped落盘，最后才抛预算异常。重复相同finish直接返回原终态；冲突finish保留首次消费并停止。重启遇到超限/停止/未完成请求均拒绝新请求。崩溃遗留锁不自动抢占；需要另行有证据的恢复，不删除锁后假装请求不存在。

M5三条工作流使用独立`data/raw_m5_equity/budget.json`和共享network锁，整个响应读取/记账串行化，避免三个进程同时消费旧余额。分项预算与总预算同时检查；失败、空体、SDK登录/分页/退出均计请求。HTTP拒绝隐式重定向，新地址需显式验证并计新尝试；日期/域名在begin之前校验。旧来源reuse只核验哈希，不增加下载成本。

HTTP按剩余额度停止读取，并把到达边界的响应保守标TRUNCATED_BUDGET。BaoStock SDK先整包返回，因此可能实际超过剩余字节；此时真实已接收的解码UTF-8字节仍完整计账并停止后续请求。预算并非TCP、TLS、协议头或SDK内部未返回的部分字节精确计量，不能声称网络传输绝不超额。SDK异常会留下FAILED终态；无法观察的SDK部分接收量不能伪造为准确网络流量。

第一轮离线验证：`python -m pytest tests/test_m5_budget.py tests/test_m4_data_feasibility.py -q`：23通过。覆盖超限后读盘/重启、幂等与冲突、未完成请求重启、三线程串行采集不丢计数、分项限额、HTTP失败、域名/日期/重定向、损坏账本拒绝重置。M4现有10项保持通过。独立复核及补充SDK测试由最终审查记录绑定。

独立第一轮发现两个剩余缺陷并保留失败：旧格式已完成记录没有terminal键，重复finish仍可能二次收费；归档对象损坏导致在计入已收到字节前失败。第二轮统一旧终态识别，并把对象写入/哈希冲突作为可持久化终态失败，真实字节先记账、停止后报错；禁止extra改写id/kind/scope等预算身份。未改独立反例，复测4/4通过；连同旧M4、作者预算、SDK异常及实际出站日期保护、市值测试共36通过。独立反例原稿和失败输出位于`review_code/m5/test_independent_budget.py`、`reports/m5_review/budget_round1_failures.txt`。两轮至此结束；系统不能在账本所在磁盘本身不可写时承诺成功落盘，此时原inflight/遗留锁保持拒绝重启，不凭空清账。
