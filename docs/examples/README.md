# SFT 格式样例

本目录两份 JSONL 来自 2026-09-12 的隔离工程验收：完整 v4.1 问卷经过当前 v3.3 单日流程，在学校计算节点上实际运行两次 EnergyPlus 24.1；规划回复使用禁止联网的固定模型桩，评分也是工程测试值，因此没有付费模型调用，也不是真人回答。

- `engineering_sft_candidate.jsonl`：一条实际完整候选导出，包括来源、问卷快照、家庭配置、模拟方案、哈希和 messages。
- `engineering_messages.jsonl`：同一记录的 messages 投影，用于查看常见对话式 SFT 输入形状；不是已发布训练集。

完整候选的 `schema_version=eb.paired_ep.v3.3`、`feedback_version=eb.binary_decision_four_scores_reason.v3`、`questionnaire_version=eb.persona_questionnaire.v4.1`、`target_source=engineering_test`、`training_release=false`。当前默认真人导出会排除该记录。不能把仅剩 messages 的投影混入真人训练集。

messages 的 user.content 是序列化 JSON，只有 household_answers 和 display；assistant.content 是序列化 JSON，包含 decision、score、comfort_score、energy_score、vpp_score、comment。本例 comment 明确标明是工程测试。

正式训练前仍需过滤工程记录、审核失败／回退与问卷质量、冻结数据版本、去重并按家庭分组划分训练与验证数据。浏览器会话分组不能证明现实家庭唯一。
