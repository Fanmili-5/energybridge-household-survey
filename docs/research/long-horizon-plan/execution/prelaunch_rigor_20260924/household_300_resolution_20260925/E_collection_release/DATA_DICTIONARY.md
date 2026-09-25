# CSV 数据字典与读取说明

所有 CSV 用 UTF-8 **带 BOM** 与标准双引号转义写出，可由 Excel 直接打开；列名为英文稳定键，值与角色卡保留中文。表中没有真人问卷回答、十天方案或仿真结果。`PACKAGE_MANIFEST.json` 给出每个输入、输出的 SHA-256 和行数。`role_id` 为所有表的外键，`cityrole-0001..0300` 恰各出现一次于主表。

## 空值、状态和时间

| 表达 | 含义 |
|---|---|
| 空单元格 | 该列无单个标量值；必须看邻近状态列或所属表。例：轮班成员无固定时窗。空值不代表 0。 |
| `UNKNOWN` | 事件日是否在家、人口权重、轮班时钟等尚无可确认值。 |
| `NOT_APPLICABLE` | 原 66 题按设备选择或显示条件跳过，或该设备类型无该参数。 |
| `NOT_COLLECTED` | 真人反馈尚未发生。 |
| `NOT_EXPORTED_PENDING_D_ACCEPTANCE` | 旧或未验收的 D 仿真不进入固定画像 CSV。 |
| `matches_F_experimental_whole_dwelling` | 27 合住户的 `X_AREA` 对应 F 验证的整套源单元**设计**建筑面积档；不是本户 H6 分摊面积或实测整套面积。 |

时钟码 `H_`、`E_`、`D_` 和 `P_HOT_WATER` 是原 EB 值域中**本地时区午夜起的小时数**，例如 `19.8333333333` 约为 19:50。`D_home_ev` 早于接入时刻表示次日。`T_` 内部值是小时，`task_duration_minutes` 是乘 60 的显示值；原题向参与者问的是分钟。空调 `H_ac` 是枚举：`afternoon`=14:00–23:00、`evening`=18:00–23:00、`all_day`=全天、`custom`=自选；切勿把 afternoon 或 evening 扩成 12:00–18:00 或 18:00–24:00。以冻结的 `QUESTIONNAIRE_CODEBOOK.json` 标签为准。

## 表、键与列

### `households_300.csv`：一户一行，300 行

- 键与版本：`role_id`、`source_version`。城市与结构：`city`、`province`、`administrative_city_code`、`family_size`、`generation_category`、`older_member_present`。
- 典型日粗档：`weekday_day_presence`、`evening_presence`、`routine_regularity`。它们来自成员合成作息，**不是事件日占用**。
- 经济/态度：`monthly_income_scenario_yuan`、`monthly_bill_scenario_yuan` 均为人民币/月情境；`bill_pressure_design_level` 的 1 是压力最高、5 是当前压力最低；`bill_pressure_description`、`budget_explanation` 为可扮演说明；`tradeoff_condition`、`cost_importance_1_5`、`comfort_importance_1_5`、`grid_importance_1_5`、`control_condition`、`notice_hours` 均为实验设定，非频率估计。
- A/F 住宅口径：`housing_form`、`h7_room_category`、`h7_room_minimum`、`h6_per_capita_area_bin_m2`、`h6_design_building_area_m2`、`h6_area_basis`。H7 自然间数排除厨房、厕所、过道和厅，且五间以上是顶格；H6 类数值是**本户**设计建筑面积。`whole_dwelling_building_area_m2` 在 27 合住户来自 F 对整套源单元净面积按实验 0.95 换算，独立户来自 A；均为设计值。`whole_dwelling_area_status` 区分来源。`x_area_answer_code` 是 B 原题值，`x_area_semantic_status` 指出它与整套设计面积的匹配来源。
- C 原型/天气：`building_type`、`floor_position`、`source_floor`、`virtual_building_id`、`housing_mode`、`source_catalog_key`、`source_unit_exposure`、`household_accounted_net_area_m2`、`selected_controlled_zone_area_m2`、`common_allocated_area_m2`、`selected_window_count`。面积单位为㎡；受控区是 C 候选集合面积，**不是每台 AC 的实际安装区**。
- 天气和文件引用：`weather_station_key`、`weather_station_distance_km`、`weather_epw_repo_path`、`weather_epw_sha256`、`idf_repo_path`、`idf_sha256`。路径相对于仓库根目录，不含本机绝对路径；CSV 本身未附 IDF/EPW，天气源可能处于私有研究目录。`owned_zone_count`、`ac_candidate_zone_count` 为 C 候选数。
- 角色和状态：`private_control_scope`、`home_charging_access`、`home_ev_driver_member_id`、`role_card_short` 来自 B；`actor_card_full` 由 E 将 A/B/C 和原问卷标签重新组合，供人阅读，**不替代逐题原值**。`event_presence_status`、`participant_feedback_status`、`simulation_result_status`、`population_weight_status` 明示尚无的事项。

