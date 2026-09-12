# 作者正式主线复核（2026-09-12）

这次先按作者声明的入口追踪，再检验此前的接口判断，没有预先套用我们网站的执行方式。作者仓库 main 在核对结束时仍是 `2b17ae63e613da776c93e900f5dace50d63a88a8`。原仓库工作区保持干净，无 PR/Issue 提交，无线上变更，无付费模型调用。

结论：此前的接口缺口判断在当前公开正式主线中仍成立；但“EB 没有电器接口”“整个项目不执行电器”“所有结果都错误”都不是准确结论。原生电器模拟参与了任务、约束、部分评估与规划，缺的是其中四类电器进入 EP 建筑电表的绑定。项目也不是只有一条入口、一个房屋模板或一套永久不变的控制配置。

## 1. 哪条是正式主线，依据是什么

依据为根 README 的 **Reproduce the experiments / primary paper-facing entry points**，以及 `reproducibility/README.md` 的第 2、3 节，再逐层核对实际调用。

| 路线 | 实际入口 | 定位 |
|---|---|---|
| 当前正式主实验 | `run_main_benchmark_from_scratch.sh → run_household_matrix.py → run_multi_user_household.py → family_runner.run_family_agent` | 两地区 × 五个家庭 × 五个方法，共 50 次七天仿真 |
| 当前正式容量实验 | `run_capacity_reporting_from_scratch.sh → run_daily_dr_memory_matrix.py → run_multi_user_household.py → family_runner.run_family_agent` | June/July 各七个配置事件 × 两地区 × 五家庭 × 六方法，共 840 次独立单日仿真，含 no_dr |
| 单 persona 快速验证 | `run_persona_json.py → family_runner.run_family_agent` | README 明列的 quick start 和单 persona 实验，不能代替多成员主实验入口 |
| 早期包/交互演示 | `examples/run_agent_loop.py`，以及 `EplusEnv → build_energybridge_graph` | `docs/ARCHITECTURE.md` 明确标 Stage 1；存在 mock 控制/早期真实 EP 适配，正式矩阵不经过此图 |
| 旧 family/office 对照 | `run_benchmark.py` | 旧 PMV/agent 等演示矩阵，不能用来代表当前五方法主实验 |

`energybridge/agent/graph.py` 存在不意味着正式矩阵会调用它。运行入口和调用链优先于目录名或旧架构文档。

作者 wrapper 的主实验明确设置 2025-06-01、七天、每日 18–19 点。容量实验则明确把每个事件切成独立一天；不是一个月一次连续规划，更没有“固定第四天比较”的要求。MPC horizon=6 表示六个十分钟步，即一小时。

## 2. 家庭 JSON 真正怎样进入

正式多成员路径：

```text
家庭 JSON（共享电器、关系、成员引用）
  ├─ load_household_member_personas：读取每位成员 persona 和日历
  ├─ _build_physical_household_persona：创建执行器所需的聚合家庭对象
  │    ├─ household.appliances → 一套家庭共享设备
  │    ├─ 成员日历 max 叠加 → 家庭在家时段 → IDF People 日程
  │    └─ 成员角色、偏好等 → 模拟家庭同意/反馈侧的上下文
  └─ IndependentMemberRoleplay：成员分别表达偏好、分别评分
       → 汇总为控制器反馈；事后评分取算术平均
```

五份家庭配置的成员数依次为 4、5、3、4、4；都配有完整共享电器组合。它们是实验样本，不是控制器只支持的五个硬编码类别。加载器支持 JSON 路径；但原多成员加载器要求至少两名成员，且成员 persona 通过文件引用加载，不能把任意问卷 JSON 原样塞进去就宣称接口完全等价。

需要特别区分两种函数：`households.py` 提供通用 `build_household_persona`；正式 `run_multi_user_household.py` 实际调用的是自己的 `_build_physical_household_persona`。仅看前者会误读正式聚合政策。家庭 JSON 中某些文字写着 discussion/consensus，但正式事后评分代码 `IndependentMemberRoleplay.score_event` 实际采用独立成员评分算术平均。

对于当前 EB 方法，完整隐含 persona 不直接当成规划提示。正式入口对 `controller_method == agent` 改用“从可观察访谈、日历和反馈推断”的提示；初始化时先让模拟家庭回答简短 onboarding，再把回答送进 V3 household profile / memory。设备、可观察日历、实时状态另行进入规划上下文。

所以“填用户信息替代预设家庭”可行，但应替换这几个输入边界；不能把隐含评分权重等全部交给规划器，也不需要强制把真人归到五个预设之一。

## 3. 当前 EB 规划与执行逻辑

