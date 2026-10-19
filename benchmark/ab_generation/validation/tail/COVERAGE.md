# Tail coverage verification

| Stratum | Frame | Selected | Verified | Deficit | Pass |
| --- | ---: | ---: | ---: | ---: | --- |
| declared_EV_shortfall | 4 | 1 | 1 | 0 | True |
| static_conflict_diagnostic | 82 | 1 | 1 | 0 | True |
| A_equals_B_control | 4 | 1 | 1 | 0 | True |
| joint_tradeoffs | 461 | 2 | 2 | 0 | True |
| washer_cost_increase | 1 | 1 | 1 | 0 | True |
| dishwasher_30min | 4 | 1 | 1 | 0 | True |
| dishwasher_60min | 4 | 1 | 1 | 0 | True |
| dishwasher_120min | 4 | 1 | 1 | 0 | True |
| EV_30min | 4 | 1 | 1 | 0 | True |
| EV_60min | 4 | 1 | 1 | 0 | True |
| EV_120min | 4 | 1 | 1 | 0 | True |
| ac_aligned_thermal_0.5C | 4 | 1 | 1 | 0 | True |
| ac_aligned_thermal_1C | 4 | 1 | 1 | 0 | True |
| ac_opposing_thermal_0.5C | 4 | 1 | 1 | 0 | True |
| ac_opposing_thermal_1C | 4 | 1 | 1 | 0 | True |
| water_heater_aligned_thermal_0.5C | 2 | 1 | 1 | 0 | True |
| water_heater_aligned_thermal_1C | 2 | 1 | 1 | 0 | True |
| water_heater_opposing_thermal_0.5C | 8 | 1 | 1 | 0 | True |
| water_heater_opposing_thermal_1C | 8 | 1 | 1 | 0 | True |
| winter_heating_aligned_gap | 0 | 0 | 0 | 1 | False |

Diagnostic rows verify static rejection only. All other rows require bound native readback.
Benefits, event success and human acceptance are not selection or ordinary admission conditions.
Marginal/pairwise coverage is measured over this finite catalogue; no complete covering-array or population claim.
