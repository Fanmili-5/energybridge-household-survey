# 家庭与A/B的复现流程

代码、数据版本与选择记录分别冻结。以下命令只生成/核对参考家庭和原生计划，不启动EnergyPlus、模型服务或线上问卷。

## 1. 复现用途与证据

| 用途 | 输入与命令 | 已有证据及边界 |
|---|---|---|
| 公开合成演示 | 声明的合成源池、pilot96与统一generation_pipeline | 可检查接口和新批流程；合成示例不是调查样本，也不替代1000户实证来源 |
| 冻结池重新分配 | 受控候选包；cohort_recipe solve + rebuild | 已物化10000题；939根格，918格至少两国；715个B与封存版不同，未替换正式数据 |
| 封存版精确重建 | 受控候选包及明示历史候选ID锁；cohort_recipe reproduce | 搬迁目录与原电器源码路径后10000题任务/事件/A/B/场景/完整输入一致 |
| 原调查到全部历史搜索 | 需原件、源适配、家庭选择、候选发现及历次分配 | 上述重建不证明独立重跑全部历史搜索；新批允许不同可行选择，应按预声明不变量验收 |

精确重建不把最终B文件作为输入复制；根据归档候选补丁重新物化并执行原电器检查，参考批次仅在最后比较。历史选择是算法选择，不是真人标签。FEASIBLE、UNKNOWN和INFEASIBLE按各自含义报告，不把多可行解差异写成错误。

## 2. 环境与上游输入

正式构造和既有原生回放验收使用Python3.14.3；依赖由以下文件固定：

~~~bash
python -m pip install -r benchmark/ab_generation/generation-requirements-lock.txt
~~~

原EB锁定提交为c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0；需要从[上游仓库](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/tree/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0)按其使用条款取得电器源码。传给命令的appliance_sim.py SHA256应为：

~~~text
be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9
~~~

原始调查的准确文件名、版本、SHA、来源网址与字段范围见[来源目录](../benchmark/household_stage1/SOURCES.json)；路径配置见[数据合同](../benchmark/household_stage1/generator/DATA_CONTRACT.md)。prepare-sources的完整原件审计当前要求八份固定输入，即使只选部分国家。不能仅改预期SHA来宣称同名新文件已兼容。


### 种子与预算

| 阶段 | 新批默认或已验证命令 | 解释 |
|---|---|---|
| 家庭选择 | production1000的seed为source-supported-household-generator-v1，最多4个补全、MILP55秒 | pilot96使用独立的public-reuse-pilot-v1；归档源户选择按原清单重建 |
| 日期任务 | task_context.SEED=20261116 | 批次与餐次在A/B前固定；不利用答案 |
| 基础候选 | GENERATION_REPAIR_CONFIG：seed20261022、rows_per_unit8、queries_per_row2、oracle确定性0.05 | 10分钟网格；配置和实际状态进入PRE_RUN/输出 |
| 补充候选 | COMPLETION_CONFIG：rows128、queries64、oracle确定性0.5、每格最多8次尝试、每国最多3次 | 未获见证不能自动标成不可行 |
| 新批队列选择 | generation_pipeline默认确定性预算2；cohort_recipe示例每角色60，seed20261116 | 是不同入口；均报告状态/目标/界，不把预算内可行解称全局最优 |

这些是所链接代码的缺省和示例配置；不反向替代受控正式批次的历史运行清单。

## 3. 公开合成源池到新批次

仓库根目录执行，所有输出目录必须不存在：

~~~bash
python -B -m benchmark.ab_generation.generation_pipeline \
  --make-example-pool \
  --household-config benchmark/household_stage1/generator/configs/pilot96.json \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/pinned/appliance_sim.py \
  --start-date 2007-07-18 --workers 2 \
  --out /new/synthetic96
~~~

该路径从320条明确声明的合成源记录选96户，每户10题。依次生成家庭、预提交任务、构造A、发现并补充B候选、分配与封存、编译同题输入。pilot96已显式降低组合覆盖要求，不能把它的合成池或覆盖阈值写成正式1000户来源。

真实源数据的新批次使用同一入口的--pool/--data-config及家庭配置；已冻结家庭则用--households和--expected-household-sha256。参数与相互排斥条件见[统一入口](../benchmark/ab_generation/ALGORITHM.md)。修改种子、配额或规则产生新版本；仅满足不变量不保证选中同一户或同一B。家庭MILP、候选搜索与队列选择的种子/预算/状态分别记录在输出清单，不存在一个种子保证跨求解器版本唯一解。

## 4. 从受控候选包精确重建或重新分配

准备包的freeze命令、必需文件和完整流程见[cohort_recipe](../benchmark/ab_generation/COHORT_RECIPE.md)。对已取得并核验的包，重建命令为：

