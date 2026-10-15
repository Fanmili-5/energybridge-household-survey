# V29任务区分度自审与验收

针对供真人扮演、训练和评估共享角色回应模型的任务世界，先修正优先41组，再逐条分类原857组显示后果相同的案例。此次为本项目助手自审，没有独立同行评审。结论限于源约束、条件物理、材料与采集工程，不把工程通过升格为真人有效性。

| 核查 | 结果与证据 |
|---|---|
| EB原生AC | 固定提交的IDF是全天可用、固定基础冷设定；运行器可覆盖。可用不等于持续耗电。本项目季节/有人房间的A适配保留，见[源核对](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/EB_AC_SOURCE_REVIEW.json) |
| 输入区分 | 调温非零至少0.5℃且累计30设备分钟；程序/可用时段至少20分钟，人工动作至少10分钟。为预定编码标准，非人群阈值；全部10000组只读候选预检通过 |
| 修正与不变性 | 修正1706组B，优先41组全修；家庭、需求、正常A、硬件、日期、角色政策及共同前史不变。没按EP结果挑方案 |
| 跨日期语义 | 3组4月30日任务在次日有制冷需求，不能笼统写整天没有需求。按设备与新增时段检查并写明其他服务保留，正反例通过；旧50签名失效后重新完整验收 |
| 原50先行 | 500正式+200物理对照，500实际浏览器；源/模拟/材料/提交/修订/恢复/撤回全部通过后才解锁950 |
| 950与全链 | 9500组源案例全部核验，1000页实际浏览器；520天气对照。六类全1000户重新核验，特征数值和配比保持 |
| 物理复用 | 1821侧本版新结果，19619侧严格同输入复用；全部21440侧重新读回；正常A硬边界失败为0 |
| 后果相同 | 当前992组；每组仍有达到标准的明确请求差异，页面中性说明；不隐瞒、不自动赋接受/拒绝 |
| 发布与版本 | 两套正式包；原邀请码和库保留。旧刺激的答卷保留，但不恢复到新刺激；隔离虚构答卷不进正式导出 |

当前同显示后果分类：{"temperature_permission_tradeoff": 332, "charging_permission_tradeoff": 391, "no_cooling_need_extra_request": 269, "other_visible_timing_or_handling_contrast": 0}。

原857组当前分类：{"charging_permission_tradeoff": 292, "modeled_consequence_difference": 13, "no_cooling_need_extra_request": 269, "temperature_permission_tradeoff": 283}。其中仍有844组显示后果相同；其余有模拟后果差异。修正范围覆盖全部10000组，所以新的同后果集合与原857不是同一集合。

证据：[聚合对比](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/PUBLIC_CONTRAST_SUMMARY.json)、[物理闭合](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/PHYSICAL_PRODUCTION_COMPLETE.json)、[原50](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/ORIGINAL50_CONTRAST_ACCEPTANCE_PUBLIC.json)、[950](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/OTHER950_CONTRAST_ACCEPTANCE_PUBLIC.json)。逐条修正账本与原始证据hash保留在学校；公共收据明确标注去实例转换，不把转换后哈希冒充原件。

尚缺：真人对角色、需求、时段和后果的理解，角色信息是否影响回答与解释；独立演员标签、分组和质量验证；建筑与设备实测校准；全国自然六类偏好比例。这些不能由加大A/B数值差或更多EP补成证据。下一步在原前端试读，检验近边界和同后果任务能否被理解，再决定是否作为正式benchmark题型保留。

后续benchmark应分别报告有模拟后果差异、仅有明确请求差异的题型，不能把编码差异当作已验证的主观代价或演员正确答案。
