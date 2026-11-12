# EB A/B 执行一致性与整份计划奖励

本模块解决六类电器的完整程序和会话语义。2026-11-09 用户确认：reward model 看一整份用电计划或完整运行结果后评分，与展示仿真后果的正式问卷对齐。

## 当前边界

隔离分支完成了规则修订、反例与公开合成计划的原生回放。V9 新1000户的日期化世界、A/B及同版本物理后果尚未生产；不能把本模块的通过写成正式问卷数据集通过。

旧版回放入口保留。新版须使用 `unified.candidates.generate_household_day(context, case, manifest_sha256, ..., native_appliance_source_path=...)`，输入必须已经由日期化世界适配器构造，并携带冻结家庭的内容哈希。该入口先读取所选原生设备源码，核对已回放的版本哈希，强制绑定家庭，随后先验证 A，再枚举与验证 B。带V9来源标记却缺少执行合同的输入直接失败；`compact_plan` 不会将旧上下文标成已对齐。此入口不代替尚缺的日期化世界适配器。

## 生成规则

- 日常A只由家庭生活与真实服务需求生成，不读取B、VPP价格收益、结果或真人答案。
- 洗衣、烘干、洗碗为完整程序：任务身份和时长固定，一台设备同一时刻只做一个程序；已开始的任务不重排。烘干保留同一衣物的洗涤前置服务。
- EV在V9单段策略下，每个明确补能会话保持连续。相邻十分钟记账行可以合并，真实中断不能隐藏。停车区间只是机会，不额外制造需求；离家和已声明服务合同决定SOC要求。
- EB原生smart/显式充电窗口会避开整个VPP。只有明确声明该策略时才能表达相应暂停，不能任意暂停十分钟再恢复。是否改变EV策略由实际A/B指令比较决定，不依赖说明里是否写了EV改动。
- AC使用温控指令；WH使用温度与预热窗口。底层温控器的运行启停不等于用户反复安排开关。
- 人工操作保留身份、必要时长、权限和可用窗口。V9原始生活时刻不改写；十分钟操作网格只向原窗口内部收缩。
- 守门直接从实际命令推导执行，再检查候选声明的曲线。服务风险与机械错误分开；机械检查通过不代表已经通过家庭硬服务和EnergyPlus验收。

## 验收顺序

1. 冻结家庭、日期、设备参数、房型/天气、服务需求与初始状态，来源能够追溯。
2. 日期化A满足人工安排、完整程序、共享资产和补能要求；冻结后不随B变化。
3. A/B都须映射到EB主方法可表达的完整程序、充电模式/窗口和温控参数，并经过主方法校验与实际调用。不可执行候选进入诊断；不额外套用RL基线的固定动作范围。
4. A/B的实际指令在目标EB版本中回放，程序与补能曲线一致。跨夜与版本差异必须覆盖。
5. 同一初始世界分别运行A/B，结果与各自指令、日期和模拟器版本绑定；完整服务终点包括跨夜程序及次日出行，不能在VPP结束时提前截断。
6. 问卷和reward model读取相同语义的家庭、整份计划与已核验后果。人体选择是标签，不进入计划生成器。只有完整材料才能进入后续训练。

整份计划/episode评分是已确认目标。每十分钟即时评分不属于本批数据验收口径。

## 可复现检查

公开反例：

```sh
python -B -m unittest benchmark.ab_generation.test_eb_alignment
```

使用已核验的上游 `appliance_sim.py` 原件回放公开合成A/B，需已安装当前求解器依赖：

```sh
python -B -m benchmark.ab_generation.check_native_replay \
  --source paper_pinned=/path/to/pinned/appliance_sim.py \
  --source server_rl_snapshot=/path/to/server/appliance_sim.py \
  --output /path/to/native_replay_report.json
```

此回放中的EV容量、SOC等为明确的合成测试常量，不是V9调查估计值；回放验证设备指令语义，不验证建筑热物理。报告保留所用源码blob、计划哈希及检查范围，不能把它替代正式批次的物理证据。

## 原始依据

- 论文对应提交：[`ShiftableAppliance`与`EVCharger`](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/energybridge/simulation/appliance_sim.py)。
- [`RL动作解码与应用`](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/baselines/rl_energyplus/environment_pref_v2.py)。此处8维动作范围属于RL基线，不是本阶段A/B数据生成的验收约束。

上游源码未打包进本模块。服务器RL快照与论文提交源码不同，最终生产必须锁定实际目标版本。

## 2026-11-09 跨夜复核

服务器原RL快照会在午夜截断未完成程序，九个公开跨夜反例均失败；论文对应设备代码九个均通过。本轮在服务器私有隔离副本应用上游完整程序修复，九个均通过，修复后文件与论文对应原件字节一致。原运行环境未修改，副本未部署。

新版家庭入口只接受已核验设备源码的实际文件哈希，当前为 `be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9`。不能传入一个“支持跨夜”的自声明标志来绕过。旧服务器源码哈希不被新版入口接受。后续物理runner仍须核对实际加载的是该版本；此预检本身不等于物理runner已接通。

## 主方法调用为本阶段目标

2026-11-09用户纠正：生成数据以EB主方法计划和电器调用对齐为准。后续reward model接入RL的需求保留，但RL基线的固定动作范围不构成本阶段数据门槛。正式验收须走主方法计划校验与实际动作应用；当前仅完成的底层类回放不足以宣称主方法整链路已通过。

来源：[主方法电器动作应用及提示合同](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/experiments/benchmark/family_runner.py)，`_adaptive_v3_apply_appliance_actions`及EV参数说明；[主方法计划验证](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/energybridge/harness/planning.py)。

日常A按普通生活服务场景验证，响应B按其声明的VPP场景验证；二者使用同一套电器调用语义，不用B的削峰约束反向修改日常A。
