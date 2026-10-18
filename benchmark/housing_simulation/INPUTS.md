# 数据接口规范

## 1. 通用约定

本规范定义原型匹配、原生提取、外壳生成、家庭世界装配和配对仿真的数据接口。各阶段采用独立配置文件，批次规模由输入列表长度确定。

| 项目 | 约定 |
| --- | --- |
| 文件格式 | UTF-8 JSON；仿真资源和请求支持 gzip JSON |
| 标识符 | 输出标识符合 `[A-Za-z0-9][A-Za-z0-9_.-]{0,120}`，批次内唯一 |
| 数值 | 有限数值；人数、房间数及共享户数使用正整数 |
| 单位 | 长度 m，面积 m²，时间 min，温度 °C；设备字段按其名称规定 kW、kWh 或 W |
| 内容哈希 | SHA-256，64 位小写十六进制；gzip 文件校验压缩字节 |
| 资源引用 | `{path, sha256}`；路径解析后须位于声明的资源根目录内 |
| 输出版本 | 每次执行使用新目录；阶段清单保存已登记产物哈希 |

家庭装配输入先按`WORLD.schema.json`执行JSON Schema 2020-12结构验证，随后执行跨字段、房间使用权、安装与服务约束检查。未知字段、重复标识、非有限数值及超域条件返回明确错误。其他阶段执行各自的路径、哈希、标识和物理参数检查。

## 2. 原型匹配接口

命令：`match --request request.json --catalog catalog.json`。

### 2.1 匹配请求

| 字段 | 类型 | 必需 | 定义 |
| --- | --- | --- | --- |
| `household_id` | string | 是 | 家庭参考标识，参与确定性并列排序 |
| `province`、`city` | string | 是 | 目标参数参照地区 |
| `building_type_order` | string[] | 是 | 建筑类型优先序，按列表顺序选择 |
| `given_epoch_interval` | integer[2] | 是 | 给定住宅年代闭区间 `[lo, hi]`，`lo ≤ hi` |
| `preferred_reference_id` | string | 否 | 相同类型与年代距离下的优先原型 |

### 2.2 候选目录

目录根对象包含 `references`。每条候选包含 `id`、`province`、`city`、`building_type`、`catalogue_interval` 和 `admitted`。`admitted` 表示来源登记阶段的准入状态，其支撑材料为原生身份、构造闭包及气象质量记录。

输出包含 `selected_reference_id`、`candidate_count`、`minimum_catalogue_gap_years`、`given_epoch_interval` 和 `envelope_mode`。给定年代与候选目录区间存在间隔时，`historical_reference_gap=true`，并采用明确的围护更新参照状态。

格式示例：[匹配请求](examples/match_request.json)、[候选目录](examples/synthetic_catalog.json)。示例地名与原型均为合成测试数据。

## 3. 原生参数提取接口

命令：`extract-native --input native_entry.json --out OUTPUT_DIRECTORY`。

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `model_key` | string | 原始模型目录键 |
| `source_path` | string | Access 原件路径 |
| `source_sha256` | string | 原件内容哈希 |
| `original_environment.CITY_NAME` | string | 计划来源的原生城市名称 |
| `original_environment.PROVINCE` | string | 计划来源的原生省份标签 |
| `coordinate_confirmed_WMO_station_candidates` | object[] | 待复核的气象候选，每项至少包含 `path`、`sha256` |

原生提取接口的路径相对配置文件位置解析，也接受显式绝对路径。提取器读取实际环境表、构造外键及材料层，并逐项核验登记哈希。

输出结构：

```text
OUTPUT_DIRECTORY/
  reference.json      原生环境、来源身份和确认的气象候选
  assembly.json       构造行、材料行、厚度、窗标量及外键证据
  MANIFEST.json       阶段元数据与产物哈希
```

`assembly.json` 至少包含 `rows`、`names`、`exterior_thickness_m`、`interior_thickness_m`、`source_sha256` 和 `climate_identity`。`names` 中的 exterior、interior、floor、window 指向可解析的构造及材料闭包。

## 4. 参考外壳接口

命令：`build-shell --input shell_job.json --out OUTPUT_DIRECTORY`。

