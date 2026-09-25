# 离线十天案例与真人反馈合同（待 D 最终验收）

状态：**设计与纯离线校验完成；案例库 0、真人反馈 0、可发布结果 0**。`offline_collection_contract.py` 是验证和回放规则，不连接模型、API 或参与者服务；其单元测试仅在内存中使用标明 `synthetic_engineering_test` 的虚构样本。

## 1. 案例库入口

只读取最终验收的离线文件，不能从用户请求现场生成计划。根对象须有：

- `schema_version="eb.offline_casebank.v1"`、`status="accepted_offline"`。
- `study_batch_id`、`consent_version`，与可信服务端的参与者同意记录匹配。
- `semantic_contrast_evidence_sha256`，绑定**另交付并独立验收**的 `eb.accepted_day_contrast.v1` 索引；索引状态为 `independently_accepted`，其 `final_evidence_sha256` 与案例库一致，逐 `case_id` 锁住 A/B 各自前事件状态哈希、方案族/真实模板指纹、A/B 当日计划与动作哈希，以及语义差异决定。消费端必须同时读取该索引，缺失、额外案例或不一致均拒绝。测试中的索引只是内存夹具，不能当成独立验收证据。
- `profile_sha256`、`behavior_sha256`、`questionnaire_sha256`、`final_evidence_sha256`，均为 64 位小写 SHA-256；上游 D 验收记录须独立证明这些指纹对应最终输入与运行证据。消费端还须核对案例库完整 JSON 的规范化 SHA-256。
- `records` 恰有 `cityrole-0001` 至 `cityrole-0300`，每条的 `profile_sha256` 与根对象相同，`days` 恰为 1–10 日递增。根对象和每日记录均不得预填 `participant_feedback`。
- 每日记录含唯一 `case_id`、`day_index`、`case_status="accepted_simulation"`、`plan_family_id`、`plan_template_fingerprint`、`history_group_id`、`history_max_day_index`（0 至前一日）、`pre_event_state_hash_A/B`、`semantic_contrast`、`pair_status`、`collectable`、`plans`。第 1 日 A/B 共用背景，后 9 日可各自承接既定轨迹。`plans` 仅含 `A`、`B`，各有 `plan_version_id`、`plan_hash_scope="day_slice"`、与案例相同的 `day_index`、`plan_hash`、`day_action_hash`、`display_payload_hash`、`metrics_hash`。逐日展示文本与能耗指标由这些指纹约束，实际载荷须由另一份经核对的离线文件按哈希读取；十天总计划哈希不能充作逐日对照。
- `semantic_contrast` 来自已验收且早于反馈的**当日**证据，记录 `source="accepted_pre_feedback_day_evidence"`、`evidence_hash`、`status`；`meaningful` 还须有 `same_day_action_change=true` 和 `basis`（设备时序、温度、费用权重、任务完成、舒适影响或电网服务之一），并要求当日计划与动作哈希均不同，此时才可 `contrast_valid`、`collectable=true`。第 1 日共用背景，不收偏好；`equivalent` 或 `inapplicable` 须写 `reason`，即使哈希不同也只能 `no_effect_or_identical`、`collectable=false`。后续日仅轨迹历史造成的差异不能冒充当日动作对照。哈希/标签校验不能替代人工或独立程序核对证据载荷及语义判断；仅 ID、版本或元数据不同不是有意义的对照。有意义差异不要求一定节电。

固定画像是角色条件，不得把前几日真人回答回填成固定画像字段。第 d 日能用的历史最多到 d−1 日；训练样本的原始历史也须按该时间边界构造。few-shot 同角色 support 若用于评测，只能是目标日以前、训练边界许可且在推理时提供的记录，不能参与参数训练或含目标/未来回答。

## 2. 展示与提交

