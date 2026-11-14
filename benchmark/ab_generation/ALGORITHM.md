# 调查约束的家庭用电决策情境生成

本模块提供从调查源池或已冻结家庭，到日常A、EB原生候选B、覆盖选题及当前索引封存的完整可复用算法。它输出后续IDF与问卷所需的计划输入及证据；配对物理计算和真人标注继续单独验收。

## 算法1

输入：八国支持来源或其冻结家庭；国家与EB六类配额；参考生活/设备规则；每户十个日期；固定事件；种子和各阶段预算；固定原生电器模块。

1. 规范化逐户调查，保留同户字段关联、原值与来源状态；按最大余数法和整数配额确定国家×角色数量。
2. 按相容性和固定种子选取不重复源户，在源约束下实例化角色与参考周；整数规划分配4—6类控制组合，AC必控、F含EV，平衡组合覆盖与实验增配成本。
3. 生成日常A：WM/DR/DW用CP-SAT安排完整程序；EV按给定停车与SOC执行原生连续充电；AC和WH使用明确参考规则。A不读取B、仿真收益或真人答案。
4. 固定A，在原EB动作与本批声明范围内枚举修改。先保留机制、联合任务数和必要的洗烘依赖，再进行有预算的IPOG-C式约束覆盖搜索；记录完整见证、已证无解和未探索。
5. 每日期选一个B，以整数规划平衡已见证联合任务数、其他覆盖与重复；登记选题前原始细分格。同角色跨国家共同补覆盖。
6. 对缺少完整见证的预声明格，按原动作域和记录的预算补候选；依原批次配方先补根动作、单步重选，再补洗烘依赖、仅额外候选重选，最后做有预算的联合重选。每个新B重新原生执行。
7. 校验冻结来源、每户十题、A未被改写、A/B内容哈希及执行记录；保存原索引和初选，生成当前索引、覆盖账本及物理交接文件。真人答案保持空值。

这些是分阶段目标，不声称一个模型全局联合优化所有家庭、设备和问题。

## 每阶段优化目标

- 家庭控制组合：在配额与覆盖约束下最小化加权实验增配成本及固定种子破同分。当前成本为100×增配数＋种子成本，不表述为严格字典序最少增配。
- A的程序排程：最小化根程序距离家庭参考目标的偏移、同批洗后等烘的等待及较小的种子破同分项。AC/WH/EV不属于这个程序CP模型的全局能耗优化。
- 初选B：优先覆盖已见证的联合任务数，再优化其他加权覆盖缺额和重复，最后固定种子破同分。
- 跨户重选：在不损失每户已有基础题型/取舍、不降低已达成跨国覆盖分数的前提下补缺。预算内可行解与已证明最优分开登记，不声称全局最优。

## 约束来源与接受标签

| 类型 | 内容 |
|---|---|
| 调查与来源 | 不重复源户；已观察字段保持身份；跨户匹配和实验补全单独记录 |
| 原生接口 | 固定到paper-v1-final/c58a2a7a；完整程序、实际检查时钟和六类动作映射 |
| 明确实验子集 | 每日完整任务、EV连续且完整补能、仅EV跨夜、4—6类且AC必控 |
| 软偏好 | 温度、便利、生活冲突和确认偏好可保留在B中，交给真人评价 |

连续完整补能等是本实验的受限提案空间，不代表原EB接口所有可能动作，也不把空间外请求称为物理不可能。B可能收益差、舒适变差或被拒绝。数值结果与人的标签分别存储。

## 生效参数与失败含义

- `GENERATION_REPAIR_CONFIG.json:A_deterministic_time`已从日常入口传入实际程序求解器；默认20。直接旧API调用仍保留显式默认5以兼容历史调用。OR-Tools确定性时间不等于固定墙钟秒数。实际预算记在每日输出的A_solver_execution；运行配置/代码另行固定，执行元数据不改写历史计划内容身份。
- 原生日常A要求程序目标已证最优，质量要求未降低。UNKNOWN返回search_unresolved；FEASIBLE返回feasible_not_proven_optimal；INFEASIBLE仅表示给定日期和声明程序域已证无解；MODEL_INVALID单独返回。失败收据保留原状态和原因。
- `COMPLETION_CONFIG.json`控制定向求解及每国/每格尝试预算；只扩大求解努力，不改变动作语法、家庭、A或覆盖分母。
- `--cohort-deterministic-time`控制联合补选；`--min-free-gib`用于运行资源保护。
- A_target_context_mode=frozen_v3是“直接使用已冻结家庭参考目标”的历史枚举名；不指定原生接口版本，原生动作/检查时钟仍固定到论文冻结版。
- 旧block_households仅用于旧assign接口；本配方按户初选后做跨户复核。handling_calendar_domain的人工装取变化不属于原生路径。
- 完整配方目前限定每户10题、10分钟网格、当地18:00—19:00事件；新国家、不同事件、其他题量须单独升级验收。

## 统一入口

主验收环境为Python3.14.3。完整链使用同一份依赖，避免混装旧模块的不同锁：

```bash
python -m pip install -r benchmark/ab_generation/generation-requirements-lock.txt
```

准备固定原生电器文件：取官方c58a2a7a提交的energybridge/simulation/appliance_sim.py；SHA256应为be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9。入口会校验它。该文件与家庭数据路径均显式提供，代码不依赖服务器目录。

公开合成演示（无需调查原件）：

```bash
python -B -m benchmark.ab_generation.generation_pipeline \
  --make-example-pool \
  --household-config benchmark/household_stage1/generator/configs/pilot96.json \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/appliance_sim.py \
  --start-date 2007-07-18 --workers 4 --out /path/to/new-demo96
```

