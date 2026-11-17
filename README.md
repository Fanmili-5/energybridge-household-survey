# EnergyBridge

给定家庭背景、当天任务、完整用电计划A、调整方案B及同版本仿真后果，收集真人对整份计划的接受判断、评分和原因。

[生成总览](docs/GENERATION.md) · [规则依据](docs/GENERATION_RULES.md) · [覆盖与分组](docs/GENERATION_STATISTICS.md) · [完整方法](docs/METHOD.md) · [可复用算法](benchmark/ab_generation/ALGORITHM.md) · [复现](docs/REPRODUCE.md) · [交接规范](docs/PIPELINE_CONTRACTS.md)

## 当前生成版本

八国各125户，共1000户，每户10个独立日期情境，每题一对完整A/B。六角色配额166/198/125/151/156/204沿用EB角色扮演调查构成。每户控制4—6类功能，空调必备且必控。

| 环节 | 当前范围 |
|---|---|
| 家庭 | 1000个不同主源家庭；调查、匹配和实验设定逐字段分开 |
| 任务与A/B | 先确定负载来源/准备时刻，再生成A和B；10000对计划，20000次原版执行检查 |
| 覆盖 | 当前有限动作域939格全部出现；924格至少两国，15格一国；旧969/969不再作为本版成绩 |
| 物理后果 | 本版尚未计算；旧试例不继承为本版通过 |
| 真人问卷 | 本版尚未正式发放、没有真人标签；后续沿用UI91展示同版仿真后果 |

版本和哈希见[当前状态](docs/BENCHMARK_STATUS.json)。既有[50户界面试用](https://47.85.194.154/household50-current/)属于含合成展示值的历史界面资料，与本版分开。

## 生成逻辑

调查家庭与配额 → 角色和参考生活 → 固定当天任务 → 日常A → 原EB动作域内B候选 → 每日期一个B及队列覆盖分配 → 同场景配对物理验证 → UI91与真人评价。

A用CP-SAT安排完整程序，B用受约束组合搜索和整数规划选取。程序不切碎，洗烘处理同批衣物，EV连续补能；居民不喜欢或没有正向名义减电的合法B保留。八国均衡是benchmark设计，不代表全球人口分布。

| 模块 | 入口 |
|---|---|
| 来源、角色、参考生活与控制组合 | [家庭生成器](benchmark/household_stage1/generator/) |
| 任务、完整A/B、候选与选择 | [算法](benchmark/ab_generation/ALGORITHM.md) |
| 同题问卷输入与身份核对 | [输入合同](benchmark/ab_generation/QUESTION_INPUTS.md) |
| 参考住宅、天气与设备物理适配 | [IDF模块](benchmark/idf_reference/) |

公开内容为代码、方法、合成示例、聚合范围和指纹；调查原件、逐户真实卡及答卷按许可管理。[全队列分配与封存版重建](benchmark/ab_generation/COHORT_RECIPE.md)均有可复用命令；历史选择重建与新求解分别报告。内部审查报告与工程日志不放入本仓库。见[来源与许可](THIRD_PARTY.md)。
