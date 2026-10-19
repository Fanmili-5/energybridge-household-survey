# 最终样本的交互覆盖与缺项

数据直接来自封存的 `final_sample/RESULT.json`。这是目录中可用的因素水平组合覆盖，不是新的配额或新的取样。203个缺项不触发补抽。

| 轴 | 可用水平组合 | 覆盖 | 缺项 |
|---|---:|---:|---:|
| admission | 2 | 2 | 0 |
| axis | 5 | 4 | 1 |
| cost_sign | 4 | 4 | 0 |
| direction | 4 | 3 | 1 |
| family | 7 | 4 | 3 |
| handling | 4 | 3 | 1 |
| opportunity | 3 | 3 | 0 |
| same_family_jobs | 2 | 2 | 0 |
| unit_count | 7 | 4 | 3 |
| admission × axis | 10 | 5 | 5 |
| admission × cost_sign | 8 | 5 | 3 |
| admission × direction | 8 | 4 | 4 |
| admission × handling | 5 | 4 | 1 |
| admission × opportunity | 5 | 4 | 1 |
| axis × direction | 9 | 5 | 4 |
| axis × handling | 20 | 6 | 14 |
| cost_sign × axis | 7 | 6 | 1 |
| cost_sign × direction | 6 | 5 | 1 |
| cost_sign × handling | 15 | 6 | 9 |
| direction × handling | 16 | 6 | 10 |
| family × admission | 10 | 5 | 5 |
| family × axis | 12 | 6 | 6 |
| family × cost_sign | 13 | 7 | 6 |
| family × direction | 12 | 6 | 6 |
| family × handling | 12 | 5 | 7 |
| family × opportunity | 10 | 6 | 4 |
| family × same_family_jobs | 8 | 5 | 3 |
| family × unit_count | 11 | 5 | 6 |
| opportunity × axis | 9 | 5 | 4 |
| opportunity × cost_sign | 6 | 5 | 1 |
| opportunity × direction | 8 | 5 | 3 |
| opportunity × handling | 9 | 6 | 3 |
| same_family_jobs × admission | 4 | 4 | 0 |
| same_family_jobs × axis | 7 | 5 | 2 |
| same_family_jobs × cost_sign | 7 | 6 | 1 |
| same_family_jobs × direction | 6 | 4 | 2 |
| same_family_jobs × handling | 7 | 4 | 3 |
| same_family_jobs × opportunity | 5 | 4 | 1 |
| unit_count × admission | 13 | 5 | 8 |
| unit_count × axis | 23 | 6 | 17 |
| unit_count × cost_sign | 17 | 7 | 10 |
| unit_count × direction | 21 | 6 | 15 |
| unit_count × handling | 21 | 6 | 15 |
| unit_count × opportunity | 12 | 5 | 7 |
| unit_count × same_family_jobs | 11 | 5 | 6 |

## 203个未覆盖的具体水平组合

