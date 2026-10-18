# 数据接口规范

## 1. 通用约定

本规范定义原型匹配、原生提取、外壳生成和配对仿真的数据接口。各阶段采用独立配置文件，批次规模由输入列表长度确定。

| 项目 | 约定 |
| --- | --- |
| 文件格式 | UTF-8 JSON；仿真资源和请求支持 gzip JSON |
| 标识符 | 输出标识符合 `[A-Za-z0-9][A-Za-z0-9_.-]{0,120}`，批次内唯一 |
| 数值 | 有限数值；人数、房间数及共享户数使用正整数 |
| 单位 | 长度 m，面积 m²，时间 min，温度 °C；设备字段按其名称规定 kW、kWh 或 W |
| 内容哈希 | SHA-256，64 位小写十六进制；gzip 文件校验压缩字节 |
| 资源引用 | `{path, sha256}`；路径解析后须位于声明的资源根目录内 |
| 输出版本 | 每次执行使用新目录；阶段清单保存已登记产物哈希 |

字段表为输入规范。当前实现执行哈希、路径、标识、部分数值及运行依赖检查，未配置覆盖所有嵌套字段的 JSON Schema 验证器。设备特定字段的完整性由编译器在执行时检查。

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

## 5. 家庭世界集成接口

外壳产物进入物理编译前，集成阶段应完成以下绑定：

1. 将 `layout.json` 写入家庭世界的 `world.layout`，保留房间及共享标识。
2. 完成成员房间分配、床位与通行、照护及设备安装检查。
3. 为设备资产绑定房间、参数、供电范围及使用与控制权限。
4. 生成完整成员日历、操作人员窗口、设施预约及服务需求。
5. 将已核验外壳转换为 `shell_rows`，同时记录原外壳字节哈希。
6. 导入策略模块提供的 A/B 请求，并核对家庭、资产、需求和日期标识。

当前包接收上述完整家庭世界，未提供从一般人口画像到该结构的自动装配器。`make-demo`仅实现无居民、无目标可控设备的最小集成测试实例。带设备的集成验证使用受控上游家庭包，结果见[验证规范](VALIDATION.md)。

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
| `history_days` | 112 | 非负整数；实际前史可被输入起点截断 |
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
| `weather`、`weather_sha256` | EPW 相对资源根目录的路径及哈希 |

`days[date]` 包含 `calendars`、`operator_windows`、`family.bath_times_min`、`family.member_dinners_min`、`shared.member_calendars`、`shared.facility_reservations` 和 `controls`；启用热水服务时另含 `water_needs`。当前参考日程覆盖 2024/2025/2026 年。

### 6.3 配对请求

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

设备服务失败保存在模型执行信息中，与引擎状态分别解释。`verify`校验清单登记文件的字节一致性；物理和服务验收见[验证规范](VALIDATION.md)。