### 4.1 批次配置

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `assembly` | artifact reference | 相对批次配置位置的构造参数文件及哈希 |
| `height_m` | number | 参考层高；当前门窗几何要求大于 2.1 m |
| `boundary_policy` | string | 当前值为 `midfloor_north_south_reference` |
| `studio_shapes` | number[][] | 开间尺寸候选，按输入顺序尝试 |
| `gallery_shapes` | number[][] | 走道住宅尺寸候选，按输入顺序尝试 |
| `households` | object[] | 非空住宅条件列表 |

### 4.2 住宅条件

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `household_id` | string | 批次内唯一家庭标识 |
| `gross_area_m2` | number | 本户分配建筑面积，严格大于零 |
| `natural_rooms` | integer | 本户参考自然卧室数 |
| `shared_households` | integer | 整套住宅内的共享家庭数 |
| `facilities.kitchen` | string | `exclusive`、`shared` 或 `none` |
| `facilities.toilet` | string | 上游卫生设施类别；`none` 表示无此设施参照 |
| `facilities.bathing_hot_water` | string | 上游热水设施类别；`none` 表示无此服务参照 |
| `reference_neighbor_room_counts` | object | 可选，辅助家庭标识到房间数的映射 |
| `target_bedroom_width_weights` | number[] | 可选，本户各卧室宽度权重，长度与卧室数一致 |

辅助家庭标识采用 `household_id-aux-NN`。其面积参与整套物理面积账目，人口身份及行为需要独立的上游记录。

尺寸候选为五元组 `[bay, depth, corridor, service, kitchen_fraction]`；单侧走道分支使用六元组并附加 `hall_fraction`。长度单位为 m，比例用于服务空间分配；卧室尺度由面积方程求解。候选数组及次序均属于实验配置。

### 4.3 输出与状态

每个成功条目输出 `layout.json`、`shell.idf` 和 `shell_metadata.json`。布局记录建筑面积、净面积、热区面积、分配份额、房间矩形及门连接。

批次 `MANIFEST.json` 为每个输入条目保存状态：`shell_compiled` 表示外壳构造完成；`rejected` 表示给定条件未通过构造，并保存原因。`sleep_and_appliance_installation_checked=false` 明确该阶段的验收范围。

可执行配置见 [shell_batch.json](examples/shell_batch.json)。

## 5. 家庭世界装配接口

```bash
python -B -m benchmark.housing_simulation assemble \
  --input world_batch.json --shells /tmp/shells \
  --weather /path/to/weather.epw --out /tmp/worlds
```

结构定义为[WORLD.schema.json](WORLD.schema.json)，完整非空输入见[world_batch.json](examples/world_batch.json)。`--shells`必须是通过清单核验的`build-shell`输出；家庭标识与外壳标识一致。天气是显式文件路径。创建世界输出前核验登记哈希、LOCATION范围、单一全年小时序列、时序连续性及干球温度有效值；结果保存为`inputs/weather_identity.json`。该检查不替代完整气象质量审查。v2新增必需天气登记及条件约束；v1作业须补齐字段并修改版本标识后提交。

### 5.1 作业配置

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `schema` | string | 固定为`eb.housing_world.input.v2` |
| `weather_source` | object | 必需`provider`、`url`、`dataset`、`release`、`sha256`；可选`station`、`usage`。哈希必须与实际EPW相同，站号若声明须与LOCATION一致 |
| `settings` | object | 必需：`history_days`、`tail_days`、`reference_ach`、`portal_flow_scale` |
| `thermal_fractions` | object | washer/dryer/dishwasher/misc/refrigerator/cooking各自的`[latent,radiant,lost]`，各项0–1且和不超过1；剩余部分为对流 |
| `households` | object[] | 非空家庭列表；全局家庭标识与案例标识唯一 |

