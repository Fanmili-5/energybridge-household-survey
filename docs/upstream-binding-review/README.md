# 电器到 EnergyPlus 的连接：上游核对与候选修复

最新补充：[EXECUTION_INTERFACE_REVIEW.md](EXECUTION_INTERFACE_REVIEW.md) 聚焦“EB 规划后 → EP 执行”的断点，包含原代码固定计划移时测试、20 次真实 EP 正负对照，以及在原项目上修复的最小范围。作者旧模型删除静态家电有明确设计记录；本审计确认的是当前多电器动态接口与默认资产不匹配，并非认定那次删除本身是错误。

后续已按作者正式复现入口完成独立追踪，见 [MAINLINE_AUDIT.md](MAINLINE_AUDIT.md)。该文区分正式矩阵、单 persona 快速入口和早期 LangGraph 示例，并给出 50 个主任务的准备追踪、4 次原始多成员入口参考仿真与指标来源。以下 24 次脉冲实验仅作为连接机制证据。

结论：作者当前默认家庭模型确有四类电器的写入缺口；已用实际 EP 复现。
本目录的多建筑上游候选补丁尚未部署或提交，不代表全部 baseline 已验证。问卷 v3.2 已单独修复生成的天津运行资产，见 [当前部署说明](../../deploy/SCHOOL-COMPUTE.md)；原仓库仍保持不变。

## 核对对象

- 作者仓库：https://github.com/Agentic-Intelligence-Lab/EnergyBridge
- main 提交：`2b17ae63e613da776c93e900f5dace50d63a88a8`（2026-08-28）。不是用户的旧 fork。
- 独立干净 checkout：`/private/tmp/energybridge-author-latest-20260912`，没有修改其跟踪文件。
- `family_runner.py:2624` 读取四个 `Schedule:Constant` 执行器；`:10759` 仅在句柄不为 -1 时写入；`:14809` 每个仿真步调用电器模型及写入函数。
- 缺口包括 washer、dishwasher、dryer、refrigerator。不能将这个结论扩展为“整个 EB 不运行”或“所有电器接口均缺失”。

## 实验结果

对天津 3/7/14 天模板、Berlin 模板各做 6 次单日 EP 24.1 仿真，共 24 次，零 LLM 调用。
所有模板统一使用天津天气，仅验证电气连接，不验证德国气候、完整多日规划或论文效果。
使用作者原函数的 AST 提取副本，无改写函数体、无加载训练器或模型 API。

| 检验 | 结果 |
|---|---|
| 原建筑，四电器关闭 vs 输入一小时固定功率 | 四句柄均为 -1；EP 整条建筑电表曲线完全相同 |
| 候选建筑，四电器输入为零 | 四句柄均有效；建筑电表与原始关闭曲线完全一致 |
| 候选建筑，18–19 点输入额定功率的 50% | 洗衣 1、洗碗 0.75、烘干 1.5、冰箱 0.1 kWh；逐设备与输入吻合 |
| 同样输入改到 20–21 点 | 逐设备电量不变，六个十分钟负荷区间准确后移两小时 |
| 使用 RL 的独立写入函数 | 四设备电量与原生写入函数一致；不声称完整 RL 策略/训练已验证 |

天津 3 天模板压缩为单日后：原始关闭/开启均为 35.417836 kWh；候选关闭仍为 35.417836 kWh；开启为 39.067157 kWh。新增设备电量合计 3.35 kWh，建筑总差额还包含设备发热带来的 HVAC 响应，不能要求总差额恰好等于 3.35。

RL 写入函数也设置空调温度，因此整栋建筑电量与原生写入试验不同；只对四台设备的表计作一致性断言，避免把不同控制策略当成相同条件。

结果摘要：[verified-results.json](verified-results.json)。完整 SQL、逐步指令和日志位于项目 `artifacts/upstream_binding_review_20260912_v2/`，不进入公开补丁。
首次实验在 Berlin 的 19:00 浮点边界暴露测试脉冲多发一步，已将测试时钟四舍五入至 8 位后重新完整运行通过；未改作者调度逻辑。

