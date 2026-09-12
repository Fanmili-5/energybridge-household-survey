# 天津住宅：EB 完整设备接口 v1

`family_all_appliances.idf` 是作者 `family_simple.idf` 的独立派生文件，补齐 **EB 当前支持的七类设备**。原始住宅和 EB 规划算法保留。它不是另一栋住宅，也不是参与者真实住宅的重建。

## 作者原来如何构建

作者的 `Family_Model/envelope_retrofit_report.md` 第 8–10 节记录了实际修改：

1. 从 EnergyPlus 24.1 的 `SingleFamilyHouse_HP_Slab.idf` 另存住宅模型，保留一个居住热区、一个阁楼及原热泵系统。
2. 调整墙体、窗、楼板等材料和构造，接入天津气象、设计日和月地温，修复地面边界及排风节点。
3. 为 EV／电热水器实验删除美国样例中的旧静态家电负荷，以及洗衣／洗碗热水支路；加入 EV 充电器和热水器控制接口。

本版本延续第三步的外部控制方式，给正式 EB writer 已经支持的四类家电补齐动态接口。没有恢复旧静态家电日程或洗衣／洗碗热水支路。

## 设备如何接入

| 设备 | IDF 表达 | 由谁决定运行 | 本版本修改 |
|---|---|---|---|
| 空调／热泵 | 原 HVAC、冷热设定点日程 | 原 EB 控制器 | 按作者准备函数接入 HVAC 可用性日程 |
| EV | 原 `EV_Charger`，7 kW | EB 的 EV 状态与充电控制 | 保留 |
| 电热水器 | 原 120 L 分层水箱及供水系统 | EB 写设定温度，EP 求解水箱状态 | 保留 |
| 洗衣机 | `ClothesWasher_Appliance`，2 kW 设计功率 | EB 洗衣任务模型 | 新增负荷与功率比例日程 |
| 洗碗机 | `Dishwasher_Appliance`，1.5 kW 设计功率 | EB 洗碗任务模型 | 同上 |
| 烘干机 | `ClothesDryer_Appliance`，3 kW 设计功率 | EB 烘干任务模型 | 同上 |
| 冰箱 | `Refrigerator_Appliance`，0.2 kW 设计功率 | EB 冰箱基荷模型，不是可移时任务 | 同上 |

设计功率用于把 EB 输出的 kW 换成 EP 日程比例，并不表示全程满功率运行。四类新增家电的功率比例日程默认为 0；直接单独运行 IDF 不会自动产生洗衣等任务。家庭信息仍须经过现有 EB 准备与控制流程。

```text
问卷 → 家庭 JSON → 原 EB 任务／控制模型
                         ↓ 每个仿真步写功率或设定温度
                  完整设备 IDF + 天津 EPW
                         ↓
                  电耗、室温、水箱状态
```

两份比较方案必须采用相同设备参数和天气，只改变各自的控制动作。现有网站运行时已经在生成的 IDF 副本中执行同样的补充；本目录把它保存为可单独检查、复现的模型资产，生成脚本不切换或启动线上服务。

## 模型假设

- EnergyPlus **24.1.0**；默认天气文件运行期为 **7 月 1 日，一天，10 分钟一个区间**。2007 年仅用于与现有 EB 一致的星期设置；天津 CSWD 是典型气象，不是实测 2007 年天气。EP 内部仍需要预热和设备 sizing。
- 四类新增家电采用 EnergyPlus `ElectricEquipment`，承接电功率并产生室内热增益。它们没有新增独立的压缩机、洗涤机械或用水物理模型。
- 热增益比例继承作者 `original_model.idf`，没有把所有耗电都强行变成室内热量；这些比例尚未针对参与者校准。

| 家电 | 潜热比例 | 辐射比例 | 不进入该热区的比例 |
|---|---:|---:|---:|
| 洗衣机 | 0 | 0.80 | 0.20 |
| 洗碗机 | 0.15 | 0.60 | 0.25 |
| 烘干机 | 0.05 | 0.15 | 0.80 |
| 冰箱 | 0 | 1.00 | 0 |

这补齐的是 **EB 已有负荷模型到 EP 电表与热平衡的连接**。它不自动支持电视、电饭煲等 EB 当前没有调度模型的所有家电，也不提供逐房间温度。完整设备接口验证与真实住宅校准是两个不同问题。

## 复现与证据

本次 **17 次真实 EP 仿真通过**，全部 0 Severe／Fatal，模型 API 调用为 0。四类家电电量、功率倍增与两小时移时均实际生效，EV／EWH／HVAC 有正响应；新资产与当前动态补接方式在 8 组输入下输出逐值一致。零输入时，新增负荷不改变原模型电量或室温。

通过不表示零 Warning 或完成住宅校准。零输入案例中，原模型完成摘要有 2619 次 Warning，新模型 2623 次（重复报告也计入）；新增四条为功率日程沿用现有 runtime 的空 `Schedule Type Limits Name`，其余来自继承的原模型。原始日志与逐案例计数保存在验证目录中。

在项目根目录运行（不使用模型 API）：

```bash
python scripts/build_complete_household_idf.py --check
python scripts/verify_complete_household_idf.py --ep-root /Applications/EnergyPlus-24-1-0 --output artifacts/complete_household_idf_rerun
```

不加 `--check` 可重新生成 IDF 和 `manifest.json`。构建会验证源文件哈希，并拒绝写入原作者目录。设备绑定与当前运行时补充函数保持幂等。

- `manifest.json`：原作者提交、原始 IDF／天气／writer 哈希、新模型哈希、设备名称、功率与热增益来源。
- `validation.json`：本次真实 EP 验证结果；固定指令测试，不评价 LLM 规划能力。
- 原始逐步输出：项目 `artifacts/complete_household_idf_20260912/`，不提交仿真大文件。

来源：[作者改造记录](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/Family_Model/envelope_retrofit_report.md)、[EnergyPlus 24.1 ElectricEquipment](https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-internal-gains-people-lights-other.html#electricequipment)。
