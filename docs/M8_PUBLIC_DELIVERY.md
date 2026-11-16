# M8 GitHub公开交付

本分支发布M8可公开的结果和代码补丁，完整本地研究已完成32条账户路径。先读[投资结果](../reports/m8_public/SUMMARY.md)，文件清单及哈希见[MANIFEST](../reports/m8_public/MANIFEST.json)。

研究结论INCONCLUSIVE：2022—2024验证R0−E0成本后均值为+1.6474bp/日，95%主区间[−2.8944,+6.5383]bp；开发为−1.4094bp/日。固定费用未知，经济确认BLOCKED_HURDLE。归档本配置，不扩大产品/参数搜索。

本分支仅以公开基准`3df2391dc646ab98122ac6b029d0ef7a5cef2b32`为祖先，没有完整本地M8提交链中的原始量额、财报长原文或完整订单/持仓表。完整本地交付提交为`5378c7a5a44880a03f6665634ae8764caf726df5`，这里的SHA只作审计指针，不声称该提交已在GitHub公开可达。

`reports/m8_public`保留原摘要包51个文件的原字节。包内README关于“尚未推送完整本地分支”的说明仍有效；包内形成时的“尚无远端CI”仅是包装时状态，后续CI状态以本分支实际GitHub检查为准。SUMMARY提到的完整ACCOUNT_PATHS及账户账簿仅本地可用，不能将公开净值包视为完整原件准入。

代码变更以`ACCOUNT_IMPLEMENTATION.patch`、`POSTRUN_PLOT_ONLY.patch`和`INDEPENDENT_REVIEW_CODE.patch`交付，没有将缺少许可原件的研究入口伪装为完整可复现运行环境。这个发布分支的生产源码仍为原公开基准，因此其现有CI检查基准源码，不代表独立重跑了M8。M8实际完整本机测试882通过，完整结果的干净检出872通过/10项原件依赖跳过；32账户及主要统计已由非作者独立核对。

用户已将完成后推送设为持续要求，见[交付政策](DELIVERY_POLICY.md)。本次只发布既有成果，不采集数据、不重跑收益、不打开股票旁线、最终留出或paper/live。
