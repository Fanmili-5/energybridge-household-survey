# 源码入口

项目概览见[仓库首页](../README.md)，使用说明见[项目文档](../docs/README.md)。

| 模块 | 职责 |
|---|---|
| [family_generation](family_generation/) | 生成家庭、设备和权限，并连接住房与生活A |
| [household_archetypes](household_archetypes/) | 六类实验角色的来源、证据与拟议配额 |
| [ab_generation](ab_generation/) | 生活A、设备机会、B候选、联合调整与十天选题 |
| [housing_simulation](housing_simulation/) | 住房构造、设备执行、配对仿真与审计 |
| [project](project/) | 三条线的数据交接、UI91资料封存和显示验证 |
| [collector](collector/) | 正式问卷、版本绑定、采集与恢复协议 |

[releases](releases/)保存各版本公开清单，[generation](generation/)保存历史生成源码目录。当前范围见[数据与验收](../docs/DATASET.md)。

当前A/B研究入口：[v2.11统一生成方法](research_delivery/METHOD.md)、[配置及复现](research_delivery/REPRODUCE.md)、[动作幅度与事件阶段](research_delivery/ACTION_CHANGE_METHOD.md)。原精确联合任务数规则继续保留；当前研究修订与线上题集版本分开，未计算后果保持未知。
