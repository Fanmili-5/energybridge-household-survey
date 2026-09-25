# A → B/C：家庭结构字段契约（2026-09-25）

交付 `family_300.json`，`records` 为 300 个 `role_id=cityrole-0001..0300`。身份、城市、省份、家庭人数、代际及七普 H7 房间配额保持冻结。B/C 按 `role_id` 关联，不用姓名、城市或建筑原型反推身份。

每户 `members[]` 给出 `age_years_design`、`source_age_band`、与参考成人的关系，并通过 `parent_member_ids[]` 和 `partner_member_id` 明确在户亲子/配偶链接。全部链接已按至少 18 岁亲子年龄差、配偶年龄接近和对称链接逐条检查；精确年龄与关系补全仍是可扮演的实验合成，不是同户调查观测。B 可据此编制日程和条件题。

`dwelling.room_count_census_h7_category` 为七普 H7 间数：排除厨房、厕所、过道和厅；`five_or_more_rooms` 只知至少 5 间。它不是卧室数，也不直接等于 EnergyPlus Zone 数。`room_count_design_minimum` 仅为保守下限。

`dwelling.per_capita_building_area_census_h6_bin_m2` 是七普 H6 分箱的省级校准配额；具体分配到该户为实验联合配对。`dwelling.design_total_building_area_m2` 是分箱中点（两端开区间按明确设计点）的 **H6 类本户建筑面积目标**，不是实测房产面积、CHNS 使用面积、净可用面积或 IDF 净热区面积。`dwelling.observed_dwelling_area_m2=null`。A 不生成全国统一的建筑/可用面积换算因子。

面积低于 30㎡ 的 27 户明确设为 `housing_form_design=shared_dwelling_private_rooms_with_allocated_common_area`：本户独立使用 H7 房间，面积为房间与公共空间分摊后的本户建筑面积，`area_basis=synthetic_H6_like_household_attributed_building_area_in_shared_dwelling`；物理**整套合住房屋**面积未知，`physical_whole_dwelling_building_area_m2=null`。B 请在卡片标明合住及独用房间数；C 请为其建模本户可用部分与共用空间分摊，或明确无法模拟的案例，不要把 8/16㎡ 当作整套独立住房面积。

其余 273 户设为 `housing_form_design=independent_dwelling`，`physical_whole_dwelling_building_area_m2=design_total_building_area_m2`，口径是实验整套建筑面积目标。C 请自行核 DeST 原型的几何面积口径，再建立独立的物理目标及缩放/敏感性，勿把 H6 数值直接命名为热区面积。当前最大 322.5㎡。

`cityrole-0024 ↔ cityrole-0267`、`cityrole-0140 ↔ cityrole-0089` 对调 H7 房间类别，解决 4/5 人单房间在 CHNS 局部样本中无足够同户格的问题；两对均位于同省×代际层，房间配额不变。四户换房间**之后**，A 从 CHNS 原始文件重算新人数×房间条件格的秩，再执行面积约束分配；新格样本量分别为 17、56、52、69。每户 `previous_census_h7_room_category` 保留旧值，详情见 `distribution_and_anomalies.json` 的 `rank_recomputations_after_room_repairs`。

`review_flags` 是需要明确呈现的稀有/极端设计情境，不等于错误；A 的分布报告列出逐户处置。面积配对采用 CHNS 2015 条件相对秩，不使用 L16×1.33 来分配数值。
