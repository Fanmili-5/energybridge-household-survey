# EnergyBridge

让模型站在具体家庭的立场，比较日常方案A与VPP调整方案B，判断是否接受、如何评分，以及为什么。

**[正式问卷](https://47.85.194.154/household50-current/) · [项目文档](docs/README.md) · [复现指南](docs/REPRODUCE.md)**

家庭与设备 → 住房和生活安排 → 日常A → 不同取舍的B → 配对仿真后果 → UI91问卷 → 人类评价。

## 三条主线

| 主线 | 内容 | 代码与详细方法 |
|---|---|---|
| 家庭与设备 | 成员、关系、实验角色、设备与权限形成一致的家庭情境 | [family_generation](benchmark/family_generation/) |
| A/B策略 | 从生活需求生成A，围绕固定VPP生成单设备/联合B，覆盖取舍并保留长尾 | [ab_generation](benchmark/ab_generation/) |
| 住房与仿真 | 匹配参考住房、装配设备、执行同世界A/B并审计后果 | [housing_simulation](benchmark/housing_simulation/) |

完整方法、来源、人工设定与验证边界见[方法说明](docs/METHOD.md)。[project](benchmark/project/)负责资料连接与UI91适配，[collector](benchmark/collector/)负责版本绑定、分户、回答与恢复。

## 当前版本

正式资料为原50户×10天的新A/B与对应参考物理后果；VPP固定18:00—19:00，沿用UI91。1000户扩展继续暂缓。版本及完成范围见[数据与验收](docs/DATASET.md)。

公开仓库包含代码、合成示例、方法和聚合证据；受控原件与真人答卷按许可管理。详见[来源与许可](THIRD_PARTY.md)。