当前 wrapper 默认 `agentic_v3`，代码内部规范化为 `adaptive_v2`；V3 是内部 profile/memory/planning 合约版本。`paper_v1`/`legacy_v1` 是显式兼容模式。配置不同，即使都叫 EnergyBridge，行为也不等价。

`family_runner.run_family_agent` 启动一次连续 EP 运行，通过 Python callback 在仿真时间中推进：

1. 初始化真实 EP 状态和 ApplianceSuite，加载电价、VPP 事件及家庭输入。
2. EB 方法进行模拟 onboarding，建立可观察家庭模型、因果阶段记忆和操作知识。
3. 在每日规划点、VPP 边界、模型指定的 next_check 及原生检查点触发决策；读取温度、占用、电表和设备状态。
4. 正式多成员回调让每位成员表达当前偏好并汇总；当前模型也可提出一次与决策相关的追问。
5. EB 基础模型生成候选并自己选择。原生代码执行运行约束检查、固定负荷/电价证据核算、必要的语义重规划或回退；MPC 可以作为咨询候选，而非默认静默替换合法模型选择。
6. 模拟家庭接受检查决定执行 VPP 提案还是回退到日常方案。当前 adaptive 检查由一个 role-play 模型结合整个家庭上下文判断；不能误说成它与事后“成员评分平均”是同一步。
7. 动作先进入 ApplianceSuite；每个仿真步通过 `_write_appliance_actuators` 写入 EP。HVAC 另行写温控/可用性。
8. EP 继续推进；事件日结束后评分，记录 proposal/validation/consent/execution/outcome 和反馈，为后续事件提供记忆。

不是“一个家庭 JSON → 一次 LLM → 完整固定方案 → 再跑一次 EP”这么简单。几次模型调用并不等于几次 EP 冷启动。日常 no_dr 与 agent 的两次运行是实验对照结构；每条 agent 运行内部可多次控制。

no_dr 在相同执行器里用原生随机日常任务规则，不进行 EB 规划或模拟评分。其 ApplianceSuite 不接收 VPP 窗口用于任务避峰；不应以我们自拟的普通时刻替代它后仍称原生 no_dr。

## 4. Baseline 是否走另一套建筑

正式 `run_household_matrix` 的五个方法是 EnergyBridge、HEMA、MPC Dynamic、Rule+MILP、PPO。各自决策方法不同，但从多成员入口传入同一个 `family_runner`，共享输出侧 EP 建筑及末端电器写入。

| 方法/子流程 | 控制策略或模型 | 末端 |
|---|---|---|
| EB | 当前 adaptive profile + 模型候选/选择/证据复核 | 原生 ApplianceSuite + EP |
| HEMA | 外部固定 HEMA checkout，经本仓库 bridge 转动作 | 同一 family runner |
| MPC Dynamic | 默认区域 5R3C 动态预测与 MPC 选动作 | 同一 family runner |
| Rule+MILP | 确定性控制/调度 | 同一 family runner；此处仅核对影响，不加入我们的问卷 |
| PPO 推理 | 按地区加载 checkpoint，经策略适配器出动作 | 同一 family runner |
| MPC 可选 EP scorer | `ep_predictor.py` 的独立 rollout | 复用相同电器写入；不是当前默认 MPC 预测模型 |
| PPO 训练 | EP 环境和 dynamic 环境均存在 | EP 训练有独立写入函数；动态训练不直接使用本层 EP 绑定 |

实际执行了全部 50 个正式任务的家庭读取、日历合并、文件生成与参数传递，到 `run_family_agent` 边界截停。对每一个 household×region 分组，五方法生成的 IDF 哈希完全一致。没有对这些任务发模型请求或声称完成五方法成绩复现。

## 5. 正式路径最终使用哪些建筑

`run_multi_user_household.main:938` 实际调用 `run_persona_json._prepare_run_assets`：

- 天津七天：`experiments/models/family_home/family_simple_7day.idf`。
- 德国：`experiments/models/family_home/berlin_family_geg_final.idf`。
- 天津单日容量实验：以 `family_simple_3day.idf` 为模板，生成一日 RunPeriod。
- 资产准备修改仿真日期/时段、注入家庭占用日程并选择天气/电价，没有增加四类设备对象。

各次运行使用新生成的 `_run_assets/...` 文件，不能只看默认常量。此次审计也核对了生成文件与实际传给 EP 的路径，而非仅搜索静态模板。

这排除了“正式入口会在别处补齐设备，只是测试没走到”的假设。在核对的公开默认路径中没有找到该补齐步骤。用户自行提供的外部 IDF 不在此结论范围内。

## 6. 指标是否在别处把电器功率加回来

不是所有指标都来自同一个模拟层：

