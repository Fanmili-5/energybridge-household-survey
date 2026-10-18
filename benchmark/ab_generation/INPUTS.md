# 数据接口

## 1. 批次与规则

批次为UTF-8 JSON：`schema=eb.ab_generation.batch.v1`，`records`为 `{case_id,context}` 列表。`context`相对批次文件解析，不得越出批次根目录。案例ID必须唯一。允许JSON与gzip JSON；公开生成阶段仅使用Python标准库。

`--rules`为 `eb.ab_generation.rules.v1`。支持字段及默认水平见 `examples/rules.json`。未知字段、未知选择规则、非10分钟时间水平和非正剂量被拒绝。不同实验应另存配置，不修改已封存清单。

## 2. 案例上下文

| 字段 | 类型/单位 | 定义 |
|---|---|---|
| `schema` | string | `eb.ab_generation.context.v1` |
| `case_id`,`household_id`,`date` | string | 案例、家庭及原日历日期 |
| `decision_min` | integer，min | 已知情境并允许提出干预的起点 |
| `horizon_min` | integer[2]，min | 主机会搜索区间；分钟均相对 `date`，允许日外值 |
| `A.tasks` | object[] | `task_id,need_id,asset_id,kind,start_min,end_min` |
| `A.operations` | object[] | `operation_id,need_id,asset_id,kind,operator_id,room_id,start_min,end_min` |
| `A.controls` | object[] | 设备原生控制；AC供暖/制冷设定与风机、热水设定、EV许可及SOC目标 |
| `needs` | object[] | 独立服务需求；程序至少含 `need_id,asset_id,kind,release_min,deadline_min`；可含最长取出等待 |
| `devices` | object[] | 设备标识、类型、房间及参数；程序功率kW；温控温度°C；EV参数不由类别猜测 |
| `operator_windows` | object | 原操作人员到绝对分钟区间列表的映射 |
| `occupancy` | object | 房间到实际有人区间列表的映射；不同于温控许可 |
| `reservations` | object[] | `room_id,start_min,end_min`，含原共享预约及洗浴占用 |
| `events` | object[] | 固定 `event_id,start_min,end_min,direction,target_kw`；方向为 `up/down` |
| `tariff` | object[] | 分段 `start_min,end_min,price_per_kWh`；可空，空或不完整时费用排序不可用 |
| `assignment` | object | `mode=fresh_candidates/identical_control/preserved_failure_replay`；事先固定 |
| `retained_B_request` | object | 仅指定失败回放必需，原始B命令；不得用新候选替换 |
| `source` | object | 原家庭、A输入、模型、天气、引擎、初始化及相关来源摘要 |
| `reference` | object | 下述当前A运行参考 |

本版本要求同一设备同类控制区间不重叠。程序任务与操作ID唯一、资产存在、起止有效、分钟在10分钟网格上。它不是全部家庭世界的领域验证器；物理/服务完整性仍由住房模块执行。

## 3. 当前A参考

`reference.binding`由 `benchmark.ab_generation.generate.binding(context)`计算，包含 `A_commands_sha256`及物理上下文摘要。它必须与当前输入一致，失配立即拒绝。`reference.provenance`声明来源。

`reference.thermal[asset_id]`为 `{minute,temperature_C,electric_kWh,headroom_kWh}`列表。温度为间隔起点，能量对应其后10分钟；AC电量扣除风机，额定电余量是搜索参照。公开合成例将参考明确标为人工测试状态。

`reference.ev_charging_steps`为当前A已交付的 `{need_id,start_min,end_min,grid_kWh}`。没有能量的许可时段不构成EV机会。它不包含新B的连续SOC结果。

## 4. 生成结果

每案输出 `eb.ab_generation.result.v1`，包括原物理依赖、整个输入摘要、参考摘要、规则摘要、单设备 `candidates`、`unavailable`、三份 `selections`和 `joint_candidates`。

每个候选保存原生因素、显式补丁、静态问题、预测范围及未知的实际结果。`rows`补丁只能替换已有ID；`control_interval`仅修改原控制的指定相交区间，保留区间外A。EV内部控制身份不写入选定物理方案。

| 选择状态 | 含义 |
|---|---|
| `candidate_selected` | 根据公开规则选到静态可用候选；尚未完整仿真 |
| `assigned_identical_control` | 事先指定A=B，保持原命令 |
| `original_failure_request_preserved` | 原B指定失败原样进入回放；不是新生成成功候选 |
| `no_comparable_opportunity` | 该规则缺少可比较机会，不能把输出A副本作为一份新的干预 |

`actual_outcomes=null`、`human_acceptance=null`。代码不会把静态可行、费用减少或VPP贡献赋为接受答案。联合候选的静态冲突分别保留。

## 5. 物理交接

`export-physics`核验导入和生成清单、原始A、家庭、配对文件及天气，输出新资源目录与 `physics_job.json`。所选B、原A、需求及事件构成新的配对请求；旧B的分类、温度、SOC结果不继承为新结果。

作业使用 `housing_simulation` 的 `compile`与 `run`接口，固定相同外壳、天气、前史、初态和恢复时域。资源原件的使用条件沿用其来源；公开仓库仅发布代码、合成示例与聚合验证，不将受控家庭或天气原件一并发布。

## 6. 新生活生成接口

`build-life`、`bind-life-worlds`、`assemble-life`、`reference-life`、`export-life`及 `reproduce-life`组成不依赖历史样本的入口，定义见 [LIFE_INPUTS.md](LIFE_INPUTS.md)。新A保留独立服务需求，原人工操作与独立烘干依赖进入B候选检查；EV锚点状态和原物理连接不通过虚构操作补齐。
