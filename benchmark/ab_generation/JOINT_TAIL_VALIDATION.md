# 新联合目录正式长尾验收结果

**18个必验层中17个通过，完整覆盖验收未通过。** 必验缺失为“洗衣费用增加”；另有同族多批可执行联合、冬季制热有依据两个监测缺额。没有改层、配额、种子或重抽来消除缺额。代码和数据完整性检查通过，不等于覆盖合同通过，也不表示可直接发布训练集或上线问卷。

本轮生成和执行代码在首次正式B之前固定于 `283d3ee`，事前计划为 `examples/joint_tail/plan.json`。先前 `876a369` 的32臂集成研究另见 `JOINT_LOAD_SUPPLY_VALIDATION.md`，不混作本轮取样。论文、算法与人工参数采用边界见 [JOINT_TAIL_METHOD.md](JOINT_TAIL_METHOD.md)。

## 目录和实际样本

- 3个公开合成家庭、8个A情境，普通/EV压力共16份生成回执；不是8户实测家庭。
- 去重目录9,275条，原候选来源13,844个；来源别名保留。
- 静态诊断7,666条、正常候选1,471条、显式供电压力131条、EV不足压力7条。
- 22个声明层共抽中19条：2条静态诊断不执行，17组A/B完成34个引擎臂。所有已选样本有去向，完整读回及A复现通过，无引擎/数据隔离错误。

## 分层覆盖和缺额

| 分层ID | 必验 | 匹配 | 独占目录 | 要求 | 抽中 | 验证 | 缺额 |
|---|---|---:|---:|---:|---:|---:|---:|
| capacity_bound_stress | True | 116 | 116 | 1 | 1 | 1 | 0 |
| capacity_known_overload_gap | False | 15 | 15 | 1 | 1 | 1 | 0 |
| EV_departure_shortfall_stress | True | 7 | 7 | 1 | 1 | 1 | 0 |
| same_family_jobs_static_diagnostic | True | 232 | 232 | 1 | 1 | 1 | 0 |
| other_static_diagnostic | True | 7666 | 7434 | 1 | 1 | 1 | 0 |
| A_equals_B_control | True | 8 | 8 | 1 | 1 | 1 | 0 |
| joint_6_units | True | 1 | 1 | 1 | 1 | 1 | 0 |
| joint_5_units | True | 66 | 66 | 1 | 1 | 1 | 0 |
| joint_4_units | True | 167 | 167 | 1 | 1 | 1 | 0 |
| joint_3_units | True | 194 | 194 | 1 | 1 | 1 | 0 |
| same_family_jobs_executable_gap | False | 0 | 0 | 1 | 0 | 0 | 1 |
| joint_2_units_mixed_support | True | 512 | 512 | 1 | 1 | 1 | 0 |
| joint_2_units_all_supported | True | 343 | 343 | 1 | 1 | 1 | 0 |
| washer_cost_increase | True | 0 | 0 | 1 | 0 | 0 | 1 |
| dishwasher_supported | True | 22 | 22 | 1 | 1 | 1 | 0 |
| ev_supported | True | 21 | 21 | 1 | 1 | 1 | 0 |
| AC_cooling_supported | True | 16 | 16 | 1 | 1 | 1 | 0 |
| AC_inactive_heating_exploratory | True | 8 | 8 | 1 | 1 | 1 | 0 |
| tank_supported_gap | False | 10 | 10 | 1 | 1 | 1 | 0 |
| tank_opposing_exploratory | True | 28 | 28 | 1 | 1 | 1 | 0 |
| tank_aligned | True | 14 | 8 | 1 | 1 | 1 | 0 |
| winter_heating_supported_gap | False | 0 | 0 | 1 | 0 | 0 | 1 |

静态诊断层的“验证”只表示正确拒绝，不是物理执行信用。匹配与独占数分别报告；不能将首次匹配独占造成的减少冒充没有该类候选。供电上界未认证与已知剖面超限分开，均不直接写成已发生的物理失败。

洗衣费用增加层匹配数为0，缺额来自当前输入、功率模型及剂量目录，不是随机取样漏抽。不能因为其他B实际电费增加，就事后填入这个事前定义的层。下一版本可预先声明额外价格/生活情境再生成，仍须保留本次失败回执。

同族多批诊断存在，但正常可执行联合匹配数为0；诊断不能替代可执行覆盖。冬季制热机会在本夏季情境中缺失，没有移动日历或事件来填层。

## 实际后果全部保留

