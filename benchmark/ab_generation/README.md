# A/B策略生成

从给定家庭的生活需求生成日常A；冻结A后，围绕18:00—19:00的VPP构造有不同取舍的B，再分配每户十题。生活安排、设备和授权不为凑覆盖而改写，没帮助、生活冲突及可计算失败保留；工程逻辑错误隔离诊断。

## 当前方法

| 内容 | 阅读入口 |
|---|---|
| 新版机会识别、逐设备变化、事件关联、联合与去重 | [十天采集方法](docs/collection/COLLECTION_METHOD.md) |
| 计划、覆盖、缺额和实际验证范围 | [采集验证](docs/collection/COLLECTION_VALIDATION.md) |
| 生活需求如何形成A | [生活到A](docs/life/LIFE_METHOD.md)、[生活输入](docs/life/LIFE_INPUTS.md) |
| 原EB对应、完整未来A的离线条件、论文与参数 | [设计](docs/core/DESIGN.md)、[离线实验](docs/core/OFFLINE_EXPERIMENT.md)、[证据](docs/core/EVIDENCE.md)、[参数](docs/core/PARAMETERS.md) |
| 基础接口及独立实验复现 | [接口](docs/core/INPUTS.md)、[复现](docs/core/REPRODUCE.md) |

现有50户从冻结A侧导入，新B独立生成；正式物理结果和UI91接入由[project](../project/)完成。当前数据范围见[数据与验收](../../docs/DATASET.md)。基础三策略实验、旧分层和新版正式十天选题分别管理。

## 入口与核验

- `benchmark.ab_generation build-life`：生活条件→服务需求与A。
- `benchmark.ab_generation.collection`：固定A→新版候选、准入、十天分配与回放。
- `benchmark.ab_generation.reference_collection`：既有50户A侧导入。

```bash
python -B -m benchmark.ab_generation.audit_design
python -B -m benchmark.ab_generation.verify_package
```

来源、数值和授权登记为`SOURCES.json`、`PARAMETERS.json`、`COLLECTION_PARAMETERS.json`、`AUTHORIZATION.json`。精确数值和搜索权重是明示实验设定，论文不自动证明本批数据的代表性或真人效度。

旧联合上限、敏感性、长尾分层、缺额修订与自查均收在[历史方法与记录](docs/history/)，原版本结果保留。完整实验在研究计算环境显式运行，GitHub只做有界检查。

> 当前研究入口：[unified v2.10](unified/README.md)。其CLI默认读取CURRENT_CONFIG.json；下列旧模块及已封存结果保留重放，新规则不回写原A/B或仿真。