## 影响范围：不能只修 EB 一条方法

| 路径 | 代码关系与修改影响 |
|---|---|
| 当前家庭 benchmark 的 EB、HEMA、MPC Dynamic、Rule+MILP、PPO、no_dr | `run_persona_json.py` / 多成员入口进入 `run_family_agent`；共享末端写入。必须使用同一版本建筑，不能只给 EB 补负荷。这里只审计 Rule+MILP 的兼容面，不把它加回我们的问卷流程。 |
| MPC 可选 `ep_predictor.py` | 引用同一 `_write_appliance_actuators`。仅增加原字段对应对象即可供此写入函数使用，但完整预测 rollout 尚未回归。 |
| 当前 MPC 默认预测 | `planner.py` 使用区域 5R3C 动态模型；不能把“EP 可选预测器受影响”说成所有 MPC 内部模型都缺 EP 接口。需要检查模型与新 EP 负荷的一致性。 |
| PPO 的 EP 训练环境 | `environment.py`、`environment_pref_v2.py` 各有独立 `_write_actuators`，仍依赖相同句柄。已测试 v2 写入函数，不等于已训练/评价 PPO。 |
| PPO 动态训练环境 | `environment_dynamic_v2.py` 使用动态模型，没有直接走这层 EP 设备写入；需要检查训练到 EP 评估的差异。 |
| 旧 PMV/office/longterm 路径 | 不应按当前家庭多电器主路径一并修改或声称覆盖。旧 `run_benchmark.py` 的 PMV/agent 调用不传相同家庭电器配置，不能直接用作修复后的公平比较。 |
| 自定义 IDF / 旧 Family_Model 目录 | 本候选不覆盖，不自动追加设备。已有静态设备必须先防重复计量；不能一律“缺名字就添加”。 |

## 候选补丁的边界

[candidate-assets.patch](candidate-assets.patch) 仅给四份当前默认模板增加各四组 `Schedule:Constant` + `ElectricEquipment`，`git apply --check` 已通过。未修改任何规划器、评分器、用户接受逻辑、baseline 规则或天数。

- 设备名称、设计功率严格取作者 `_APPL_DESIGN_W` 及句柄名称。
- 初始日程全部为 0，只有接到执行指令才用电。
- 热量的潜热/辐射/散失比例取作者 `original_model.idf`；这是一项明确的候选建模决定，尤其迁移到 Berlin 时需要作者确认。接口缺口可确定，热参数正确性不能仅凭电表测试确定。
- 候选仅限已核对的缺设备模板；脚本遇到同名旧设备/日程会拒绝追加，避免重复计量。
- 本次未更改已有 EV、热水器、空调、功率截断、回调时序、任务运行规则。

## 是否给作者提 PR

建议先提交可复现 Issue，询问是否遗漏了未入库的设备模型/生成步骤，以及建议的内部热增益配置；随后提供资产层的最小 PR。不要将网站、问卷或我们的人类评价边界混入上游 PR。

正式 PR 前还需：确认热参数；在作者认可的所有使用模板/资产生成路径接入；对相同物理条件的各方法做回归；对 PPO 模型与新环境的差异注明是否需要重新训练；明确旧 benchmark 结果不能和修后结果混用。并不需要付费调用所有 LLM 来证明这个电气缺口，但当前 24 次试验也不等于全部 benchmark 回归。

问卷 v3.2 已在两条比较路径使用同一套生成的天津资产修复，记录资产哈希，具体范围见当前部署说明。这里的四模板上游候选补丁与那项问卷修复不同，尚未提交作者或完成所有 baseline 回归；不能把两者混为一项已完成的上游修复。

## 重现

```bash
python scripts/audit_upstream_appliance_binding.py \
  --upstream /path/to/author/EnergyBridge \
  --ep-root /path/to/EnergyPlus-24-1-0 \
  --output /path/to/new-empty-output-directory
```

脚本只用本地 EnergyPlus 和 Python 标准库，不需要 API 密钥；不修改上游工作区。输出目录必须尚不存在，避免覆盖实验。