### 5.2 家庭契约

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `household_id` | string | 目标家庭及外壳标识 |
| `anchor`、`end_exclusive` | ISO date | 完整日历区间，终点不含；长度1–730天 |
| `members` | object[] | 整个物理住宅内的完整名册，包含共享邻户 |
| `sleep_groups` | object[] | 一或二人睡眠组、参考床尺寸与可选指定卧室 |
| `fixtures` | object[] | 便器、淋浴、厨房台及冰箱等矩形参考包络 |
| `devices` | object[] | 资产、类别、使用家庭、安装、服务连接与物理参数 |
| `electrical_supply_W` | number | 住宅供电功率上界，W |
| `exhaust_power_budget_W` | number | 供电筛查的排风功率预算，W |
| `background` | object | `lighting_W_m2`、`misc_W_m2`、`refrigerator_W`、`cooking_W` |
| `hot_water_minimum_C` | number | 参考热水出口最低服务温度，°C |
| `calendars` | object | 成员引用的工作日、周末及可选日期事件模板 |
| `services` | object[] | 洗衣、干衣及洗碗的日常需求与执行时点 |
| `controls` | object[] | 设备日常控制；热泵与水箱要求每日连续完整覆盖 |
| `ev_connection` | object | 安装EV时必需：操作人、每日接插时点、初始连接状态及行程 |
| `cases` | object[] | 非空案例列表，含日期、服务位移及控制覆盖 |
| `facility_reservations` | object | 可选；按日期声明的房间预约 |

成员字段为`member_id`、`household_id`、`age_years`、`calendar_id`、`hot_water_liters`及`can_operate_asset_ids`。`hot_water_liters`是每次洗浴的水箱出口热水量，单位L；零表示无该热水需求。全住宅每位成员恰好分配一个床位。睡眠组字段为`group_id`、`member_ids`、`capacity`、`bed_footprint_m`及可选`room_id`。

设施字段为`fixture_id`、`kind`、`room_id`、`footprint_m`。已声明卫生间必须提供`toilet_reference`和`shower_reference`；厨房必须提供`sink_cooking_reference`和`refrigerator_reference`。设施是安装占地见证，排水网络和高度不在本接口中求解。

### 5.3 资产与参数

通用字段为`asset_id`、`kind`、`using_household_ids`、`placement`、`parameters`和`connections`。落地设备另需`room`、`footprint_m`，壁挂设备另需`room`、`mount_width_m`，EV使用`placement=exterior`。每个资产均声明`parameters.nameplate_W`。

房间可使用具体标识，或`$living`、`$kitchen`、`$bath`、`$sleep:member_id`选择器。公共选择器按功能优先级和房间标识确定；最终房间写入输出。使用家庭必须有对应房间使用权。

| `kind` | 专用参数 | 必需服务连接 |
| --- | --- | --- |
| `washer` / `dryer` / `dishwasher` | `power_kw` | 电；洗衣/洗碗另需水与排水；干衣另需排风 |
| `ac` | 冷/热容量W、冷/热COP、风量m³/s、风机功率W及压升Pa、显热比、补热及除霜功率W | 电、室外换热 |
| `water_heater` | 体积m³、高度m、加热功率W、最高温度°C、死区°C、面散热系数W/(m²·K)、效率、2–12个节点 | 电、水 |
| `ev` | 充电功率kW、容量kWh、效率、目标与最低SOC、锚点初始电量kWh | 电、专用停车 |

精确键名及数值边界由Schema和`assembly.bind_world`定义。储水箱与EV各至多一个；热泵可按不同房间配置多个，同一热区至多一个独立控制的热泵。壁挂宽度检查不输出三维安装证明。

### 5.4 日历、服务与案例

日历模板含`weekday`、`weekend`及可选`date_overrides[YYYY-MM-DD]`。事件字段为`start_min`、`end_min`、`location`、`room`、`activity`、`available_for_operation`。时间为当日分钟，按10 min对齐，采用左闭右开区间。每天恰好覆盖`[0,1440)`；在家事件绑定可访问房间，离家事件`room=null`。`sleep`、`bath`及`dinner`用于睡眠、独占洗浴与烹饪排风绑定。操作窗口必须由输入显式允许，睡眠、包含`nap`的活动和洗浴期间不得操作。睡眠及午睡必须在本人已分配卧室，洗浴必须在实际卫生间，晚餐必须在家；有非零热水需求的成员所属家庭须具有水箱使用权。