| 轴 | 水平（同列顺序） | 可用去重请求数 | 抽中 |
|---|---|---:|---:|
| family | dishwasher | 144 | 0 |
| family | ev | 9 | 0 |
| family | water_heater | 22 | 0 |
| unit_count | 4 | 184 | 0 |
| unit_count | 5 | 56 | 0 |
| unit_count | 6 | 8 | 0 |
| axis | mixed | 468 | 0 |
| direction | mixed | 278 | 0 |
| handling | timer_only | 5433 | 0 |
| family × unit_count | dishwasher × 1 | 144 | 0 |
| family × unit_count | ev × 1 | 9 | 0 |
| family × unit_count | joint × 4 | 184 | 0 |
| family × unit_count | joint × 5 | 56 | 0 |
| family × unit_count | joint × 6 | 8 | 0 |
| family × unit_count | water_heater × 1 | 22 | 0 |
| family × same_family_jobs | dishwasher × no | 144 | 0 |
| family × same_family_jobs | ev × no | 9 | 0 |
| family × same_family_jobs | water_heater × no | 22 | 0 |
| family × admission | dishwasher × normal | 28 | 0 |
| family × admission | dishwasher × static_diagnostic | 116 | 0 |
| family × admission | ev × normal | 9 | 0 |
| family × admission | washer × static_diagnostic | 184 | 0 |
| family × admission | water_heater × normal | 22 | 0 |
| family × opportunity | dishwasher × supported | 144 | 0 |
| family × opportunity | ev × supported | 9 | 0 |
| family × opportunity | water_heater × exploratory | 16 | 0 |
| family × opportunity | water_heater × supported | 6 | 0 |
| family × cost_sign | dishwasher × positive | 114 | 0 |
| family × cost_sign | dishwasher × zero | 30 | 0 |
| family × cost_sign | ev × negative | 6 | 0 |
| family × cost_sign | ev × zero | 3 | 0 |
| family × cost_sign | joint × zero | 62 | 0 |
| family × cost_sign | water_heater × unknown | 22 | 0 |
| family × axis | dishwasher × not_thermal | 144 | 0 |
| family × axis | ev × not_thermal | 9 | 0 |
| family × axis | joint × cooling | 428 | 0 |
| family × axis | joint × heating | 1022 | 0 |
| family × axis | joint × mixed | 468 | 0 |
| family × axis | water_heater × tank | 22 | 0 |
| family × direction | dishwasher × not_thermal | 144 | 0 |
| family × direction | ev × not_thermal | 9 | 0 |
| family × direction | joint × aligned | 1484 | 0 |
| family × direction | joint × mixed | 278 | 0 |
| family × direction | water_heater × aligned | 8 | 0 |
| family × direction | water_heater × opposing | 14 | 0 |
| family × handling | dishwasher × shift_chain | 72 | 0 |
| family × handling | dishwasher × timer_only | 72 | 0 |
| family × handling | ev × not_program | 9 | 0 |
| family × handling | joint × not_program | 384 | 0 |
| family × handling | joint × timer_only | 5265 | 0 |
| family × handling | washer × timer_only | 96 | 0 |
| family × handling | water_heater × not_program | 22 | 0 |
| unit_count × same_family_jobs | 3 × yes | 24 | 0 |
| unit_count × same_family_jobs | 4 × no | 160 | 0 |
| unit_count × same_family_jobs | 4 × yes | 24 | 0 |
| unit_count × same_family_jobs | 5 × no | 48 | 0 |
| unit_count × same_family_jobs | 5 × yes | 8 | 0 |
| unit_count × same_family_jobs | 6 × no | 8 | 0 |
| unit_count × admission | 1 × static_diagnostic | 300 | 0 |
| unit_count × admission | 3 × static_diagnostic | 320 | 0 |
| unit_count × admission | 4 × normal | 94 | 0 |
| unit_count × admission | 4 × static_diagnostic | 90 | 0 |
| unit_count × admission | 5 × normal | 27 | 0 |
| unit_count × admission | 5 × static_diagnostic | 29 | 0 |
| unit_count × admission | 6 × normal | 4 | 0 |
| unit_count × admission | 6 × static_diagnostic | 4 | 0 |
| unit_count × opportunity | 2 × exploratory | 2558 | 0 |
| unit_count × opportunity | 3 × supported | 299 | 0 |
| unit_count × opportunity | 4 × exploratory | 144 | 0 |
| unit_count × opportunity | 4 × supported | 40 | 0 |
| unit_count × opportunity | 5 × exploratory | 50 | 0 |
| unit_count × opportunity | 5 × supported | 6 | 0 |
| unit_count × opportunity | 6 × exploratory | 8 | 0 |
| unit_count × cost_sign | 1 × zero | 33 | 0 |
| unit_count × cost_sign | 2 × unknown | 3992 | 0 |
| unit_count × cost_sign | 2 × zero | 62 | 0 |
| unit_count × cost_sign | 3 × negative | 175 | 0 |
| unit_count × cost_sign | 3 × positive | 64 | 0 |
| unit_count × cost_sign | 4 × negative | 5 | 0 |
| unit_count × cost_sign | 4 × positive | 3 | 0 |
| unit_count × cost_sign | 4 × unknown | 176 | 0 |
| unit_count × cost_sign | 5 × unknown | 56 | 0 |
| unit_count × cost_sign | 6 × unknown | 8 | 0 |
| unit_count × axis | 1 × tank | 22 | 0 |
| unit_count × axis | 2 × cooling | 396 | 0 |
| unit_count × axis | 2 × heating | 990 | 0 |
| unit_count × axis | 2 × mixed | 236 | 0 |
| unit_count × axis | 2 × tank | 2370 | 0 |
| unit_count × axis | 3 × cooling | 24 | 0 |
| unit_count × axis | 3 × heating | 24 | 0 |
| unit_count × axis | 3 × mixed | 80 | 0 |
| unit_count × axis | 3 × not_thermal | 239 | 0 |
| unit_count × axis | 4 × cooling | 8 | 0 |
| unit_count × axis | 4 × heating | 8 | 0 |
| unit_count × axis | 4 × mixed | 96 | 0 |
| unit_count × axis | 4 × not_thermal | 8 | 0 |
| unit_count × axis | 4 × tank | 64 | 0 |
| unit_count × axis | 5 × mixed | 48 | 0 |
| unit_count × axis | 5 × tank | 8 | 0 |
| unit_count × axis | 6 × mixed | 8 | 0 |
| unit_count × direction | 2 × aligned | 1434 | 0 |
| unit_count × direction | 2 × mixed | 124 | 0 |
| unit_count × direction | 2 × opposing | 2434 | 0 |
| unit_count × direction | 3 × aligned | 33 | 0 |
| unit_count × direction | 3 × mixed | 49 | 0 |
| unit_count × direction | 3 × not_thermal | 239 | 0 |
| unit_count × direction | 4 × aligned | 15 | 0 |
| unit_count × direction | 4 × mixed | 63 | 0 |
| unit_count × direction | 4 × not_thermal | 8 | 0 |
| unit_count × direction | 4 × opposing | 98 | 0 |
| unit_count × direction | 5 × aligned | 2 | 0 |
| unit_count × direction | 5 × mixed | 35 | 0 |
| unit_count × direction | 5 × opposing | 19 | 0 |
| unit_count × direction | 6 × mixed | 7 | 0 |
| unit_count × direction | 6 × opposing | 1 | 0 |
| unit_count × handling | 1 × timer_only | 168 | 0 |
| unit_count × handling | 2 × not_program | 344 | 0 |
| unit_count × handling | 2 × timer_only | 5208 | 0 |
| unit_count × handling | 3 × mixed | 148 | 0 |
| unit_count × handling | 3 × not_program | 32 | 0 |
| unit_count × handling | 3 × timer_only | 36 | 0 |
| unit_count × handling | 4 × mixed | 51 | 0 |
| unit_count × handling | 4 × not_program | 8 | 0 |
| unit_count × handling | 4 × shift_chain | 108 | 0 |
| unit_count × handling | 4 × timer_only | 17 | 0 |
| unit_count × handling | 5 × mixed | 22 | 0 |
| unit_count × handling | 5 × shift_chain | 30 | 0 |
| unit_count × handling | 5 × timer_only | 4 | 0 |
| unit_count × handling | 6 × mixed | 4 | 0 |
| unit_count × handling | 6 × shift_chain | 4 | 0 |
| same_family_jobs × opportunity | yes × exploratory | 32 | 0 |
| same_family_jobs × cost_sign | yes × unknown | 32 | 0 |
| same_family_jobs × axis | no × mixed | 468 | 0 |
| same_family_jobs × axis | yes × tank | 32 | 0 |
| same_family_jobs × direction | no × mixed | 278 | 0 |
| same_family_jobs × direction | yes × opposing | 32 | 0 |
| same_family_jobs × handling | no × timer_only | 4854 | 0 |
| same_family_jobs × handling | yes × mixed | 1191 | 0 |
| same_family_jobs × handling | yes × timer_only | 579 | 0 |
| admission × opportunity | static_diagnostic × exploratory | 2202 | 0 |
| admission × cost_sign | static_diagnostic × negative | 2502 | 0 |
| admission × cost_sign | static_diagnostic × unknown | 3398 | 0 |
| admission × cost_sign | static_diagnostic × zero | 72 | 0 |
| admission × axis | normal × mixed | 396 | 0 |
| admission × axis | static_diagnostic × cooling | 345 | 0 |
| admission × axis | static_diagnostic × heating | 843 | 0 |
| admission × axis | static_diagnostic × mixed | 72 | 0 |
| admission × axis | static_diagnostic × tank | 2138 | 0 |
| admission × direction | normal × mixed | 224 | 0 |
| admission × direction | static_diagnostic × aligned | 1185 | 0 |
| admission × direction | static_diagnostic × mixed | 54 | 0 |
| admission × direction | static_diagnostic × opposing | 2159 | 0 |
| admission × handling | static_diagnostic × timer_only | 5433 | 0 |
| opportunity × cost_sign | supported × zero | 95 | 0 |
| opportunity × axis | exploratory × heating | 200 | 0 |
| opportunity × axis | exploratory × mixed | 378 | 0 |
| opportunity × axis | supported × mixed | 90 | 0 |
| opportunity × axis | supported × tank | 624 | 0 |
| opportunity × direction | exploratory × aligned | 643 | 0 |
| opportunity × direction | exploratory × mixed | 226 | 0 |
| opportunity × direction | supported × mixed | 52 | 0 |
| opportunity × handling | exploratory × mixed | 78 | 0 |
| opportunity × handling | exploratory × timer_only | 1195 | 0 |
| opportunity × handling | supported × timer_only | 4238 | 0 |
| cost_sign × axis | unknown × mixed | 468 | 0 |
| cost_sign × direction | unknown × mixed | 278 | 0 |
| cost_sign × handling | negative × mixed | 918 | 0 |
| cost_sign × handling | negative × not_program | 6 | 0 |
| cost_sign × handling | negative × timer_only | 819 | 0 |
| cost_sign × handling | positive × timer_only | 2696 | 0 |
| cost_sign × handling | unknown × mixed | 98 | 0 |
| cost_sign × handling | unknown × timer_only | 1880 | 0 |
| cost_sign × handling | zero × mixed | 16 | 0 |
| cost_sign × handling | zero × shift_chain | 38 | 0 |
| cost_sign × handling | zero × timer_only | 38 | 0 |
| axis × direction | mixed × aligned | 62 | 0 |
| axis × direction | mixed × mixed | 278 | 0 |
| axis × direction | mixed × opposing | 128 | 0 |
| axis × direction | tank × aligned | 820 | 0 |
| axis × handling | cooling × mixed | 8 | 0 |
| axis × handling | cooling × shift_chain | 212 | 0 |
| axis × handling | cooling × timer_only | 196 | 0 |
| axis × handling | heating × mixed | 8 | 0 |
| axis × handling | heating × shift_chain | 500 | 0 |
| axis × handling | heating × timer_only | 484 | 0 |
| axis × handling | mixed × mixed | 32 | 0 |
| axis × handling | mixed × not_program | 276 | 0 |
| axis × handling | mixed × shift_chain | 128 | 0 |
| axis × handling | mixed × timer_only | 32 | 0 |
| axis × handling | not_thermal × timer_only | 3553 | 0 |
| axis × handling | tank × mixed | 50 | 0 |
| axis × handling | tank × not_program | 88 | 0 |
| axis × handling | tank × timer_only | 1168 | 0 |
| direction × handling | aligned × mixed | 12 | 0 |
| direction × handling | aligned × shift_chain | 701 | 0 |
| direction × handling | aligned × timer_only | 679 | 0 |
| direction × handling | mixed × mixed | 24 | 0 |
| direction × handling | mixed × not_program | 152 | 0 |
| direction × handling | mixed × shift_chain | 78 | 0 |
| direction × handling | mixed × timer_only | 24 | 0 |
| direction × handling | not_thermal × timer_only | 3553 | 0 |
| direction × handling | opposing × mixed | 62 | 0 |
| direction × handling | opposing × timer_only | 1177 | 0 |
