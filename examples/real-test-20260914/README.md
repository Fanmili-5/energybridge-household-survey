# 一份真实试填记录

2026-09-14，项目本人在线填写并提交反馈，已明确授权公开。EB 实际调用 gpt-4o-mini，EnergyPlus 实际运行；这不是固定答案演示。

- [完整保存记录 JSON](full-collected-record.json)：问卷原始答案、家庭配置、环境、两份方案、展示内容、真人反馈及来源关联。
- [保存的 SFT 候选记录](sft-candidate.json)：保留元数据与校验信息。
- [SFT messages JSON](sft-messages.json)：该记录实际构造的输入与真人回答。
- [校验信息及文件 SHA-256](verification.json)。

反馈：同意；`score=4.2`、`comfort_score=4.3`、`energy_score=2.9`、`vpp_score=4.2`，原因见 JSON 原文。

当时网站处于工程模式，因此原记录的 `synthetic_engineering_test` 标记及 `training_release=false` 均保留。这里的填写、评价和仿真是真实发生的，但不冒充正式采集样本。

仅移除了会话身份/凭据字段，移除范围见 `example_notice.omitted_transport_fields`。此处包含保存于数据库的完整 JSON 文档；不包含未留存的浏览器 HTTP 抓包，也不包含通过路径和哈希引用的 EP SQL、模型调用原文件等运行附件。JSON 中的路径是历史来源，不是访问令牌。

该测试发生在英文输入转换上线前，原始中文输入不做事后改写。新版本的英文 EB 输入说明见[中英文边界](../../docs/planner-language.md)。
