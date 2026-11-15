# M6 采集协调故障及恢复

2026-11-15T13:06:13Z，外部工具请求7仍在执行（stock_execution，已提前计1HTTP等价）时，R1I采集器在未看到跨工具network.lock的情况下请求begin；核心BudgetLedger正确以UNRESOLVED_INFLIGHT_REQUEST全局停止，没有发送第二个请求。外部请求7在13:06:39Z完成，实际可见JSON正文27,803字节及终态已持久化。它不是预算耗尽、不是遗失请求，也没有覆盖原消费。

故障原账本保存`incidents/budget_after_concurrent_stop.json`。经root核对所有7请求终态、全局与分项额度有余额、无活动网络lease，登记一次**协调故障恢复**：仅将stopped复位false，原stop原因/时钟/消费/所有请求/原hash保留在恢复事件；不增额度、不删除或重编号请求。此恢复只针对已证明完成的该次并发误判，不适用于真实额度超限、未知请求或存储故障。M4/M5账本不变。

根因是调用方跨工具请求没持共享网络锁；M6 collector新增begin_external/finish_external持有可核验token lease直到工具终态，其他采集器等待锁，不能把活动工具请求误当遗失请求。lease丢失不自动回收。独立测试会验证串行保护、实际计费和重启停机仍有效。scope字节超限仍保守全局停止，本轮不放宽。

请求7原elapsed_seconds误用了finish时刻的perf_counter；原值不改写。可观察完整started_at→ingested_at间隔为39.610676秒，报告单列修正；正文和HTTP次数不受影响。