参与者以服务端生成的匿名 `actor_pseudonym` 固定绑定一个 `role_id`；默认一角色一位在研参与者。中断恢复保持角色与十天进度。服务端记录同意版本、时间、批次和有效状态；只有与案例库匹配的有效同意才能以真人来源提交。服务端从已认证会话确定 `data_origin`，拒绝浏览器自报来源或同意。服务端用至少 16 字节的私有种子、案例库哈希、参与者代号、角色及日序确定左右顺序，保留种子承诺与 `display_order_hash`；前端只呈现左右方案，不展示 A/B 内部标签。实际系统应保存这些字段，并在同一事务内执行唯一性与幂等检查。

每次提交包含以下字段：

| 字段 | 规则 |
| --- | --- |
| `schema_version` | `eb.role_ten_day_blind_feedback.v1` |
| `casebank_sha256`, `profile_sha256` | 与已锁定案例库和固定画像一致 |
| `actor_pseudonym`, `role_id`, `case_id`, `day_index` | 与已分配角色及可收集日一致 |
| `display_order_hash` | 与该参与者该日的服务端随机化一致 |
| `choice` | `left`, `right`, `tie`, `reject_both`, `cannot_judge` 五选一 |
| `reason` | 非空、最多 1000 字；无法判断或都拒绝也需说明原因 |
| `ratings_by_side` | `left` 和 `right` 各保留 `score`, `comfort_score`, `energy_score`, `vpp_score` 四字段；每值 1–5 的有限数或显式 `null` |
| `idempotency_key` | 12–128 字符；同键同内容返回原回执，同键异内容报错 |

`missing` 是未提交，没有反馈行；`cannot_judge` 是主动提交的无法判断；`withdrawn` 是撤回；`superseded` 是同日修订后的旧版本。后两者保留在受控审计事件中，不进入训练导出。整位参与者撤回同意后，该参与者所有日的记录退出训练导出，不能继续提交；重新参加需要新的同意与研究批次。

提交时深拷贝反馈和同意快照，事件哈希包含服务端确定的来源；调用者随后改写原对象不会改写审计记录。受控审计导出保留来源与同意快照，训练导出再次核对**当前**同意状态、版本、批次、案例库、公开角色包、画像及 meter 版本。旧记录保留在审计视图，不随新放行门重新获得训练资格。

独立 `/roles` 实行服务端顺序开放：第 1 日与非对照日确认已查看，对照日提交或附原因明确跳过，才可访问下一日。服务端记录展示、确认、跳过、回答、修订及撤回；直接访问未来日或未展示即提交均拒绝。已经看过更晚日再修订早日的事件标记 `future_exposure`，从严格时间顺序训练视图排除，审计仍保留。这只证明服务端操作顺序，不证明参与者实际理解、阅读时长或注意力。

## 3. 导出与切分

受控审计导出保留事件版本、左右实际计划哈希、计划版本、方案族、历史组和状态。训练导出仅含**当前有效、已同意的真人** `submitted` 事件；工程测试、撤回和被替换事件一律排除。训练导出仍需按研究方案审查自由文本中的隐私信息，再决定是否对外分享。

预注册**主轨**检验未见家庭：actor、role、同角色历史组隔离，明确允许训练与测试见到相同方案族，因此主轨不能声称未见方案泛化。**严格附轨**检验未见家庭且未见方案族：事先分别锁定互斥角色集合和互斥真实方案族集合，训练只取训练角色×训练方案族，测试只取测试角色×测试方案族，交叉格剔除；不能把同一模板重新编号冒充新方案族。两轨都逐行要求历史终点早于目标日，并核对参与者、角色、历史组不跨边界。若严格附轨没有非空、互不泄漏的训练/测试样本，报告不可行，不以主轨结果替代。

独立 `/roles` 已补持久化事务、同源检查、同意/撤回 UI、工程夹具浏览器回归和版本化导出核对；这些是工程验证，不代表 F 已放行真实 G 数值或真人采集。现有 8 项离线合同测试只是基础合同门。
