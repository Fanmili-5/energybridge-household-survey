# 项目文档

按以下顺序阅读即可了解和使用项目。

| 文档 | 回答的问题 |
|---|---|
| [八国家庭生成第一步](../benchmark/household_stage1/README.md) | 实际调查来源、1000户构造方法、每户空调必备且必控和验收范围 |
| [最新完整方法](METHOD.md) | 八国调查→家庭→原生A/B→参考IDF→问卷，算法、来源及版本交接 |
| [本轮A/B生成与实际验收](research/AB_GENERATION_REPAIR_20261114.md) | 新10000题、949/969细分覆盖、两组物理试例及仍未完成项 |
| [原EB论文版重审](research/original_eb_reaudit_20261113/REPORT.md) | 后加校验的来源，4335误报与执行映射逐条核对，居民负面候选保留 |
| [当前状态](BENCHMARK_STATUS.json) / [ACL视角复核](ACL_BENCHMARK_REVIEW_20261112.md) | 哪些已经验收，哪些还不足以支持论文结论？ |
| [数据与验收](DATASET.md) | 当前50户是什么版本，哪些完成、哪些仍待验证？ |
| [复现指南](REPRODUCE.md) | 公开环境可以运行什么，受控输入需要什么？ |
| [采集与质控](COLLECTION.md) | UI91如何分户、作答、恢复，以及标签怎样管理？ |
| [评测协议](EVALUATION.md) | 模型输入输出、数据分组和正式指标怎样确定？ |

源码入口见[benchmark](../benchmark/README.md)，当前机器可读版本见[CURRENT_QUESTIONNAIRE50.json](household1000/CURRENT_QUESTIONNAIRE50.json)。

## 历史与证据

- [早期问卷和工程记录](history/legacy-202609/)、[旧项目说明](history/project-20261020)、[项目复核记录](history/reviews/)。
- [研究源码与逐版材料](research/)、[家庭批次与机器清单](household1000/)。历史说明只适用于其登记版本。
- 各模块的原始依据、参数和验证文件由对应README引导，不作为并列的项目入口。

历史生成方法研究版本：[统一算法](../benchmark/research_delivery/METHOD.md) · [v2.10联合任务数及配置修订](../benchmark/research_delivery/JOINT_ORDER_SELECTION_METHOD.md) · [复现与范围](../benchmark/research_delivery/REPRODUCE.md)。本次GitHub代码更新不改变线上正式采集。

家庭第一步的可复用实现：[调查约束的家庭生成算法](../benchmark/household_stage1/generator/README.md)，含角色/生活规则、证据表、规模配置、原件适配与独立重放。
