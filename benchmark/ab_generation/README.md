# 家庭与A/B完整生成算法

完整公共入口是 [generation_pipeline.py](generation_pipeline.py)，见[算法1、目标与复现命令](ALGORITHM.md)。单户入口保留[generate_native.py](generate_native.py)。冻结家庭输入后，每户生成十个不同日期的日常A，再从原EB六类动作中生成候选，最后每天只选一个B。完整来源和结果见[本轮记录](../../docs/research/AB_GENERATION_REPAIR_20261114.md)。

## 算法

1. **生成A：OR-Tools CP-SAT。** 根据家庭参考周、吃饭/家务/洗浴时间联合安排完整程序；同批衣物先洗后烘，洗碗对应已经完成的一餐，热水器窗口围绕洗浴，EV在给定停车连接内连续充电。保留原程序资源、时长和硬件；不读取VPP收益、B后果或真人答案。A是有家庭依据的实验参考日程，不冒称实测生活日记。
2. **构造B：有限动作枚举＋IPOG-C覆盖设计＋CP-SAT约束求解。** 洗衣、烘干、洗碗只移动完整程序；空调只改变原版制冷设定值；热水器改变原有窗口/目标；EV保持一段连续充电。原版来源固定到官方paper-v1-final的c58a2a7a；实际检查时钟由冻结原文件的相关AST执行，不用后来V2/V3限制回判旧题。
3. **选一个B：SciPy/HiGHS整数规划。** 每日期一题；优先覆盖已有完整见证的联合任务数，再优化电器/取舍覆盖和重复，用固定种子破同分。同类家庭可共同补齐细分组合；[cohort_coverage.py](cohort_coverage.py)只做保持原有基础覆盖的重选，并重新执行改动后的B。它不保证全局最优，未覆盖单元照实登记。

家庭温度偏好是软属性；偏好冲突、预计收益差和居民可能拒绝都可保留。未知热效应不能算成“零影响”。执行接口错误、擅改硬件或破坏同批洗烘先后关系单独报错。

连续EV、每日完整服务和非EV不跨夜是本批明确采用的实验约束。十分钟记录网格不表示十分钟开关一次。原EB资源窗口也不冒称实测电机连续工作的时长。

## 复用

完整链从[统一配方](ALGORITHM.md#统一入口)运行，安装[generation-requirements-lock.txt](generation-requirements-lock.txt)。以下分步入口保留用于调试与单户研究，整批完整验收应使用generation_pipeline。

```bash
python -B -m benchmark.ab_generation.generate_native \
  --households /path/to/household_cases.jsonl \
  --case-id YOUR_CASE_ID \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --start-date 2007-07-18 --days 10 \
  --native-source /path/to/pinned/appliance_sim.py \
  --out /path/to/new-output-directory
```

输出包括冻结输入/代码指纹、每日A、完整已生成候选、选择凭据和逐日A/B及原版执行回放。物理后果和真人答案保持null。公开参考参数是本轮来源原型的资源窗口，不适用于任意硬件或国家；新硬件须重新核对来源和能力。

整批生成复用同一算法，无服务器路径写死：

```bash
python -B -m benchmark.ab_generation.generate_cohort \
  --households /path/to/household_cases.jsonl \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --start-date 2007-07-18 --days 10 --workers 4 \
  --native-source /path/to/pinned/appliance_sim.py --out /path/to/new-batch
```

批次覆盖检查：

```bash
python -B -m benchmark.ab_generation.cohort_coverage --batch /path/to/native-batch
# --apply --native-source ... 才会重选；保存原PAIR并回放新B。
# 剩余目标可用 cohort_optimize --batch ... --native-source ... 做有预算的联合补选。
python -B -m benchmark.ab_generation.seal_native_cohort \
  --batch /path/to/native-batch --households /path/to/household_cases.jsonl
python -B -m benchmark.ab_generation.verify_package
```

批次检查读取同版生成批次的STATUS、PRE_RUN及分户CATALOGUES/PAIR。重选后须重新封存，更新全局索引和SELECTION_CURRENT；原索引和初选凭据保留。若使用原生成器的独立快照，可给封存命令传--generator-code。逐户/整批CLI不自动创造人口源池或调用EnergyPlus。

完整配方本次已在新目录生成1000户×10题，并通过两份96户公开示例的逐题A/B哈希复现。修复和范围见[算法验收自查](../../docs/research/GENERATION_ALGORITHM_REVIEW_20261114.md)。

## 当前验收与历史

新1000户×10题已完成计划生成和20000次原版A/B执行回放。细分覆盖、两组新配对物理验证及一个UI91隔离预览分别登记；全量物理验收和正式发放仍未完成，见[状态](../../docs/BENCHMARK_STATUS.json)。

旧10000题全部保留。原“4335个B一概不合格”已撤回，见[论文版重审](../../docs/research/original_eb_reaudit_20261113/REPORT.md)。旧[490题V3试跑](validation/eb_native_v3/README.md)、[十天采集方法](docs/collection/COLLECTION_METHOD.md)、[v2.10/v2.11研究方法](../research_delivery/METHOD.md)按原版本留档，不能继承其后果或答案到本轮新方案。