- 13组全部目标有变化、1组混合响应、2组无目标响应、1组A=B对照。
- 保留1个供电超限和1个EV出发目标不足的服务失败。另一个供电上界压力执行后没有超限，也保留，没有另换失败B。
- 无响应、混合响应和服务失败未被删除重选。失败和响应类别可重叠，不能相加当作独立样本总数。
- 有依据目标出现28次，无响应0次；六类设备均有变化实例。出现次数不是独立家庭或电器数，不能估计总体无效率。
- 实际导出B哈希等于冻结选择；执行前后选择文件SHA相同。逐批核对了原任务身份、批次能量、程序和完整时长未被改变。

“物理失败”在这里是模型违反声明服务要求，不是引擎崩溃或现实设备损坏。全户功率审查也不是浪涌、断路器或电气规范认证。人的接受、满意度及真实许可未被推断。

## 生成覆盖和未穷尽空间

| A情境 | 规则变体 | 单位数 | 生成联合数 | 两单位剂量覆盖/要求 | 生成覆盖通过 |
|---|---|---:|---:|---:|---|
| family_base | ordinary_unrestricted_joint | 4 | 364 | 324/324 | True |
| family_base | EV_shortfall_boundary | 4 | 391 | 268/268 | True |
| family_light | ordinary_unrestricted_joint | 4 | 364 | 324/324 | True |
| family_light | EV_shortfall_boundary | 4 | 391 | 268/268 | True |
| family_heavy | ordinary_unrestricted_joint | 4 | 364 | 324/324 | True |
| family_heavy | EV_shortfall_boundary | 4 | 391 | 268/268 | True |
| family_multibatch | ordinary_unrestricted_joint | 5 | 918 | 696/696 | True |
| family_multibatch | EV_shortfall_boundary | 5 | 844 | 616/616 | True |
| studio_wide | ordinary_unrestricted_joint | 6 | 2040 | 1118/1118 | True |
| studio_wide | EV_shortfall_boundary | 6 | 2082 | 1018/1018 | True |
| shared_base | ordinary_unrestricted_joint | 4 | 458 | 324/324 | True |
| shared_base | EV_shortfall_boundary | 4 | 408 | 268/268 | True |
| family_tight_supply | ordinary_unrestricted_joint | 4 | 471 | 324/324 | True |
| family_tight_supply | EV_shortfall_boundary | 4 | 406 | 268/268 | True |
| studio_warm | ordinary_unrestricted_joint | 6 | 1563 | 1040/1040 | True |
| studio_warm | EV_shortfall_boundary | 6 | 1785 | 944/944 | True |

16份回执的声明两单位剂量、任务数及族组合覆盖通过，不表示物理后果或人群覆盖完整。抽样单因素/两因素表共 1802 格，其中 928 格未选中，全部见 `validation/joint_tail/INTERACTIONS.json`。高阶完整剂量、连续参数、重叠多事件、人口分布和人类理解均未穷尽或验证。

联合设备的可观察变化可包含设备间耦合，不是每个子命令独立因果效应的证明。连续效应量保留，不以数值非零保证人能感知。原生轨迹重复只报告，没有据此删除重抽。

## 自查和复现

- Python3.9.6下146项A/B检查通过；Python3.14.3下含住房/家庭接口共218项检查通过。
- 165项生成扰动的不变式通过；A未服务案例保留。对应A运行依赖与本轮一致，不是新增经验标定。
- 两版Python重算冻结观察，覆盖表、每条结果、分类、逐目标响应及交互表完全一致。
- 严格覆盖门保持失败，明确指向洗衣费用增加层。软件CI通过只验证实现、完整性及已知验收状态可复现，不宣称本批覆盖通过。
- 原13条旧规则冻结样本可用显式历史规则精确回放，没有重写旧物理回执。

```sh
python -B -m benchmark.ab_generation.validation.joint_tail.recompute --out /tmp/joint-tail-review-new
# 严格覆盖门：本版预期非零退出，保留CHECKS.json和缺额。
python -B -m benchmark.ab_generation.validation.joint_tail.recompute --require-coverage --out /tmp/joint-tail-gate-new
```

公开冻结A重放命令见方法文档，固定Python3.14.3。`frozen_sample`是原选择的公开审查视图；完整变体补丁可由冻结A重建。`CATALOGUE_INDEX.json`覆盖全部唯一请求的身份、特征、静态问题及来源，不只公开成功请求。

原始变体、原生SQL、IDF和日志保存于本地封存证据，永久再生依据为公开输入、固定版本、引擎和命令。集成研究的 `SCREEN.json` 中raw路径指原始封存目录，不能误认为该JSON同目录下已公开全部原生文件。

线上问卷和50户发布包不变；1000户仿真继续暂停。

输入范围另查：当前8个情境全部为工作日、固定降载事件；周末和增载事件尚未验证，见 `validation/joint_tail/INPUT_SCOPE.json`。这不是事后改变22层配额，也不会删除或重抽已执行样本。
