# EnergyBridge

给定家庭背景、日常用电计划A、调整方案B及其仿真后果，收集人对整份计划的接受判断、评分和原因。

[方法与来源](docs/METHOD.md) · [数据与当前范围](docs/DATASET.md) · [复现指南](docs/REPRODUCE.md) · [输入输出规范](docs/PIPELINE_CONTRACTS.md)

## 当前数据

八国各125户，共1000户，每户10个日期、每天一个A/B问题。家庭来自冻结调查资料，角色沿用EB设计，生活安排采用有来源记录的参考规则。每户包含4—6类可控电器，空调必备且必控。

| 环节 | 已完成范围 |
|---|---|
| 家庭 | 1000个不同源家庭，来源、日程与服务一致性检查通过 |
| A/B | 10000对完整计划，20000次原版动作执行通过，预定义细分969/969覆盖 |
| 物理后果 | 两组与当前计划身份一致的配对试例通过；新版场景批量适配与全量物理结果尚未完成 |
| 真人问卷 | 当前10000题尚未正式发放；UI91采用实际仿真后果展示路线 |

数量和版本见[当前状态](docs/BENCHMARK_STATUS.json)。现有[50户界面试用](https://47.85.194.154/household50-current/)含合成展示值，与上述新题集分别管理。

## 从家庭到问卷

调查家庭与角色 → 参考生活与日常A → EB动作域内的B候选 → 每户十题的覆盖选取 → 同场景配对仿真 → UI91与人类评价。

IDF由公开住宅构造算法、地区材料和天气包、EB设备及家庭需求共同编译成参考物理环境。A/B共享住房、天气、硬件和外部需求，按各自实际指令运行。当前新事件时段仍需完成逐题上下文到物理结果的批量连接。

| 模块 | 入口 |
|---|---|
| 调查家庭与参考生活 | [household_stage1](benchmark/household_stage1/) |
| 日常A、B候选和题位分配 | [完整算法](benchmark/ab_generation/ALGORITHM.md)、[场景分配](benchmark/ab_generation/SCENE_ALGORITHM.md) |
| 当前参考住宅与EB物理适配 | [idf_reference](benchmark/idf_reference/) |
| 问卷材料与版本绑定 | [project](benchmark/project/)、[collector](benchmark/collector/) |

运行环境、第三方资源准备和支持范围由各模块说明；代码检查不替代新请求的物理验收。源码、合成示例和聚合数据公开；受控调查原件、家庭日程及真人答卷按各自许可管理。见[来源与许可](THIRD_PARTY.md)及[项目文档](docs/README.md)。