| 指标 | 真正来源 | 四设备缺 EP 绑定时 |
|---|---|---|
| 任务完成、是否在 VPP 内运行、EV SOC 等 | ApplianceSuite 的任务/状态结果 | 仍可有结果；不能据此认定 EP 已计量对应设备 |
| 规划前候选固定电器成本/重叠窗口 | 候选时间 × 设备功率 × 电价等核算 | 可用于模型证据，不等于执行后建筑电表 |
| 建筑总电量 | callback 读取 `Facility Total Electricity Demand Rate` 积分 | 不含未连接设备的动态用电 |
| 事后电价成本 | `compute_price_metrics → read_facility_meter_steps`，读取 EP `Electricity:Facility` | 没有另把四设备 Python 电量加回 |
| VPP 窗口 actual_kwh | runtime 计量，并在结束后用 EP meter 窗口结果回填 | 同样受绑定缺口影响 |
| no_dr 对照削峰 | `counterfactual_baseline.py` 的 baseline_kwh − actual_kwh | 用双方窗口计量，并非补算遗漏电器 |
| accepted_effective 等派生指标 | 原计量加服务未完成的等价惩罚 | 是评价量，不是修复设备电表的真实能量补记 |
| 事后满意度 | 成员 role-play 同时看温度、电量、任务情况等，最后平均 | 输入混合物理和任务模拟，不能统称全错或全为 EP 事实 |

因此此前“有任务时间轴但 EP 电量未跟随”的解释成立；但“电器信息完全没有进入系统”的解释应撤回。

## 7. 正式入口的实际证据

在未修改作者源文件/IDF、禁止所有 Python 网络连接的情况下：

- 实际构造并执行 50 个主实验任务的准备部分，验证五方法资产一致性。
- 实际构造 840 个容量任务命令，均为独立一天；另实际执行一个容量任务的正式准备部分。
- 用正式多成员入口实际跑了天津/德国各一个七天 no_dr 参考运行，及容量生成器产出的天津/德国各一个单日 no_dr 任务：**共 4 次 EP，全部 exit=0，模型调用=0**。七天 no_dr 是同入口参考试验，不是主矩阵五方法之一。
- 四次运行 washer/dishwasher/dryer/refrigerator 句柄全部为 -1；Python 实际最大功率分别为 1.5/1.2/2.5/0.15 kW。EV、热水器句柄有效。
- 作者 `run_release_checks.sh` 全部通过（11 个测试和公开数据验证）；另选取家庭、占用、电价、adaptive planning、MPC、PPO 接口的 113 个测试通过。未声称跑完全仓库测试或五方法真实模型比较。
- 此前独立的 24 次设备脉冲实验继续作为“输入变化是否进入电表”的机制证据，不能代替上述正式入口追踪。

原始数据：[mainline-verified-results.json](mainline-verified-results.json)。可复现脚本：项目 `scripts/audit_author_mainline.py`。完整生成 IDF、结果、meter、trace 在 `artifacts/author_mainline_20260912_v2/`；运行日志 `/private/tmp/eb-author-mainline-runtime.log`。作者代码工作区最终仍干净。

## 8. 对我们项目的结论与下一步

我们目前确实复用了正式主线的 `family_runner.run_family_agent` 控制核心，不是早期 LangGraph 演示；但并没有原样运行完整 `run_multi_user_household.main`。

已接受的研究改动包括：真人问卷进入 observable onboarding/家庭设备/占用；不用预设成员代填；原生开关绕过模拟接受分支；最终由家庭代表评分；单日 no_dr/agent 对照；额外保存展示快照及真人标签。这是“复用原生控制核心的真人数据采集流程”，不是原论文 consent-aware benchmark 的一比一复现。

还有事实层面需要持续明确：当前网站占用由家庭问卷映射，而非原预设成员日历 max 叠加；成员描述作为问卷证据保留，不执行原 independent-member 模拟发言；未经采集的中途追问返回未知。它们属于输入/家庭交互替换，不能含混地称所有上下文完全相同。最终训练目标仍是家庭代表的真人接受与评分，不是给每名成员伪造标签。

当前可下的结论是：**公开正式主线存在所述设备—EP 绑定缺口，值得向作者反馈；最小修复的物理参数和全方法回归范围仍需谨慎确认。** 不把接口缺口直接推成原论文排名无效，也不能断言此前我们“两份安排一样”全部由它导致。

候选资产补丁继续冻结，不提交、不部署。下一步先把“正式入口的复现 + 结果来源 + 未覆盖边界”给作者核对，确认是漏入库、缺生成步骤还是预期的分层建模。作者若确认需在 EP 计量，则补丁需同时应用各方法相同资产，并重新验证；不能只改我们 EB 一侧后混用旧基线或旧 PPO 结果。