### `members_300.csv`：一成员一行，749 行

复合主键 `(role_id, member_id)`。`member_order` 是户内顺序；`relationship_to_reference_adult`、`partner_member_id`、`age_years_design`、`source_age_band`、`age_band` 来自 A 结构/ B 接口，具体年龄为约束合成。`life_role`、`routine`、`comfort`、`task_flexibility`、`participation`、`needs_priority`、`cost_importance_1_5`、`grid_importance_1_5`、`control` 是 B 的成员条件；本冻结版每位成员恰一个 `life_role`。`trait_basis`、`weekday_window_status`、`weekend_window_status` 标证据与作息可知性。没有姓名、手机号、身份证或真实个人属性。

### `member_links_300.csv` 与 `member_windows_300.csv`

`member_links_300.csv` 用 `(role_id, member_id, related_member_id, relationship_type)` 表示成员间 `parent`/`partner` 有向关系，`evidence_status` 为模板来源；所指成员均可在 `members_300.csv` 找到。

`member_windows_300.csv` 用 `(role_id, member_id, day_type, window_order)` 记录工作日/周末每个在家窗的 `start_local_time`、`end_local_time`；`time_status=SYNTHETIC_TYPICAL` 才有时钟。轮班成员各日型保留 `window_order=0`、`time_status=UNKNOWN` 且时钟为空。`basis` 说明生成规则。这是典型日模板，不是逐日记录。

### `devices_300.csv`：一户一类已纳入设备一行，734 行

复合主键 `(role_id, device)`。`owned_unit_count`、`weekly_frequency_code`、`control_scope`、`operation_condition` 记录拥有台数、原题频次档、实际可安排范围和需要当天确认的前提。`usual_start_code` 复用对应 `H_device`；`earliest_start_code`、`latest_end_code`、`task_duration_hours_internal`、`task_duration_minutes` 适用于洗衣/洗碗/烘干任务，其中 `latest_end_code` 也记录热水器加热结束和 EV 次日离家。`ac_mode`、`ac_custom_start_code`、`ac_custom_end_code`、`ac_temperature_c`、`ac_comfort_range_c`、`ac_acceptable_change_c` 仅适用于空调。`hot_water_need_time_code`、`preheat_choice` 仅适用于电热水器；`ev_target_soc_fraction`、`ev_reserve_soc_fraction`、`ev_driver_member_id` 仅适用于家充 EV。`device_data_status=SYNTHETIC_FIXED_PROFILE`。无某类设备的家庭**没有设备行**，但相关原题在问答表明确为 `not_applicable`。

### `zones_300.csv`：一个 C 原型热区一行

复合键 `(role_id, zone_name)`。`source_unit_zone`、`household_owned_zone`、`ac_candidate_zone`、`owned_but_unconditioned_zone` 为 0/1 的不同集合成员标记。`ac_device_assigned_status=NOT_ASSIGNED_BY_B` 表示 B 不决定实际空调装在哪个候选区；这不是关闭或开启记录。`building_idf_sha256` 防止跨版本合并。

### `question_answers_300.csv`：66 题逐户原值及条件适用性

一户一题至少一行；多选题每个选项一行，完整 300×66 个户题组合共 20,594 行。复合键 `(role_id, question_id, answer_index)`。`question_group`、`question_prompt`、`required_for_generation` 来自现行码本；`applicable`、`response_status`、`basis` 来自码本条件及 B 值。`value_kind` 为 `scalar`、`list_item`、`member_reference` 或 `none`；前两类的 `value_code` 是原码，`display_label` 是原码本中文标签。`M_MEMBERS` 对应成员表时写 `value_reference=members_300.csv`，不把成员数组塞单格。`semantic_status` 显式标 27 户 `X_AREA` 问题；`source_profile_sha256` 钉住 B 版本。`response_status=not_applicable` 是按跳题规则无值，不是漏填。

### `provenance_300.csv`：字段与来源的长表

每行 `(role_id, field_group, field_path, source_id)` 对应 A 家庭字段证据、B 问卷题来源、B 域证据或 C 原型绑定。`evidence_label` 保留生成器原标签；`source_scope` 限定它是边际配额、构念支持还是合成数值；`source_version` 是 A/B/C 文件哈希。来源 ID 的公开文献/原表解释见 `DATA_MANUFACTURING_PATH.md`、A 的 `SOURCE_EVIDENCE.md`、B 的 `SOURCES_AND_RULES.md`、C 的 `HANDOFF.md`。相同题可有多个来源 ID，故使用长表，不把列表放在一个单元格里。

## 生成与回读

在仓库根目录运行 `python3 docs/research/long-horizon-plan/execution/prelaunch_rigor_20260924/household_300_resolution_20260925/E_collection_release/export_profiles_csv.py` 重建，再加 `--verify` 可重新从冻结 A/B/C 算期望行并逐格回读 CSV。输入哈希不符时脚本直接停止。`audit_profile_semantics.py` 对 66 题、成员、卡片和合住面积口径做独立审计。