服务字段为`service_id`、`asset_id`、`kind`、`operator_id`、`start_min`、`duration_min`、`retrieval_min`、`release_min`、`deadline_min`及`weekdays`（0=周一）。装载在程序开始前10 min执行，取出持续10 min。干衣可通过`after_service_id`声明洗衣前序；前序必须取出完成后才能装载。日常服务与接插操作均接受人员、房间及设备冲突检查。

案例字段为`case_id`、`date`、`service_shifts`及`control_overrides`。服务位移对同一需求的装载、程序、取出整体平移，需求释放与截止不变。控制种类分别为`ac_setpoint`、`tank_setpoint`、`ev_charge_window`，精确字段见Schema。通知时点固定为案例日起480 min；改变通知前事件的请求拒绝。EV接插和行程保持不变，仅允许调整充电窗口或目标SOC。每个EV控制窗口须完整位于同一物理连接段内；跨越出行断开的窗口拒绝。锚点首日拔插同样需要可用操作人，完整基线逐次出行均须保留最低SOC。B控制须有目标家庭授权成员，服务位移也仅允许目标家庭授权操作的服务；上下文住户的日常计划不由该请求改动。B方案的执行失败作为结果保留，审计返回失败，不自动改写请求。

### 5.5 产物与状态

保存可重用的`assembly_input.json`快照；每户输出`households/<id>/world.json`和`physics.json.gz`；每案例输出`pairs/<case>.json.gz`；批次输出可直接提交`compile`的`physics_job.json`。世界文件保存床位与设施安装见证、解析后的资产和成员、供电账目及项目规则身份。

`assembled`表示该户通过结构、空间、权限、供电及完整基线执行检查。`rejected`保留家庭标识及原因，并计入`households_requested`。失败家庭不进入编译队列；任一拒绝均使CLI返回非零退出码。批次结构错误在创建输出前返回；资源读取失败返回非零退出码，并保留已创建的诊断目录。所有阶段输出目录必须不存在。

## 6. 配对物理编译接口

命令：`compile --input physics_job.json --out OUTPUT_DIRECTORY`。

### 6.1 作业配置

```json
{
  "schema": "eb.housing_physics.input.v1",
  "resource_root": "resources",
  "resources": {
    "inputs/schema_fields.json.gz": "SHA256",
    "inputs/native_rows.json.gz": "SHA256",
    "THERMAL_ENVIRONMENT_POLICY.json": "SHA256"
  },
  "settings": {
    "history_days": 112,
    "tail_days": 8,
    "reference_ach": 0.35,
    "portal_flow_scale": 1.0
  },
  "pairs": [
    {
      "id": "pair-001",
      "household": {"path": "inputs/home.json.gz", "sha256": "SHA256"},
      "pair": {"path": "inputs/ab.json.gz", "sha256": "SHA256"}
    }
  ]
}
```

示例中的 `SHA256` 为资源准备阶段生成的实际哈希。`resource_root` 相对配置文件位置解析，其余资源路径位于该目录内。

`schema_fields` 为官方 EnergyPlus schema 的 `legacy_idd.fields` 映射。`native_rows` 保存源设备的 `gains` 和 `tank` 对象行。热环境配置定义门交换、排风和补风参数。

| 运行参数 | 默认值 | 接口约束 |
| --- | ---: | --- |
| `history_days` | 112 | 非负整数；输入必须完整覆盖请求前史，装配接口要求至少1天 |
| `tail_days` | 8 | 正整数；实际尾期还受最后请求及可用终点约束 |
| `reference_ach` | 0.35 | `0 < value ≤ 3` |
| `portal_flow_scale` | 1.0 | `0.5`、`1.0`、`2.0` |

### 6.2 家庭包

