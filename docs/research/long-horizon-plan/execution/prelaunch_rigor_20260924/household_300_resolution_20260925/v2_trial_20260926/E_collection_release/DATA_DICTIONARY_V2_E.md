# V2 E 工程数据字典

本包是 300 个固定合成角色的工程候选。公开七表只供隔离角色展示和基准接口读取；内部两表保留物理与设备分配审计。问卷事实是合成设定，十天指标来自 EnergyPlus 代理结果，真人反馈为 0。

| 表 | 行数 | 主键/粒度 | 含义 |
| --- | ---: | --- | --- |
| `households_300.csv` | 300 | `role_id` | 家庭卡、H6 本户归属面积、整套设计面积、模型净面积、设备拥有/纳入边界、经济与偏好情境 |
| `members_300.csv` | 749 | `role_id, member_id` | 合成成员角色、年龄设计值、作息与偏好 |
| `member_links_300.csv` | 585 | 关系边 | 合成家庭关系，非真实亲属记录 |
| `member_windows_300.csv` | 2,878 | 成员/日型/序号 | 典型在家时窗；不规律者保留 `UNKNOWN_IRREGULAR` |
| `devices_300.csv` | 715 | `role_id, device` | 本轮 EB 纳入设备；空调只表示 D 实际选中的可控单元及区域 |
| `question_answers_300.csv` | 20,576 | 角色/题目/选项序号 | 66 题的长表。300×66=19,800 个唯一角色题目对；B05 和 X_PROTECTED 多选额外展开 776 行 |
| `provenance_300.csv` | 6,900 | 来源记录 | A/B/C/D 字段来源与证据身份 |
| `device_inventory_300.csv` | 734 | `role_id, device` | 原合成持有清单，含 19 条未纳入 EB 的背景设备；这些设备的实际使用未知，不记入本轮 EB 计量 |
| `zones_300.csv` | 2,191 | `role_id, zone_name` | C 候选区与 D 实际受控空调区分列；区域名仅在内部表 |

`households_300.csv` 中 `synthetic_owned_device_types`、`eb_intervention_device_types`、`owned_background_excluded_device_types` 三列分别表示原合成持有、本轮纳入、仅背景设备。`owned_ac_unit_count` 是问卷拥有数量；`eb_controllable_ac_unit_count` 是本轮可控数量；`eb_selected_ac_zone_count` 是 D 实际选区数量。`cityrole-0025` 和 `cityrole-0249` 分别为拥有 2 / 可控 1；`cityrole-0275` 原持有洗衣机和烘干机，但本轮 EB 纳入为空。

面积字段不可混用：`h6_design_building_area_m2` 是本户归属的合成建筑面积；`whole_dwelling_building_area_m2` 是整套住房设计建筑面积；`household_accounted_net_area_m2` 是本户计入模型的净面积；`whole_dwelling_modeled_net_area_m2` 是整套模型净面积。10 个合住角色的其他住户人数写 `UNKNOWN`。这些都是设计/模型量，非实测住所面积，也不能代表整套电费。

`device_inventory_300.csv` 中本轮纳入的 491 个非空调类型行来自 D 实际注入设备，224 个空调行来自 C 可控候选区经 D 实际选区；另外 19 行保留 `UNKNOWN_UNVERIFIED_BACKGROUND` / `NOT_INCLUDED_UNVERIFIED_BACKGROUND`。后者不是“实际不用电”。公开 `devices_300.csv` 不收录这 19 行，家庭卡仍明确显示原持有与纳入范围。

`question_answers_300.csv` 的 `response_status` 是合成角色问卷适用/跳题状态，不是真人填写。`B05` 按 EB 纳入设备填写，原持有清单另见库存表；`X_COUNT_ac` 保留问卷拥有数量，不当作可控数量。每题 `applicable` 按 66 题 codebook 的设备与 show_when 条件逐户复核。

`provenance_300.csv` 的 6,900 行是每户 23 条家庭结构、角色证据和物理绑定的**字段组摘要**，并非 66 题逐题来源的全展开。逐户逐题的 `basis` 在 `question_answers_300.csv`；每题的实际 basis 计数、构念参考来源 ID、生成规则文件及其 SHA 在独立的 `QUESTION_MAPPING_66_V2.json`。父版 `B_profile/QUESTION_MAPPING_66.json` 有 7 题仍记录旧 basis（B05、X_AREA、X_BUILDING、X_BUILDING_AGE、X_EXTRA_DEVICES、X_FLOOR、X_TENURE），不作为本轮 v2 题值来源证明。新映射对 66/66 题有非空来源或明确实验规则，`experimental_profile` 指向旧 B 生成器中按角色序号及预设数组轮转的规则，属于合成情境，不是受访者答案或来源数据的同户频率。

`participant_feedback_status=NOT_COLLECTED`，`event_presence_status=UNKNOWN`，`population_weight_status=UNKNOWN`。十天 D/G 指标不填进静态角色表；它们由隔离 G casebank 按 `role_id/day_index` 连接，且不代表真人偏好或实测节能。
