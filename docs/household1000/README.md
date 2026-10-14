# V28：1000户完整参考世界与50/950正式采集

2026-10-15发布自查与修正见[审查报告](AUDIT_20261015.md)：核当前全案例源/回读数值与签名，修正恢复顺序、邀请码中断登记及旧看板状态。真人证据与最终浏览器提交复验仍明确待完成。

2026-10-14，1000户、2524名参考成员、10000组A/B和20000份基准IDF完成静态、六类实际覆盖、学校物理及前端源绑定验收。原50先核验500基准与200敏感性配对，通过后才核验950户9500基准配对，另完成520组气象敏感性。全部A服务/车辆/功率门及实际时序、计量和逐室/逐人闭合通过；B的不满足保留。[完整逻辑与依据](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/METHODS_AND_ACCEPTANCE.md)。

两个正式采集入口：[50户500任务](https://47.85.194.154/household50)、[950户9500任务](https://47.85.194.154/household950)。角色集合不相交，同一版生成规则，每户十个原季度分层日期。沿用成熟问卷，保留影响，增加本人年龄/性别选填，动作简略并可展开完整时段。研究者私下分发固定家庭的邀请码，参与者确认说明后填写，可恢复、修订和撤回。[采集协议与管理](../../deploy/formal_questionnaires_20261014/RELEASE.md)。

正式库与旧试填库独立。源情境仍为参考模型数据，实际答卷标记参与者提交来源；虚构验收记录不进正式导出，训练不自动准入。每条答卷连接角色/日期、源包/页面hash、可见输入、参与说明版本和回执。本人信息及当前回答在模型输出侧。

目标人口限定2020年中国大陆城市普通住宅家庭户，排除镇、乡村、集体户及非普通住宅。七普直接控制、辅助调查代理、联合补全与给定政策分层记录；未知就业不改成真实职业，精确作息/设施/服务/协商条件是明确情境。六类A101/B303/C319/D101/E85/F91为家庭结构和可行性约束下的研究配比，类型覆盖与EB一致；没有识别全国真实六类偏好占比。

设备为原EB六功能模型，每户4–6类覆盖，洗烘可共机；覆盖不是全国拥有率。08:00至次日08:00是完整24小时，保留跨夜端点；前史和有限服务尾段用于初始化/交付，没有全年运行或等末态净节能结论。原空调曲线边界截断与警告仍保留，模型温度不等于个人舒适，也未完成品牌或建筑实测校准。

本版统一修正全员外出/在家活动覆盖、源EPW湿度异常的可追溯处理和外部人员—SQL名称绑定。原家庭/日期/设备/冻结类型保持，A/B因作息修正重新生成；20400份IDF在人员绑定补充前后字节不变。源原件、旧版本和失败记录保留，未删户或掩盖失败。当前验收：[聚合报告](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/PUBLIC_ACCEPTANCE.json)、[50案例](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/FORMAL50_CASE_ACCEPTANCE.json)、[950案例](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/FORMAL950_CASE_ACCEPTANCE.json)。

正式发布允许启动实际角色答卷收集；真人理解/角色作用、自然偏好比例和最终benchmark性能仍需后续数据验证。50/950不自动等于统计独立的训练/测试划分。公开源码、方法与聚合报告；许可原件、逐户世界、IDF/天气/SQL、邀请码和答卷留在受控环境。

```bash
python3 scripts/household1000.py status
python3 scripts/household1000.py stages
python3 scripts/household1000.py check-source
python3 scripts/household1000.py doctor
python3 scripts/household1000.py require-generation --scope full1000EP
```

这些命令不启动EP、不调用模型、不生成真人答案。干净公开clone缺少受控输入，准入命令返回2；准备好学校当前目录后，核对实际内容绑定验收回执。[复现输入](INPUTS.md)、[完整链](PIPELINE.md)、[状态](STATUS.json)、[研究门](RESEARCH_GATES.md)。
