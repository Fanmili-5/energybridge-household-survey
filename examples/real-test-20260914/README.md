# 真实试填样例

2026-09-14，项目维护者在线填写问卷、运行 EB 和 EnergyPlus，并提交反馈。本案例已获本人授权公开；数据库中的工程测试标记保留。

| 文件 | 内容 |
|---|---|
| [questionnaire-answers.json](questionnaire-answers.json) | 实际提交的答案、提交时间及问卷版本 |
| [full-collected-record.json](full-collected-record.json) | 合并后的答卷、配置、情境、两份方案、展示结果与反馈 |
| [cleaned-supervision.json](cleaned-supervision.json) | 从该案例提取的 `input` / `output` |
| [verification.json](verification.json) | 来源核对结果与文件哈希 |

本次选择为同意，四项评分依次为 4.2、4.3、2.9、4.2，原因保留原文。规划使用 gpt-4o-mini，仿真使用 EnergyPlus。

`cleaned-supervision.json` 的输入包括家庭画像、事件条件、两份计划和参与者看到的仿真结果；输出为选择、评分及原因。它不包含问卷题干、作答状态、EB 推理、system prompt 或训练 messages。

该案例产生于英文 EB 输入转换功能上线前。英文清洗结果是后续导出的，原始运行记录没有改写。样例用于核对数据格式，不作为正式采集数据或模型效果证据。

导出命令和服务器保存格式见[数据说明](../../docs/DATA.md)。
