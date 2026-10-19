# 生活到A接口规范

## 1. 输入与单位

批次格式为 `eb.life_to_A.input.v1`，字段为 `schema`、`worlds`及非空 `households`。`worlds={path,sha256}`指向已绑定空间、成员、设备及操作权利的规范家庭世界；路径在批次目录内解析。`households`的标识必须唯一并在该世界文件中存在。

机器可读结构见 [LIFE_INPUT.schema.json](LIFE_INPUT.schema.json)。运行时的日历连续性、权限、资源与服务语义检查由 `life.py`执行；JSON Schema另提供离线结构检查，不代替资源及执行验证。纯生活生成只使用Python标准库。

| 对象 | 定义 |
|---|---|
| `anchor`,`end_exclusive` | 可用日期半开区间，1—730日；排程分钟相对此锚点 |
| `member_calendars` | 全部物理成员，包含共享上下文；工作日、周末及可选日期覆盖 |
| 日历事件 | `start_min,end_min,location,room,activity,available_for_operation`；覆盖每天0—1440，无间隙或重叠 |
| 房间选择 | 已知房间ID，或 `$living/$kitchen/$bath/$sleep`；由空间世界绑定，不能越权 |
| `program_policies` | 服务触发、设备、程序长度、习惯锚点、允许机器窗口、等待与截止规则；不接收最终启动/取出时刻 |
| `thermostat_policies` | 每台AC的占用/在家/连续习惯，保持时长、运行与回退双设定及风机状态 |
| `comfort_requirements` | 受控房间的独立温度范围及来源，未知范围为 `null` |
| `hot_water_minimum_C`,`tank_policy` | 最低服务温度与设备控制目标分别给定；设备参数在世界中 |
| `mobility` | 可选EV合同：原操作人员、锚点连接状态、工作日/周末/日期出行；声明的出发、返家与牵引电量 |
| `facility_reservations` | 可选的日期—房间预约列表，洗浴占用另由原日历生成 |

时间均为整数分钟，采用10分钟网格。温度°C，程序功率kW，设备额定功率W，电池容量与能量kWh，衣物kg，热水为明确的设备热端出口升数。原日历与天气文件年份分别记录，不将典型年天气解释为居民实测日历。

当前生活排程支持一台EV、一台储水式热水器、同日往返出行、显式初始已连接状态，以及同日内的非中断机器程序；不自动补外部充电、跨日出行或多车调度。纯生活日历可覆盖1—730日，实际物理回放仍须满足住房模块的非闰、至多365日及前史/恢复期要求。

## 2. 程序服务输入

三种触发被明确区分：

| 触发 | 设备及需求 | 附加字段 |
|---|---|---|
| `textile` | washer；给定衣物库存及进入量 | `daily_quantity_kg,capacity_kg,initial_inventory_kg,daily_service,no_arrival_release_min` |
| `after_dinner` | dishwasher；原在家晚餐完成后；在外晚餐不产生家中餐具 | 无；只计设备使用家庭中在家就餐的成员 |
| `after_service` | 独立dryer；同一洗涤服务的唯一完整批次后继 | `upstream_service_id`必须指向washer；当前支持一层显式洗衣→烘干，不支持分流或重复烘干 |

共同字段为 `service_id,asset_id,kind,trigger,duration_min,preferred_start_min,maximum_preload_wait_min,maximum_retrieval_wait_min,deadline_after_release_min,machine_windows_min,timer_allowed,priority`。`preferred_start_min`分别提供工作日及周末习惯锚点；它不是强制命令，必须与原可操作资源共同求解。设备程序长度为输入声明，生成器不擅自改短以满足期限。

每台washer/dryer/dishwasher使用各自设备参数和完整人工链。一体洗烘的历史 `:dry`链仍由B接口兼容；新生活生成器的独立烘干使用明确依赖和不同设备，不混用两者。

## 3. 输出

`build-life`输出不可覆盖的新目录：

```text
OUTPUT/
  INPUT.json                 原生活批次
  WORLD_INPUT.json           规范空间及资产世界
  RULES.json                 调度规则及种子
  households/*.json.gz       逐户需求、日历、A和失败记录
  SUMMARY.json               完整批次及准入状态
  MANIFEST.json              代码、输入及产物哈希
```

逐户格式为 `eb.life_to_A.v1`。`requirements`独立保存服务数量、释放、截止、原习惯及来源，并携带定时能力、预装/取出等待和机器窗口，供B继续检查；`A.tasks/operations/controls`记录请求命令；`service_ledger`记录调度结果及等待；`unserved`保留未满足条件；`EV`记录原连接、出行、状态和能量事件。库存字段为尚未分配给A批次的数量，不叫作实际剩余脏衣或已洗净数量。

`A_constructed`与 `needs_unserved`是构造状态。实际服务、室温、水温、SOC和费用后果在物理执行后报告，`human_acceptance`保持未知。

## 4. 通用分阶段命令

1. 住房模块构造外壳后，将空间与设备合同绑定为生活资源：

```bash
python -B -m benchmark.ab_generation bind-life-worlds \
  --world-contracts WORLD_CONTRACTS.json --shells SHELL_DIRECTORY \
  --out outputs/life-worlds
```

2. 编写生活批次，使用上述 `resource_worlds.json`及实际SHA-256；生成A：

```bash
python -B -m benchmark.ab_generation build-life \
  --input LIFE_BATCH.json --out outputs/life-A
python -B -m benchmark.ab_generation verify outputs/life-A
```

3. A生成完成后，才提供独立实验文件及天气，装配物理作业：

```bash
python -B -m benchmark.ab_generation assemble-life \
  --life outputs/life-A --world-contracts WORLD_CONTRACTS.json \
  --shells SHELL_DIRECTORY --weather REFERENCE.epw \
  --experiments EXPERIMENTS.json --out outputs/life-physics
```

实验格式为 `eb.life_A_experiments.v1`，包含住房编译设置、`weather_source`登记及 `{case_id,household_id,date,decision_min,horizon_min,events,tariff,assignment}`列表。天气登记必须提供 `provider,url,dataset,release,sha256`，可指定站号；装配前核对实际EPW字节、站点和完整逐时年覆盖，不能只填一个天气文件名。本物理接口沿用明确的08:00通知及其后24小时主区间，前史与尾期由设置给定；A本身没有这些事件、电价、天气登记或案例选择输入。

4. 以住房模块的 `compile/run/audit`执行A=B基线，再执行：

```bash
python -B -m benchmark.ab_generation reference-life \
  --assembled outputs/life-physics --compiled BASELINE_COMPILED \
  --runs BASELINE_RUNS --audit BASELINE_AUDIT --out outputs/life-contexts
python -B -m benchmark.ab_generation generate \
  --input outputs/life-contexts/BATCH.json --out outputs/life-B-candidates
python -B -m benchmark.ab_generation export-life \
  --assembled outputs/life-physics --contexts outputs/life-contexts \
  --generated outputs/life-B-candidates --policy known_profile_vpp \
  --out outputs/life-selected-B
```

重新对导出的A/B执行 `compile/run/audit`。历史1000户、已有50户、线上问卷、模型API及答卷均非上述命令的输入。公开端到端命令见[复现指南](REPRODUCE.md)。
