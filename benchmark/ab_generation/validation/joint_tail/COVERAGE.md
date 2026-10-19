# 新联合目录的正式长尾覆盖

| 分层 | 必验 | 独占目录 | 要求 | 抽中 | 验证 | 缺额 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| capacity_bound_stress | True | 116 | 1 | 1 | 1 | 0 |
| capacity_known_overload_gap | False | 15 | 1 | 1 | 1 | 0 |
| EV_departure_shortfall_stress | True | 7 | 1 | 1 | 1 | 0 |
| same_family_jobs_static_diagnostic | True | 232 | 1 | 1 | 1 | 0 |
| other_static_diagnostic | True | 7434 | 1 | 1 | 1 | 0 |
| A_equals_B_control | True | 8 | 1 | 1 | 1 | 0 |
| joint_6_units | True | 1 | 1 | 1 | 1 | 0 |
| joint_5_units | True | 66 | 1 | 1 | 1 | 0 |
| joint_4_units | True | 167 | 1 | 1 | 1 | 0 |
| joint_3_units | True | 194 | 1 | 1 | 1 | 0 |
| same_family_jobs_executable_gap | False | 0 | 1 | 0 | 0 | 1 |
| joint_2_units_mixed_support | True | 512 | 1 | 1 | 1 | 0 |
| joint_2_units_all_supported | True | 343 | 1 | 1 | 1 | 0 |
| washer_cost_increase | True | 0 | 1 | 0 | 0 | 1 |
| dishwasher_supported | True | 22 | 1 | 1 | 1 | 0 |
| ev_supported | True | 21 | 1 | 1 | 1 | 0 |
| AC_cooling_supported | True | 16 | 1 | 1 | 1 | 0 |
| AC_inactive_heating_exploratory | True | 8 | 1 | 1 | 1 | 0 |
| tank_supported_gap | False | 10 | 1 | 1 | 1 | 0 |
| tank_opposing_exploratory | True | 28 | 1 | 1 | 1 | 0 |
| tank_aligned | True | 8 | 1 | 1 | 1 | 0 |
| winter_heating_supported_gap | False | 0 | 1 | 0 | 0 | 1 |

必验合同通过：False
全部声明层覆盖：False
结果分类：{'capacity_stress_executed_without_overload': 1, 'capacity_service_failure_retained': 1, 'declared_service_failure_observed': 1, 'static_failure_retained_nonexecuting': 2, 'executed_valid': 14}
响应分类：{'all_targeted_assets_change': 13, 'mixed_target_response': 1, 'identical_control': 1, 'no_target_response': 2}
诊断层只验证静态拒绝；物理层须有完整读回。所有无效、无响应、服务失败和缺额原样保留，未重抽。
完整单因素及两因素抽样覆盖表见 RESULT.json；高阶剂量并非全部穷举，非人口代表性证明。
