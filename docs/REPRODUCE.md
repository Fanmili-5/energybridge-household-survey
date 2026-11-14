# 复现指南

仓库根目录执行。基础检查用Python标准库；家庭与住房连接需Python3.12—3.14及固定依赖。输出目录必须新建，旧产物和失败记录保留。

## 1. 核验公开版本

```bash
python -B benchmark/verify_publication.py
python -B -m benchmark.family_generation.verify_package
python -B benchmark/household_archetypes/verify.py
python -B -m benchmark.ab_generation.verify_package
python -B -m benchmark.housing_simulation.verify_package
python -B -m benchmark.project.verify_package
```

这些命令检查来源、参数、文件身份和接口资料，不运行EnergyPlus、不连接生产数据库、不产生真人标签。

## 2. 完整生成算法

以[算法与统一入口](../benchmark/ab_generation/ALGORITHM.md)为准。主验收环境Python3.14.3，统一安装：

```bash
python -m pip install -r benchmark/ab_generation/generation-requirements-lock.txt
python -B -m benchmark.ab_generation.generation_pipeline \
  --make-example-pool \
  --household-config benchmark/household_stage1/generator/configs/pilot96.json \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/pinned/appliance_sim.py \
  --start-date 2007-07-18 --workers 4 --out /path/to/new-demo96
```

原生文件固定到官方paper-v1-final/c58a2a7a，确切路径和SHA见算法说明。公开演示从320条声明的合成池生成96户×10题，自动补候选、重选并封存。真实源池/原件和冻结家庭的两种入口、扩量步骤、预算及失败含义均在同一说明中。--reference-batch在封存后核对实际A/B哈希，不参与选题。

该入口不运行物理引擎或制造真人答案。单户和逐阶段研究可继续用[分步CLI](../benchmark/ab_generation/README.md#复用)。

## 3. 历史公开家庭与生活A示例

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.family_generation generate --input benchmark/family_generation/examples/batch.json --out /tmp/eb-families-new
python -B -m benchmark.family_generation connect --families /tmp/eb-families-new --out /tmp/eb-life-new
python -B -m benchmark.family_generation verify /tmp/eb-life-new
```

公开池为六个声明的合成情境，用于实现与接口验证。增加复制数量不证明人口多样性。

## 4. 历史物理与UI91入口

| 阶段 | 入口与所需资料 |
|---|---|
| 新版十天计划 | [采集方法第6节](../benchmark/ab_generation/docs/collection/COLLECTION_METHOD.md#6-验证与复现)：固定A、候选、分配及回放；不启动引擎 |
| 既有50户导入 | `benchmark.ab_generation.reference_collection`，需获准的原家庭和A侧输入；不读取旧B后果 |
| 配对物理交接 | `benchmark.project.reference_collection_physics`，绑定同一冻结A/B、需求、住房、天气和初态 |
| 住房物理复现 | [住房指南](../benchmark/housing_simulation/REPRODUCE.md)，需固定依赖、登记资源和EnergyPlus24.1；这是显式运行步骤 |
| UI91封存 | `benchmark.project.reference_physical_release`，将同版可用结果与资料绑定；工程修复见[专项方法](../benchmark/project/PHYSICS_REPAIR_PRODUCTION.md) |

公开六户37案仍按[旧接口示例](../benchmark/project/README.md)独立复现，不能代替新版18:00—19:00的正式500题。受控500题重建需要相应许可输入；公开代码不等于公开提供这些原件。

## 5. 采集协议与正式部署

`python -B benchmark/collector/test_protocol.py`使用隔离虚构数据测试HTTP/SQLite，不产生真人答案；运行环境须允许本地回环监听。多轮身份检查见[采集器](../benchmark/collector/README.md)。

生成和封存命令不自动激活线上服务。正式发布须核对资料、代码、数据库版本和恢复材料，并保留旧记录。文档或CI通过不表示任意新物理批次已经通过验收。本轮1000户已完成计划与原版执行，全量物理验证及正式发放仍待完成。两组新配对物理验收与隔离UI91预览见[本轮报告](research/AB_GENERATION_REPAIR_20261114.md)。
