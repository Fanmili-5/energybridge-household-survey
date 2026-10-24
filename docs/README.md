# 项目文档

按以下顺序阅读即可了解和使用项目。

| 文档 | 回答的问题 |
|---|---|
| [方法说明](METHOD.md) | 三条主线怎样连接，每一步依据、规则和人工设定是什么？ |
| [数据与验收](DATASET.md) | 当前50户是什么版本，哪些完成、哪些仍待验证？ |
| [复现指南](REPRODUCE.md) | 公开环境可以运行什么，受控输入需要什么？ |
| [采集与质控](COLLECTION.md) | UI91如何分户、作答、恢复，以及标签怎样管理？ |
| [评测协议](EVALUATION.md) | 模型输入输出、数据分组和正式指标怎样确定？ |

源码入口见[benchmark](../benchmark/README.md)，当前机器可读版本见[CURRENT_QUESTIONNAIRE50.json](household1000/CURRENT_QUESTIONNAIRE50.json)。

## 历史与证据

- [早期问卷和工程记录](history/legacy-202609/)、[旧项目说明](history/project-20261020)、[项目复核记录](history/reviews/)。
- [研究源码与逐版材料](research/)、[家庭批次与机器清单](household1000/)。历史说明只适用于其登记版本。
- 各模块的原始依据、参数和验证文件由对应README引导，不作为并列的项目入口。

当前生成方法研究版本：[统一算法](../benchmark/research_delivery/METHOD.md) · [v2.10联合任务数及配置修订](../benchmark/research_delivery/JOINT_ORDER_SELECTION_METHOD.md) · [复现与范围](../benchmark/research_delivery/REPRODUCE.md)。本次GitHub代码更新不改变线上正式采集。
