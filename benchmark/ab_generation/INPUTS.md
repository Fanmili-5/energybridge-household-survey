# B生成与后果回读接口

## 1. 版本与单位

规范上下文为 `eb.ab_generation.context.v3`，生成结果为 `eb.ab_generation.result.v3`，包阶段为 `eb.ab_generation.frozen_A.v3`，物理报告为 `eb.ab_generation.physical_report.v3`。批次容器沿用 `eb.ab_generation.batch.v1`。v1/v2上下文须重建或重新只读导入；不自动补权限、设备能力或离线信息声明。

时间为相对案例日期的整数分钟，采用10分钟网格；负值表示通知前/前一日期。功率kW，电量kWh，温度°C，电价为显式币种每kWh。原始轨迹能耗J在回读时转换，不能直接与kWh相加。

## 2. 上下文

| 字段 | 含义 |
|---|---|
| `case_id,household_id,date` | 原案例与家庭身份 |
| `decision_min,horizon_min` | 通知与主要比较区间 |
| `A.tasks/operations/controls` | 已冻结的程序、真实人工操作与控制 |
| `needs` | 独立服务要求；程序项含 `timer_allowed,maximum_preload_wait_min,machine_windows_min`及原等待/截止 |
| `devices` | 已安装资产及实际声明的参数，不代表可随意增添设备 |
| `operator_windows,occupancy,reservations` | 原人员可操作窗口、房间占用及预约 |
| `authority` | 每资产 `authorized_operator_ids,target_control_authorized`，以及 `immutable_operator_ids`和来源 |
| `events,event_meter_scope` | 固定事件与目标计量；事件自身的 `meter_scope`优先 |
| `tariff,tariff_provenance` | 完整显式价格段与币种/来源；不表示实时价格 |
| `source,reference` | 家庭、模型、天气、初始化、当前A输入及运行证据 |
| `assignment` | `fresh_candidates`、`identical_control`或 `preserved_failure_replay` |
| `retained_B_request` | 仅指定历史失败回放分支使用的原请求，不读其实际后果 |

`reference.binding`保存A命令和物理上下文摘要。`thermal`按资产保存时步温度、电耗与名义余量；新生活水箱参考另含前一报告边界的`node_temperatures_C`全节点向量及其时间说明；向量有则须长度匹配硬件且数值有限，缺失时不伪造状态支持。AC新增 `axis_electric_kWh`，来自原生制热/制冷线圈。缺少模式证据时不猜测降载轴。`ev_charging_steps`是当前A的实际网侧充电步骤；同一需求/时步不得重复。

`reference.information_set`必须明确`offline_full_A_counterfactual`或手写测试的`synthetic_interface_fixture`、完整所供A区间、未来A可用、B最终后果/答卷不可用、无实时部署声明和空预测器。范围须覆盖主区间及所供热/EV参照，不得把含尾期的EV参照缩称24小时信息。新生活参考另存`baseline_admission`审查SHA；`reference-life`必传`--audit`，核对服务/物理审查及编译/运行身份。定义见[OFFLINE_EXPERIMENT.md](OFFLINE_EXPERIMENT.md)。

`information_set,proposal_purpose`随物理交接进入回读报告。后者明确合成反事实提案、非原EB控制器输出，接受和满意度未知；生成排序不是人的效用估计。

控制权限不等于人在家。共享上下文成员仍进入占用与仿真，但其操作不能由目标家庭的B移动。原A46的720分钟预装及06:30—23:30窗口在导入器中明示为继承的项目假设，未表述为实测设备规格。

## 3. 候选与选择

结果包含 `candidates,unavailable,selections,joint_candidates,device_opportunity_inventory`。清单逐资产报告候选数、静态通过且有依据数、探索数、依赖链专属状态及缺失原因。单候选保存稳定身份、因素、补丁、`static_issues`和预测；每项另有`opportunity.status,basis,actual_response_confirmed`，程序/EV含逐资产解析L1，热项含采样A阈值见证。已知程序/EV预测保存A/B负荷剖面供复核，热响应预测为未知。实际后果和人类接受值不写入候选排序。

补丁类型为既有行替换、明确温控区间，以及EV的 `control_pause`。暂停只移除原许可的特定部分，保留原间隙和通知前命令。不得借补丁新增帮手、换资产或缩短非中断程序。

三种规则各返回 `candidate_ids,status,plan_B,B_commands_sha256`、预测和命令扰动。比较域为静态通过、机制supported的单设备替代方案；`baseline_outside_option`另列不改变A的零增量。`no_comparable_opportunity`表示没有该规则的可比候选，不是假造一个有交付响应的B。无事件时VPP规则不可比较。

联合请求保留独立 `id`、子候选身份及组合后的静态检查；`opportunity.children,joint_support`逐子请求保留机制依据，分为all_supported/mixed/all_exploratory。常规三规则未自动选择联合最优；公开复核可按冻结计划选择联合探针并执行。

## 4. 物理交接

`export-life`核对生活装配、当前A参考、生成批次及选定B，输出统一住房作业。原A、独立需求、事件和通知前命令保持。服务需求与控制设定仍为不同对象。

旧版 `export-physics`须提供原阶段、更新后的规范导入与生成目录。若旧家庭包缺完整需求，另传 `--annual-A-root`，目录内为各家庭原年度A文件；逐文件核对原家庭包登记的SHA、身份、任务和操作后读取全年原需求。没有该文件即拒绝，不从已排程程序补造需求，也不因配对文件只有数日而漏检恢复期服务。

一房间多套独立AC的旧世界不受当前编译器支持。适配器明确拒绝导出，不合并设备或修改原控制。静态生成结果与物理可重放状态分别解释。

## 5. 实际报告

`report-physics`绑定作业、编译、运行与审查，检查各臂IDF、SQL和轨迹回执。可传 `--reference-runs`与用于生成B的A基线逐通道比较；旧阶段使用 `--reference-stage`时只声明共有通道范围，两者不可同时给定。

报告包含：

- `request_opportunity`及`targeted_response`：逐目标电量剖面L1、峰值差、温度/SOC差、实际执行时点和全部/部分/无变化类型；数值变化不是人的可感知阈值；
- 每事件净住宅电表和所建模可控设备小计、所声明口径的目标是否满足；
- 主24小时与主区间加跟随期的电量和明确币种电费；缺价保持未知；
- 实际执行、人工时刻变化、交付、预装/取出等待和截止；
- 每房间温度及独立范围外分钟/度分钟，未知要求保持 `null`；
- 热水数量/温度、EV原居家连接后的出发目标/储备/牵引能量，以及恢复残差。

共享整套电表不自动分摊为目标家庭账单；未声明的VPP补偿不计入费用。编译或引擎失败、通道缺失保留 `readback_status=incomplete`和原因，不填零后果。实际结果不触发重选；`human_acceptance`保持未知。

## 6. 公开复核与上游接口

`reproduce-strategies`使用公开生活与空间输入、显式实验及 `plan.json`，输出冻结计划、A基线、同A三规则请求、设备/联合/失败探针和完整回读。冬季计划单独验证制热；数量由配置列表决定。常规 `reproduce-life`也执行默认三策略。

上游输入及单位见 [LIFE_INPUTS.md](LIFE_INPUTS.md)，方法与来源见 [METHOD.md](METHOD.md)、[STRATEGY_RULES.json](STRATEGY_RULES.json)，执行命令见 [REPRODUCE.md](REPRODUCE.md)。