| 字段组 | 数据定义 |
| --- | --- |
| `household_id`、`anchor`、`end_exclusive` | 家庭标识及可用日程半开区间 |
| `world.layout` | 房间、面积、连接及共享条件 |
| `world.parameter_pack.devices` | 设备标识、类型、房间及物理参数 |
| `world.activity_contract.room_map` | 服务空间映射，包含浴室等位置 |
| `world.routine` | 启用热水系统等服务时的运行参数 |
| `days[date]` | 成员日历、共享成员日历、设施预约、操作窗口、服务时点与控制 |
| `shell_rows`、`source_shell_sha256` | 已核验外壳对象行及来源哈希 |
| `HVAC` | 已安装空调对象、节点、设备名和控制日程名 |
| `tasks`、`operations` | 程序任务与人工操作 |
| `journeys`、`EV_battery_energy_events` | 行程及连续电池事件 |
| `EV_physical_connections`（可选） | 显式物理连接区间；生活生成接口使用，旧包继续按原插拔操作推导 |
| `weather`、`weather_sha256` | EPW 相对资源根目录的路径及哈希 |

`days[date]` 包含 `calendars`、`operator_windows`、`family.bath_times_min`、`family.member_dinners_min`、`shared.member_calendars`、`shared.facility_reservations` 和 `controls`；启用热水服务时另含 `water_needs`。输入不依赖固定年份；实际运行区间须不含2月29日且不超过365天，完整覆盖前史及恢复期。

`EV_physical_connections` 的每项包含唯一 `need_id`、已安装 `asset_id`、相对家庭 `anchor` 的 `start_min/end_min` 及 `origin`。区间位于10分钟网格、不得重叠或穿过行程。`origin=given_anchor_connection` 仅可从0开始，表示声明的初始已连接状态；其余开始边界须有真实 `EV_plug` 操作结束，离开前的结束边界须有 `EV_unplug` 操作开始。家庭覆盖末端可保持连接。该字段只声明物理连接，不能代替充电控制、电池账本或出发能量检查；实现为 `kernel/execution.py:explicit_EV_connections`，编译器据此设置原生充电连接窗口。

### 6.3 配对请求

`needs_A`可带独立温度要求：`kind=comfort`、`room_id`、相对案例日期的 `release_min/deadline_min`及 `temperature_band_C`。范围为 `null`表示未知，不从控制设定补齐。编译器将这些要求传给物理审查，与程序及EV出发目标分别核对。

配对包包含 `case_id`、`household_id`、`date`、`source_pair_sha256`、`schedule_hashes`、`needs_A`、`EV_continuous_reference`，以及 `A`、`B` 各自的 `tasks`、`operations`、`controls`。

家庭包任务时间相对 `anchor`，配对请求时间相对 `date`，单位均为 min。资产、任务、操作及需求标识必须与家庭世界一致。`EV_continuous_reference.status=not_installed` 表示无 EV；已安装设备的特定字段由对应设备协议定义。

## 7. 仿真执行与产物状态

命令：`run --compiled COMPILED_DIRECTORY --out OUTPUT_DIRECTORY --engine ENGINE --engine-sha256 SHA256`。

每臂保存原始引擎输出、`TRACE.json.gz` 和 `RESULT.json`。回执包含引擎和 IDF 哈希、警告、执行状态、`evaluated_interval_min` 及相应区间的电量。轨迹保留通道单位、计量属性和时间—数值序列。

| 阶段 | 状态 | 定义 |
| --- | --- | --- |
| 编译 | `compiled` / `failed` | 物理模型编译完成或失败 |
| 运行 | `completed` / `engine_failed` | 引擎完成或失败 |
| 回读 | `readback_or_engine_failed` | 执行、超时或轨迹检查失败 |
| 批次传递 | `compile_failed` | 编译失败条目在执行批次中的保留状态 |

`RESULT.json`同时绑定SQL及TRACE文件哈希，审计再次验证回执。设施电量为全住宅口径，包含共享邻户及公共负荷，面积份额不构成电量分摊规则。设备服务失败保存在模型执行信息中，与引擎状态分别解释。`verify`校验清单登记文件的字节一致性；物理和服务验收见[验证规范](VALIDATION.md)。

## 8. 统一物理审计接口

```bash
python -B -m benchmark.housing_simulation audit \
  --compiled /tmp/compiled --runs /tmp/runs --out /tmp/audit
```

审计验证编译清单与运行清单绑定，输出`MANIFEST.json`中的`passed`、逐案例`checks`及`details`。失败返回非零退出码。服务失败与引擎失败分别记录；引擎运行完成不等价于家庭服务完成。检查公式和容差见[验证规范](VALIDATION.md)。
