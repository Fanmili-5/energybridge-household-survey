# EB 规划之后，设备是否真正进入 EnergyPlus

审计日期：2026-09-12。作者 main 当日重新 fetch 后仍为 `2b17ae63e613da776c93e900f5dace50d63a88a8`；独立 checkout 跟踪文件无修改。本文限定讨论原生 EB 生成方案后的执行接口，不讨论问卷字段、家庭分类或增加新电器。

**结论：当前默认资产与多电器执行代码存在接口不匹配。洗衣机、洗碗机、烘干机的排程可以已进入 Python 电器模型，但其功率没有写入 EP；冰箱的基荷也在同一处缺失。空调、EV 和热水器有各自有效的 EP 控制接口。**

## 断点在哪里

```text
EB 输出 appliances
        ↓
原执行规则接受动作，更新 ApplianceSuite 的设备时刻
        ↓
每步 suite.step() 计算该时刻的设备功率
        ↓
_write_appliance_actuators() 写 EP schedule
        ↓
Schedule → ElectricEquipment → EP 电表
            ↑ 默认模型缺四组对象，handle = -1，写入被跳过
```

| 执行步骤 | 作者代码位置 |
|---|---|
| 选择计划并读出 `data["appliances"]` | `experiments/benchmark/family_runner.py:12138, 12188, 12520, 12584` |
| 应用计划中的设备动作 | 同文件 `14543–14549`，调用 `_adaptive_v3_apply_appliance_actions` |
| 修改可移位任务开始时间 | 同文件 `3504`；`energybridge/simulation/appliance_sim.py:490–492, 68–79` |
| 按时刻产生 kW，再写 EP | `family_runner.py:14809–14810`；`appliance_sim.py:520–530` |
| 取得四个句柄，缺失时得到 -1 | `family_runner.py:2624–2627` |
| 缺句柄即静默跳过 | 同文件 `10769–10786` |
| 建筑能耗来自 EP，而非把漏掉的 Python 功率另行补加 | 同文件 `14799–14806`；`energybridge/data/day_ahead.py:333–389` |

原项目是连续闭环：一次 `run_family_agent` 创建一个 EP state（`10906`），注册回调并启动一次 `run_energyplus`（`14818–14819`）。规划在回调内发生，更新控制后 EP 继续推进。参考路径与 agent 路径可以分别运行；不是每得到一份新计划都重新启动 EP。

## 其他电器在哪里接入

| 设备 | 当前正式主线的写入方式 | 默认资产与此次实测 |
|---|---|---|
| 空调 | `heating_sch` / `cooling_sch`；`family_runner.py:14793–14794` | 原 IDF 有温控对象；降低制冷设定温度后 EP 制冷电量变化 |
| 空调可用性 | `run_persona_json.py:287–328` 动态加入并连接 `HVAC_Availability_Control` | 不能只搜原始 IDF 就判为缺失；本次使用作者真实注入函数得到有效句柄 |
| EV | `_write_appliance_actuators` 内写 `EV_Charging_Fraction_Control` | 已连接 `EV_Charger`，设计功率 7 kW；半功率一小时计量 3.5 kWh |
| 热水器 | 同一 writer 写 `EWH_Setpoint_Control` 温度 | 已连接实际水箱；改变设定温度后 EP 热水器电量变化。此处不是把 Python 热水器 kW 再叠加一次 |
| 洗衣 / 洗碗 / 烘干 | 同一 writer 写各自 `*_Power_Frac` | Python 执行逻辑存在；当前默认 IDF 缺对应 schedule / equipment |
| 冰箱 | 同一 writer 写 `Refrigerator_Power_Frac` | 缺对应对象；它是基荷，不能说成 EB 应该给冰箱移峰 |

另有 `energybridge/simulation/actuator_writer.py` / `eplus_env.py`、`Family_Model/control_model/control_model.py` 等接口，但不是当前 `family_runner` 主线的四设备补写路径。旧 `shiftable_load.py` 的 Python 能耗记账也不替当前主线 EP 电表补量。PPO 的部分 EP 环境有独立 writer，但仍查找相同句柄，不能补救 IDF 缺对象。

## 设计取舍与接口缺口需要分开

