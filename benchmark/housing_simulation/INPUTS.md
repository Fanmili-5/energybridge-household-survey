# 输入与输出契约

所有命令从仓库根目录执行。`path`以所声明的资源根目录解析；`sha256`为文件实际字节哈希，gzip文件核压缩字节。批量列表长度决定规模，不从人口主索引读取或补足名额。

## 1. 匹配输入

`match --request request.json --catalog catalog.json`：request包含`household_id`、`province`、`city`、`building_type_order`、`given_epoch_interval:[lo,hi]`，可有`preferred_reference_id`。catalog包含`references`列表，每条有`id`、`province`、`city`、`building_type`、`catalogue_interval`及`admitted`。

`admitted`是调用者在来源核验后写入的候选状态，不能单凭该布尔量证明来源权威；原生提取与气象QC记录应一起保存。输出为所选ID、候选数、年代缺口与参照/更新情景。候选目录和请求字节须在实验配置中冻结。[虚构请求](examples/match_request.json)与[虚构目录](examples/synthetic_catalog.json)展示字段结构。

## 2. 原生DeST提取输入

`extract-native --input native_entry.json --out NEW_DIRECTORY`接收单份原件的来源记录，关键字段为：

```json
{
  "model_key": "YOUR_NATIVE_MODEL_KEY",
  "source_path": "model.accdb",
  "source_sha256": "SHA256_OF_ACCDB",
  "original_environment": {"CITY_NAME": "NATIVE_CITY", "PROVINCE": "NATIVE_PROVINCE"},
  "coordinate_confirmed_WMO_station_candidates": [
    {"path": "weather.epw", "sha256": "SHA256_OF_EPW"}
  ]
}
```

路径相对native_entry位置，也可显式绝对路径；原件和EPW始终按哈希与内容核查。输出`reference.json`包含实际ENVIRONMENT及通过身份核对的天气，`assembly.json`包含材料行、构造映射、厚度、窗标量及原始外键证据。未知或多种实际使用构造需要显式映射，当前实现拒绝自动挑选。

## 3. 住房外壳输入

完整可执行格式见[shell_batch.json](examples/shell_batch.json)。根字段：

| 字段 | 意义 |
| --- | --- |
| `assembly:{path,sha256}` | 提取后的构造闭包；示例使用明确标注的人工材料。 |
| `height_m` | 给定参考层高。 |
| `boundary_policy` | 当前显式支持`midfloor_north_south_reference`。 |
| `studio_shapes`、`gallery_shapes` | 有序的尺寸语法候选；不是户型总体概率。 |
| `households[]` | 任意非空批量，每条有唯一`household_id`、`gross_area_m2`、`natural_rooms`、`shared_households`、`facilities`。 |

`facilities`明确`kitchen`为exclusive/shared/none、`toilet`和`bathing_hot_water`的参考状态；可传邻户房间数与卧室宽度权重。当前`natural_rooms`为自然卧室的参考操作化，不能拿该输入重写调查定义。输出每户`layout.json`、`shell.idf`、`shell_metadata.json`以及含全部成功/拒绝记录的MANIFEST。

该输出只到住房外壳。完整家庭世界需额外具备成员到房间、睡位与通行、照护、设备安装、供电、使用/控制权限及共享预约证据；它们由家庭主线产生。不能直接将shell_compiled状态改名为actor-ready或完整家庭验收。

## 4. 成对物理编译输入

`compile --input physics_job.json --out NEW_DIRECTORY`：

```json
{
  "schema": "eb.housing_physics.input.v1",
  "resource_root": "resources",
  "resources": {
    "inputs/schema_fields.json.gz": "SHA256",
    "inputs/native_rows.json.gz": "SHA256",
    "THERMAL_ENVIRONMENT_POLICY.json": "SHA256"
  },
  "settings": {"history_days": 112, "tail_days": 8, "reference_ach": 0.35, "portal_flow_scale": 1.0},
  "pairs": [
    {"id": "pair-001", "household": {"path": "inputs/home.json.gz", "sha256": "SHA256"},
     "pair": {"path": "inputs/ab.json.gz", "sha256": "SHA256"}}
  ]
}
```

`resource_root`相对配置文件位置；其余path位于该root之内。schema_fields由官方EnergyPlus schema的legacy_idd字段表提取；native_rows包含源设备的`gains`和`tank`对象行；热环境政策见本包[参考配置](reference_environment.json)。输入可为JSON或gzip JSON。

household包保留完整结构：

| 字段组 | 内容 |
| --- | --- |
| `household_id,anchor,end_exclusive` | 身份与可用日程区间，当前内核覆盖2024/2025/2026参考日历。 |
| `world.layout` | rooms、access、面积和房间身份。 |
| `world.parameter_pack.devices` | asset_id、types、room_id和运行参数；拥有/使用与计量含义须由上游解释。 |
| `world.activity_contract.room_map` | 如bath等服务空间。 |
| `world.routine` | 装有热水系统时的混水服务目标等。 |
| `days[date]` | calendars、shared.member_calendars、shared.facility_reservations、operator_windows、family.bath_times_min/member_dinners_min、controls；装有水系统时还含water_needs。 |
| `shell_rows,source_shell_sha256` | 上游已核验住房外壳与源字节。 |
| `HVAC` | 已安装空调的EnergyPlus对象、节点、设备和schedule_names。 |
| `tasks,operations,journeys,EV_battery_energy_events` | 程序与装取、出行及连续电池事件；时间为相对anchor的分钟。 |
| `weather,weather_sha256` | root内的实际EPW及哈希。 |

pair包包含`case_id,household_id,date,source_pair_sha256,schedule_hashes`，`A/B`各自的`tasks,operations,controls`，`needs_A`和`EV_continuous_reference`。pair分钟相对题目日期；内核按冻结需求替换相关任务并恢复后续A，不以B结果修改需求。`make-demo`会写一份最小且完整的工程夹具，可直接检查具体结构；装有空调、热水或EV时，需由相应上游设备编译器提供完整字段，缺字段会明确失败。

编译输出每对A/B的`model.idf`、`INPUT.json.gz`、编译日志及MANIFEST。INPUT记录实际前史、运行区间、执行失败、EV状态、实际供水需求及计量映射。运行输出保留原SQL、eplusout.err、TRACE与RESULT；RESULT的电量覆盖`evaluated_interval_min`，不默认为一天或节能量。

## 5. 版本和依赖失效

改变家庭、住房或设备时，重建受影响世界与两臂；改变A/B、占用、热环境、天气、schema、引擎或前史时，重新编译和执行受影响案例。不能把旧物理结果或人类答案移动到新输入。输出目录不覆盖既有版本；`verify`检查文件字节，不把文件一致性当实测校准。
