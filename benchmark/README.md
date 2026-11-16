# 源码入口

[仓库首页](../README.md) · [方法与来源](../docs/METHOD.md) · [复现指南](../docs/REPRODUCE.md)

| 模块 | 职责 |
|---|---|
| [household_stage1](household_stage1/) | 八国调查家庭、角色、参考周、设备和服务需求 |
| [ab_generation](ab_generation/) | 日常A、EB动作候选B、覆盖与题位分配 |
| [idf_reference](idf_reference/) | 当前参考住宅、地区/地点包及EB统一物理适配 |
| [project](project/) | 数据交接、UI91材料与版本绑定 |
| [collector](collector/) | 采集、答卷存储与恢复 |
| [housing_simulation](housing_simulation/) | 独立EnergyPlus24.1公开构造示例，与主25.2路线分开 |
| [family_generation](family_generation/) | 早期合成家庭与可复用组件 |
| [household_archetypes](household_archetypes/) | 六类角色的依据和配额 |

当前批次和可用范围见[数据说明](../docs/DATASET.md)及[状态](../docs/BENCHMARK_STATUS.json)。各模块保留对应源锁、依赖和验证数据。
