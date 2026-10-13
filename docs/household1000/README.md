# 1000户生产链：V23验收修复，V22设计数据

当前验收目录为 `gate_repair_production_20261013_v23`。V23保留V22的1000户、2524名成员、原十日期及10000对A/B；数据schema保留v22，验收与源码发布版本为v23。历史V17–V22保留，现行入口不再指向V17。

目标是让真人扮演有来源锚点、内部一致的中国城市普通住宅参考角色，评价B相对于独立冻结A的安排，并支持一个共享的角色回应模型。目标人口限定2020年中国大陆城市普通住宅家庭户，排除镇、乡村、集体户及非普通住宅。这里不是1000户实际住户的日记、拥有率或真实同意调查。

当前结果与范围以 [STATUS.json](STATUS.json)、[原50户验收汇总](PHYSICS50_SUMMARY.json) 和 [验收反例](ACCEPTANCE_REPAIRS.json) 为准。全量1000户EP保持关闭，真人答案为0，正式benchmark与训练未准入。

三个验收漏洞已改为：对实际世界/配对/设备账本/IDF/天气/代码/前端内容核hash；从冻结原50户独立生成期望运行集合，缺失、重复、错配和范围外结果拒收；正常A的服务及住宅/回路10分钟平均功率为硬门，B的不满足和风险保留供演员评价，不预填拒绝答案。

旧SQL只在IDF、天气、引擎和输出hash精确一致时复用，保存旧运行回执来源，依据当前账本重读服务与物理后果。不能把旧验收报告改名当新验收，也不能把已复用1400个物理运行说成新运行1400次。7/14日前史、入水温度与空调模型形式比较是参考敏感性；原曲线截断与严格湿球点比对失败保留。

每户4–6类EB功能设备是任务覆盖，333/333/334户分别覆盖4/5/6类；洗烘可共用一个实体资产。这不是全国电器拥有率。日程、照护、服务目标、惯常A、可协商条件和未知主观取舍分别记录。十个原季度分层日期为每户十个任务日，主观察窗08:00至次日08:00，前史和有限服务尾段用于初始化/交付，不做全年模拟，也不声称A/B末态相等或等服务净节能。

原成熟前端继续使用采用/不采用B、四项可空评分和原因。模型输入取演员实际可见的信息和合法历史，当前答案留在输出侧。工程填写和浏览器检查不构成真人试读。

阅读顺序：[完整链条](PIPELINE.md) → [逐环节科研依据](../research/collection-adjustment-20260930/household1000/gate_repair_production_20261013_v23/PRODUCTION_LOGIC_CHAIN.md) → [来源与未知](../research/collection-adjustment-20260930/household1000/gate_repair_production_20261013_v23/EVIDENCE_CHAIN_REVIEW.json) → [受控输入](INPUTS.md) → [复现核验](REPRODUCTION.md) → [证据门](RESEARCH_GATES.md)。

```bash
python3 scripts/household1000.py status
python3 scripts/household1000.py stages
python3 scripts/household1000.py check-source
python3 scripts/household1000.py doctor
```

这些命令只读，不启动EP、调用模型或生成真人答案。公开载荷是第一方源码、无案例前端模板、合同、科研依据和汇总验收；许可调查原件、逐户包、IDF/天气/SQL、联系人和答卷不公开。完整重建需自行准备获准使用的受控输入，干净clone不具备全部数据。
