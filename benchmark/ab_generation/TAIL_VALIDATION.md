# 第二条线长尾覆盖验证（2026-10-19）

最终原始结果逐字节发布为 [TAIL_VALIDATION.json](TAIL_VALIDATION.json)。候选目录、全部别名、所选样本、覆盖表和回执见 [validation/tail](validation/tail/)。源代码哈希为 `7eaa6e78bbf1c4df07f42718c944269d224721236d403daef5f511cde5489c2f`，计划与参考输入哈希见 `SOURCE_RECEIPTS.json`。

已独立用Python3.9重建固定A下的20条入样命令及分层，与Python3.14最终运行一致；公开A目录转为明文JSON时逐项核对4个上下文内容不变，转换记录随包公开。

## 范围与结果

使用3个公开合成家庭、4个冻结实验上下文，复用已经通过审查的完整A参考。1052条来源记录按实际命令归并为621个独立实验请求。最终选20条：19条执行A/B（38次引擎运行），1条静态冲突只验证拒绝、不执行。19个必验层均满足；可选冬季制热层缺1条，如实保留。另用2次引擎运行验证原策略审查的联合探针，适配全组合枚举后仍通过。

18条普通/控制请求完成物理与服务审查；1条预设EV压力请求仅检出 `B_EV_departure_target`，没有能量闭合或A复现错误；1条静态冲突保持非执行诊断。全部19组配对A对完整参考轨迹的通道、单位和时间轴一致，最大绝对差为0。人的接受与满意度仍未知。

实际保留费用增加10条、费用不变3条、费用减少6条；事件未达标16条，其中反向实际响应4条。预设EV失败虽主区间费用下降，仍单独标为服务失败，不能算普通可交付灵活性。命令不同但物理读回相同的两档热控制继续分别记录，不能按结果相同删除处理条件。

以下列出全部所选结果。费用是声明的合成CNY电价下整栋主24小时电表费用差，不包含补偿，也不代表净福利或真实家庭账单；事件达标不是普通样本准入条件。

| Stratum | Case | 24h cost B-A (CNY) | Aligned response kW / target met | Status |
| --- | --- | ---: | --- | --- |
| declared_EV_shortfall | declared-wide-device-probe | -4.764611 | +0.321759 / False | declared_service_failure_observed |
| static_conflict_diagnostic | example-family-life-20250715 | not executed | not executed | static_failure_retained_nonexecuting |
| A_equals_B_control | example-studio-life-20250715 | +0.000000 | -0.000000 / False | executed_valid |
| joint_tradeoffs | example-studio-life-20250715 | +0.061421 | -0.152338 / False | executed_valid |
| joint_tradeoffs | example-family-life-20250715 | -2.755556 | +7.000000 / True | executed_valid |
| washer_cost_increase | example-family-life-20250715 | +0.081820 | +0.416667 / False | executed_valid |
| dishwasher_30min | example-family-life-20250715 | +0.000665 | -0.000000 / False | executed_valid |
| dishwasher_60min | example-studio-life-20250715 | +0.057794 | -0.000000 / False | executed_valid |
| dishwasher_120min | example-shared-life-20250715 | +0.206895 | -0.000000 / False | executed_valid |
| EV_30min | declared-wide-device-probe | +0.000000 | -0.000000 / False | executed_valid |
| EV_60min | example-studio-life-20250715 | -0.585556 | +7.000000 / True | executed_valid |
| EV_120min | example-family-life-20250715 | -2.755556 | +7.000000 / True | executed_valid |
| ac_aligned_thermal_0.5C | declared-wide-device-probe | -0.015258 | +0.000936 / False | executed_valid |
| ac_aligned_thermal_1C | declared-wide-device-probe | -0.066763 | +0.004315 / False | executed_valid |
| ac_opposing_thermal_0.5C | declared-wide-device-probe | +0.029990 | -0.001957 / False | executed_valid |
| ac_opposing_thermal_1C | example-studio-life-20250715 | +0.014427 | -0.045716 / False | executed_valid |
| water_heater_aligned_thermal_0.5C | declared-wide-device-probe | +0.054667 | +0.001733 / False | executed_valid |
| water_heater_aligned_thermal_1C | declared-wide-device-probe | +0.054667 | +0.001733 / False | executed_valid |
| water_heater_opposing_thermal_0.5C | example-shared-life-20250715 | +0.000000 | -0.000000 / False | executed_valid |
| water_heater_opposing_thermal_1C | example-family-life-20250715 | +0.121784 | -0.327327 / False | executed_valid |

## 覆盖表

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

静态诊断列的验收只证明拒绝规则成立，不能当作物理执行完成。费用、事件成功和人的接受均不参与抽样或普通样本准入。

## 尚未验证的范围

有限目录的单因素组合命中39/51，二因素组合命中200/317。这是所选命令的覆盖测量，含明确标记的静态诊断；不等于对应组合全部通过物理验证。所有零命中组合均在 `SELECTION.json` 中列出，没有宣称完整二阶覆盖数组。

当前仍缺冬季分层样本、更多家庭/日型与种子、完整联合设备组合及剂量×时长交互；三设备以上与连续控制空间不在当前目录。参数敏感性、真实长尾发生率、家庭偏好、人类理解和接受度、实时预测表现均未由本次验证。下一步优先扩展小型冬季/日型与约束交互基准，1000户仿真仍暂停。

## 开发试跑、依据与复现

开发试跑另有24次引擎运行。第二轮36次因必验“洗碗机30分钟且预测费用增加”无候选而未通过覆盖，物理执行结果均保留。检查有限目录发现该档预测费用为零，于是在最终独立运行前移除洗碗机各移时层的费用正号条件，保留独立费用符号统计和洗衣费用增加层；种子没有变。最终覆盖通过不能覆盖这轮失败记录，见 `validation/tail/development/`。这些是探索性的工程设计迭代，没有声称实证预注册。最终结果、两轮开发试跑及联合回归合计100次引擎运行，均限于3个公开合成家庭。

科研与算法依据、人工参数和授权边界见 [TAIL_METHOD.md](TAIL_METHOD.md)、[PARAMETERS.json](PARAMETERS.json)、[AUTHORIZATION.json](AUTHORIZATION.json)。分层/多阶段取样依据来自加拿大统计局，覆盖测量依据来自NIST SP800-142及IR7878；具体配额、扰动档位与失败规则是本项目设定。科研审查流程引用Kassis等 Scientific Agent Skills（已核查当前版本），不作为物理有效性证据。

复现命令见 [REPRODUCE.md](REPRODUCE.md)。96项A/B单元测试分别在Python3.9.6和3.14.3通过，52项住房物理接口测试通过。CI以官方Linux EnergyPlus24.1重跑公共基线、长尾和冬季边界。线上问卷、既有答卷与设备实控均未修改。
