# EnergyBridge

让模型站在具体家庭的立场，比较日常方案A与VPP调整方案B，判断是否接受、如何评分，以及为什么。

**[正式问卷](https://47.85.194.154/household50-current/) · [项目文档](docs/README.md) · [复现指南](docs/REPRODUCE.md)**

家庭与设备 → 住房和生活安排 → 日常A → 不同取舍的B → 配对仿真后果 → UI91问卷 → 人类评价。

## 三条主线

| 主线 | 内容 | 代码与详细方法 |
|---|---|---|
| 家庭与设备 | 调查约束的家庭、EB角色态度、参考周、4—6类控制与服务合同 | [可复用生成器](benchmark/household_stage1/generator/)；[早期合成画像](benchmark/family_generation/) |
| A/B策略 | 从生活需求生成A，围绕固定VPP生成单设备/联合B，覆盖取舍并保留长尾 | [ab_generation](benchmark/ab_generation/) |
| 住房与仿真 | 匹配参考住房、装配设备、执行同世界A/B并审计后果 | [housing_simulation](benchmark/housing_simulation/) |

完整方法、来源、规则参数与验收结果见[方法说明](docs/METHOD.md)。[project](benchmark/project/)负责资料连接与UI91适配，[collector](benchmark/collector/)负责版本绑定、分户、回答与恢复。

## 当前版本

正式资料为原50户×10天的新A/B与对应参考物理后果；VPP固定18:00—19:00，沿用UI91。新八国1000户的家庭生成第一步已完成，当前每户均配备并控制空调；其IDF、A/B和真人问卷仍待后续阶段验收。版本及完成范围见[数据与验收](docs/DATASET.md)。

公开仓库包含代码、合成示例、方法和聚合证据；受控原件与真人答卷按许可管理。详见[来源与许可](THIRD_PARTY.md)。

## 八国家庭生成第一步（V9）

[可复用生成算法与规则](benchmark/household_stage1/generator/README.md) · [数据来源与实际方法](benchmark/household_stage1/README.md) · [冻结批次摘要](benchmark/household_stage1/CURRENT.json) · [验收证据](benchmark/household_stage1/VALIDATION.json)

中国、美国、英国、西班牙、印度、墨西哥、澳大利亚、德国各125户。家庭背景由真实调查提供，角色态度沿用EB定义，六类配额按EB人类角色扮演调查样本比例分配；结合活动与服务规则生成生活安排，以整数规划分配电器组合。**空调每户必备且必控**，每户共4—6类。生成代码、逐步依据、规则参数、验收证据及扩量入口均已打包，家庭生成第一步通过，可用于后续benchmark构造。正式V9与既有50户线上资料分别管理。

## 当前生成方法 v2.11（研究版本）

[统一方法与来源](benchmark/research_delivery/METHOD.md) · [分开动作幅度与事件阶段](benchmark/research_delivery/ACTION_CHANGE_METHOD.md) · [复现入口](benchmark/research_delivery/REPRODUCE.md) · [v2.11的500日期影子验收](benchmark/research_delivery/release_v2_11/shadow50/README.md)

CLI默认配置为`benchmark/ab_generation/unified/CURRENT_CONFIG.json`。v2.11分开机器移时、装取变化和控制幅度，小时级变化显示绝对分钟；VPP前准备与事件内调节按固定18:00边界分开。已在原18,977候选中完成50户500原日期影子重选：各户已有联合规模及1,264项声明目标缺额0；额外机器×装取细分仍缺全局5种、家庭条件下130项组合，不宣称全面覆盖。冲突、名义无帮助和未知保留，不改A/B、不重抽，原v2.10结果继续封存。公开代码与无身份汇总，个体明细保存在本地；不替换线上正式题集、不跑物理仿真、不启动1000户A/B及物理批次；家庭输入V9另行验收。