[作者改造记录 §10](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/Family_Model/envelope_retrofit_report.md#L520) 明确说明：为了 EV/EWH 实验，删除了旧住宅的静态家电负荷，也删除了洗衣机、洗碗机的热水支路。这是有意的建模取舍。

然而，[当前 writer](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/experiments/benchmark/family_runner.py#L10745) 明确准备向 EP 写入四类动态电器，注释还声明功率对应 IDF 中的设备对象。当前四份默认模板、实际资产准备路径及其他脚本均未提供这些对象。能确定的是**当前执行代码与默认资产的契约不一致**；不能据此推测作者为何漏补，或声称已经定位首次引入缺口的提交。

因此修复应补动态电气接口，不能把已主动删除的旧全年日程、热水支路、电视/电灶等全部恢复。

## 本次真实测试

先单独验证了原代码的动作应用：手工输入三设备 18–19 点的固定方案，再输入改为 20–21 点的方案；原 `_adaptive_v3_apply_appliance_actions` 均返回 `applied_as_requested`，没有拒绝。`ApplianceSuite` 的实际功率区间随之移动，洗衣/洗碗/烘干电量保持 2/1.5/3 kWh。模拟句柄捕获到 writer 的对应开关比例。这一项不运行 EP，只用于确认断点前的执行逻辑；摘要见 [fixed-plan-suite-summary.json](fixed-plan-suite-summary.json)，完整逐步数据和复现脚本位于 `artifacts/interface_controls_20260912/`。

新增脚本：`scripts/audit_device_interface_controls.py`。本次最终完整运行 20 个单日 EP 24.1.0 仿真：天津默认 3 天模板与 Berlin 模板，各 10 个控制条件；均压缩为 2007-07-01，统一使用天津天气，只检验接口，不验证 Berlin 气候适配或完整策略效果。

脚本通过 AST 提取作者原 `_FamilyLoop.init`、`_write_appliance_actuators`、运行日期生成函数和空调可用性注入函数，不改其函数体；直接输入确定的功率/温度指令。它不生成模型规划，网络连接被测试进程禁止，收费 API 调用为 0。完整配对规划的效果不能由这些接口测试代替。

| 对照 | 天津与 Berlin 结果 |
|---|---|
| 原资产，四设备全零 vs 非零 | 四句柄均 -1；144 个十分钟建筑电表值逐项完全相同 |
| 诊断修复，四设备全零 | 四接口有效；建筑电表与原资产关闭时完全一致 |
| 修复后四设备 18–19 点半功率 | 分别计量 1.00、0.75、1.50、0.10 kWh |
| 同样半功率移到 20–21 点 | 电量不变，六个十分钟计量区间均后移两小时 |
| 四设备额定功率一小时 | 分别 2.00、1.50、3.00、0.20 kWh |
| 原 EV 半功率一小时 | 两模板均 3.50 kWh |
| 热水器：40°C 对照 vs 18–19 点设 65°C | 天津 5.823 → 6.885 kWh；Berlin 3.043 → 4.821 kWh |
| 空调：24°C vs 28°C | 天津制冷 19.356 → 3.013 kWh；Berlin 22.079 → 10.786 kWh |

诊断修复刻意使用 `Fraction Lost=1` 排除室内热增益，以独立验证电气连接；它不是建议部署的热参数。此条件下，新增建筑电量也与四设备合计严格相等。此前候选采用旧模型热比例，因会引起空调响应，建筑总差额不应直接等同设备电量。两组实验的物理假设不同，不应混用。

本次结果：[interface-controls-results.json](interface-controls-results.json)。原始 SQL、逐步指令、每份 IDF / 天气哈希在 `artifacts/interface_controls_20260912_final/`。早期脚本调试失败目录不是通过结果。此前四次真实原生 no_dr 入口测试及 50 个任务的资产准备追踪见 [MAINLINE_AUDIT.md](MAINLINE_AUDIT.md)。

## 在原项目上怎样提最小 PR

1. **保留当前执行代码、规划器和动作格式。**它们已经发出四设备功率，不需要重写规划、增加规则或另造一个电量估算器。
2. **补齐共享默认资产的动态接口。**在 `experiments/models/family_home/` 的 `family_simple_3day.idf`、`family_simple_7day.idf`、`family_simple_14day.idf`、`berlin_family_geg_final.idf` 各添加四组 `Schedule:Constant` + `ElectricEquipment`。名称严格匹配现有 writer，功率分别 2000/1500/3000/200 W，Fraction 范围、日程初值 0，连接原 living zone，避免重复负荷。放在对应对象区并注明字段，不能直接使用当前审计补丁的尾部单行排版。
3. **明确室内热增益参数。**与作者确认使用何种潜热、辐射、散失比例，特别是 Berlin；旧天津模型只提供候选依据。零室内热的诊断对象用于证明接口，不能未经说明变成正式建筑参数。不恢复旧家电热水支路。
4. **随 PR 附回归测试和复现。**测试四模板对象完整、有效句柄、零输入无新增负荷、逐设备电量、移时电表、既有 HVAC/EV/EWH 控制。资产选择测试保证 EB、no_dr、所有对比方法用同版修复资产。可增加一次性缺句柄诊断，避免静默漏计；这属于接口诊断，不是新增计划合格性规则。

直接补共享默认 IDF 是当前最小、最容易审核的做法。如果作者更希望运行时注入，应建立一个共享资产准备函数，再让正式入口、独立 EP 训练环境和可选 EP 预测器复用；只在 EB 或问卷专用入口注入，不足以修好原项目的全部使用路径。两种方案选一套，不能重复追加。

当前 [candidate-assets.patch](candidate-assets.patch) 是可复现候选，不宜原样提交：仍需确定热参数、完善类型限制和对象排版、增加回归测试。本文及 Issue 草稿均未发布，未修改原仓库跟踪文件或部署新参数。修复后的 benchmark 需记录资产版本；完整方法结果和 PPO 检查点适配尚未重新验证，不能宣称原论文排序已经复现。

复现本次最终接口测试：

```bash
python3 scripts/audit_device_interface_controls.py \
  --upstream /path/to/author/EnergyBridge \
  --ep-root /path/to/EnergyPlus-24-1-0 \
  --output /path/to/new-empty-directory
```
