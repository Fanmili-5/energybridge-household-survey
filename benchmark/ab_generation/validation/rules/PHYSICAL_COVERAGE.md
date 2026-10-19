# Tail coverage verification

| Stratum | Frame | Selected | Verified | Deficit | Pass |
| --- | ---: | ---: | ---: | ---: | --- |
| declared_EV_failure | 4 | 1 | 1 | 0 | True |
| static_conflict | 82 | 1 | 1 | 0 | True |
| A_equals_B_control | 4 | 1 | 1 | 0 | True |
| joint_all_supported | 253 | 1 | 1 | 0 | True |
| joint_mixed_support | 290 | 1 | 1 | 0 | True |
| washer_with_cost_tradeoff | 1 | 1 | 1 | 0 | True |
| dishwasher_supported | 13 | 1 | 1 | 0 | True |
| EV_supported | 12 | 1 | 1 | 0 | True |
| AC_supported | 16 | 1 | 1 | 0 | True |
| AC_exploratory_inactive_axis | 8 | 1 | 1 | 0 | True |
| tank_exploratory_up | 15 | 1 | 1 | 0 | True |
| tank_down | 8 | 1 | 1 | 0 | True |
| tank_state_supported_gap | 4 | 1 | 1 | 0 | True |
| winter_heating_gap | 0 | 0 | 0 | 1 | False |

Diagnostic rows verify static rejection only. All other rows require bound native readback.
Benefits, event success and human acceptance are not selection or ordinary admission conditions.
Marginal/pairwise coverage is measured over this finite catalogue; no complete covering-array or population claim.

## Per-target response coverage

Patterns: {'all_targeted_assets_change': 8, 'identical_control': 1, 'mixed_target_response': 1, 'no_target_response': 2}
Changed device kinds: {'ev': 4, 'dishwasher': 2, 'dryer': 1, 'washer': 1, 'ac': 1, 'water_heater': 2}
Missing required kinds: []
Screen-supported targets without observed response: 0.0
All samples, including ineffective and failed requests, remain in RESULT.json. No replacement.