这会生成96户×10题、完成两个补候选阶段、覆盖重选和封存。合成示例只用于软件与复现验证，不计作真实调查家庭或真人标签。

真实来源模式：

```bash
python -B -m benchmark.ab_generation.generation_pipeline \
  --data-config /secure/supported_source_paths.json \
  --household-config benchmark/household_stage1/generator/configs/production1000.json \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/appliance_sim.py \
  --start-date 2007-07-18 --workers 6 --out /path/to/new-source-cohort
```

来源配置与八份原件的版本要求见[家庭数据合同](../household_stage1/generator/DATA_CONTRACT.md)。也可给--pool提供已规范化源池，并继续用--data-config完成原件独立核验。

复用已验收家庭：

```bash
python -B -m benchmark.ab_generation.generation_pipeline \
  --households /secure/household_cases.jsonl \
  --expected-household-sha256 YOUR_FROZEN_SHA256 \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/appliance_sim.py \
  --start-date 2007-07-18 --workers 6 --out /path/to/new-native-cohort
```

此模式核对输入身份、唯一源记录和控制要求，不冒称重新核验全部调查原件。--reference-batch可在生成封存后比较另一冻结批次的逐题A/B计划哈希；比较结果不参与选题。

## 输出与复现

- PIPELINE_PRE_RUN.json、STAGES.json、PIPELINE_RESULT.json：代码/配置、每步命令、日志、成功和覆盖状态。
- households/：来源模式生成的家庭、配额、独立核验与重放记录；提供冻结家庭模式直接引用原件。
- native/：每户A、原始候选、额外候选、原生回放、初选及当前选择、覆盖账本、PAIR_INDEX和DATASET_MANIFEST。
- COVERAGE_TARGETED_SEARCH.json、COVERAGE_PROGRAMME_COMPLETION.json：补候选参数、完整请求见证和未完成项。
- PHYSICS_HANDOFF.json：当前计划身份和同源物理计算要求；未生成的建筑绑定/物理后果保持null。
- PIPELINE_FAILURE.json：保留失败阶段，失败输出不作为发布版本；原成功和失败文件不覆盖。

改变规模、源池、规则、种子或预算会得到新批次。联合补选固定变量、约束与集合遍历顺序，单线程并固定求解器种子；跨目录及不同PYTHONHASHSEED的实际计划哈希复现由CI检查。相同程序选择与代码/求解器版本、冻结输入有关；不承诺不同求解器版本的同分解逐字节一致。复现比较以实际A/B指令哈希为准，不以gzip时间戳或运行路径为准。

## 覆盖与科学解释

原始细分分母在选题前建立，不用已选或已生成候选反推。电器类、单设备细分、联合任务数和设备间互动分别报告。单设备细分覆盖不代表全部联合方案空间。

稀有格可竞争同一家庭日期；一天一题可能产生覆盖上限。未搜索或预算不足保留unknown，不推断物理不可能或居民拒绝。完整运行成功允许附带明确覆盖缺口，不为满格扭曲生活安排。

文献支持生活建模组织原则，具体生活钟点、温度和配额仍按来源/实验身份记录。本算法不声称学习了全球家庭真实联合分布；生活自然性需要独立人工检查，选题指标改善也不等于人类接受率提高。

## 方法构件与来源

- 家庭来源、EB角色和生活规则：[生成依据表](../household_stage1/generator/EVIDENCE_MAP.md)。
- 有预算的IPOG-C式覆盖基于Yu等，2013，An Efficient Algorithm for Constraint Handling in Combinatorial Test Generation：[NIST原文](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=913191)。
- 求解状态：[OR-Tools官方说明](https://developers.google.com/optimization/cp/cp_solver/)。
- 原生设备与时钟：[来源快照](paper_v1_clock_source.provenance.json)。
- IDF构造与原生环境：[物理模块](../idf_reference/README.md)。本入口不启动EnergyPlus、采集服务、训练或付费模型。

## 实现对应与扩量验收

| 阶段 | 公开实现 | 必查输出 |
|---|---|---|
| 调查源池、配额与家庭 | household_stage1/generator | 源键不重复、逐字段来源、配额与重放 |
| 参考日常A | household_routine_A.py、eb_primary.py、v9_date_adapter.py | 实际预算、求解状态、完整任务和生活目标 |
| 原生候选B | generate_native.py、unified/candidates.py | 原始动作域、细分分母、完整请求和原版执行 |
| 每日一题 | unified/selection.py | 一日期一个B、完整候选见证和选择凭据 |
| 根动作与依赖补齐 | candidate_completion.py | 两阶段搜索日志、预算和新增候选 |
| 同类跨国覆盖 | cohort_coverage.py、cohort_optimize.py | 原分母、保留基础覆盖、逐项缺口 |
| 当前批次封存 | seal_native_cohort.py | 当前PAIR_INDEX、A/B指令哈希、源和代码身份 |
| 全过程编排 | generation_pipeline.py | 全部阶段退出码、结果、物理交接文件 |

扩量按以下顺序验收：先核对新源池容量/身份与家庭重放；再以新目录运行完整配方；核对每户十题、实际原生执行、原始覆盖分母和负面取舍保留；最后对确切计划做独立物理及真人验收。修改源池、规则、种子、日期或预算必须新建批次，不覆盖已冻结批次。如需合并新旧批次，调用方须合并源键台账并跨批去重；只换种子不能保证没有源户重叠。

论文可称“调查约束、原生动作对齐、覆盖引导的半合成决策情境构造”。本实现组合既有配额、排程与覆盖方法；方法贡献应由任务设计、可复核生成合同、实际覆盖及下游实验支撑，不将现有求解器改名当作新算法。