~~~bash
python -B -m benchmark.ab_generation.cohort_recipe reproduce \
  --bundle /authorised/cohort-recipe \
  --native-source /authorised/pinned/appliance_sim.py \
  --reference-batch /authorised/current-native \
  --reference-questions /authorised/current-question-inputs \
  --out /new/exact-reconstruction --workers 2
~~~

它逐题比较A/B内容、任务SHA、事件、场景、上下文、pair_id和完整输入；缺题、重复或身份不一致失败。压缩时间和运行日志不属于科学内容一致条件。

生成另一组合格B：

~~~bash
python -B -m benchmark.ab_generation.cohort_recipe solve \
  --bundle /authorised/cohort-recipe \
  --out /new/allocation --workers 2 \
  --deterministic-time 60 --seed 20261116

python -B -m benchmark.ab_generation.cohort_recipe rebuild \
  --bundle /authorised/cohort-recipe \
  --selection /new/allocation/CHOICES.json \
  --native-source /authorised/pinned/appliance_sim.py \
  --out /new/materials --workers 2
~~~

solve不读取历史选择文件，按角色单线程、固定顺序和预算求解。新批应满足每户十个日期、同题任务一致、原动作/完整程序、有机会功能及声明覆盖等约束；报告跨国重复、频数和求解界，不预设一定达到封存版924格两国重复。

## 5. 重新计算统计与分组

以下命令只使用Python标准库及本地纯数据辅助函数，逐题读取封存文件，核验家庭身份、计划哈希、事件、任务身份与覆盖台账的一致性：

~~~bash
python -B -m benchmark.ab_generation.method_statistics \
  --households /authorised/household_cases.jsonl \
  --batch /authorised/current-native \
  --out /new/static-statistics
~~~

| 输出 | 用途 |
|---|---|
| GENERATION_STATISTICS.json / GENERATION_STATISTICS.md | 无逐户ID的来源、国家/角色、覆盖、事件、变动与分组聚合统计，可按许可发布 |
| GROUPS.jsonl | 逐户source_group/construction_group；私有，不能复制到公开仓库 |

公开聚合件对应[当前统计](GENERATION_STATISTICS.md)与[JSON](GENERATION_STATISTICS.json)。输入指纹和统计实现SHA均包含在JSON中。命令输出页名与公开页名一致；只有聚合JSON和Markdown进入公开发布。

已有私有case_id→split的JSON映射时，可追加--split-assignment /private/splits.json核验关联组不跨分区；命令不会自行分配训练集。重复参与者需在获得答卷后与构造组连接合并。当前尚无答卷或正式分区。


### 不跳过原EB源码检查的回归命令

仅安装求解器依赖不足以导入家庭调查适配器；须安装上述完整锁中的pyreadstat/narwhals。原生回归还需显式指定原电器源码，否则有关测试会标为skipped，不能把跳过计成通过：

~~~bash
EB_NATIVE_SOURCE=/path/to/pinned/appliance_sim.py python -B -m unittest \
  benchmark.household_stage1.generator.test_generator \
  benchmark.ab_generation.test_daily_problem \
  benchmark.ab_generation.test_generation_recipe \
  benchmark.ab_generation.test_task_commitment \
  benchmark.ab_generation.test_cohort_recipe \
  benchmark.ab_generation.test_method_statistics -v
~~~

这些检查使用合成反例和锁定原生电器逻辑，不调用EnergyPlus；它们与正式批次物理验证分开。

## 6. 输入获取与发布范围

代码、规则表、依赖、原件指纹和聚合统计公开。源调查需按原网址申请/下载并遵守原条款；CRECS当前使用项目持有原件，官网不保证提供同一文件。调查原件、逐户卡、候选包、历史选择锁和答卷不在GitHub再分发。

研究者可向项目维护者申请受控复现材料；能否提供取决于来源条款和授权，不承诺所有源数据可公开下载。受控材料须带文件清单与内容指纹，按相应命令验证；没有授权原件/候选包时，公开合成演示仍可检查算法接口，但不能宣称独立复现了调查锚定的正式批次。当前没有自动公开下载受控包的服务。

| 当前冻结输入 | SHA256 |
|---|---|
| 1000户家庭JSONL | 81fe13c3bb37cfe961418333690a5008e68b09e834f73241437a42fba5b82a11 |
| 已审A索引 | 90fc4a1bbadf1258f93c19e806d4a3beb5a0fa274e05125d7395f675cce2b9b0 |
| 10000题配对索引 | 66a95e74cc83611f9235830d6d887d8e1ce55a028f7fc4d6a07d90574a8f9cb1 |
| 同题问卷输入索引 | d3e98203dea35988b7840250388da649f8b4fc29fff67a83e3e324e3c3a1c20c |

本节的复现证据限定于参考家庭、任务及原生计划输入；不继承旧物理结果，不产生真人标签。第三方条款见[来源与许可](../THIRD_PARTY.md)。
