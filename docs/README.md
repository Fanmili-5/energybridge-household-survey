# 项目文档

| 文档 | 内容 |
|---|---|
| [方法与来源](METHOD.md) | 调查家庭、角色、A/B、参考IDF和问卷的完整流程 |
| [家庭生成](../benchmark/household_stage1/generator/README.md) | 国家数据源、规则参数、相容性选取与扩量入口 |
| [A/B生成算法](../benchmark/ab_generation/ALGORITHM.md) | 日常A、EB动作候选、选题目标和复用命令 |
| [场景与题位分配](../benchmark/ab_generation/SCENE_ALGORITHM.md) | 每户十题、细分覆盖及匹配场景 |
| [参考住宅与物理环境](../benchmark/idf_reference/README.md) | 构造算法、地区包、共享资源和支持范围 |
| [输入输出规范](PIPELINE_CONTRACTS.md) | 家庭、计划、物理结果和答卷的身份连接 |
| [当前状态](BENCHMARK_STATUS.json) | 当前批次、实际通过范围和尚未完成部分 |
| [数据说明](DATASET.md) | 新1000户与既有界面试用版本的区别 |
| [复现指南](REPRODUCE.md) | 依赖、公开示例及受控输入准备 |
| [采集与质控](COLLECTION.md) | UI91、版本绑定、回答和恢复 |
| [评测协议](EVALUATION.md) | 评测目标、分组和指标 |

[源码入口](../benchmark/README.md)列出模块职责。必要的来源、参数、测试与验证数据随代码保留。
