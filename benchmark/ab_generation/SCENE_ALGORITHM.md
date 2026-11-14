# 保持家庭不变的场景覆盖生成算法

这一步解决的是：合法候选已经存在，但稀有修改集中在少数家庭日期，无法同时放进每户十题。算法先检查题位容量，再调整外部事件场景和选题。家庭、日常A和原EB电器动作不变。

## 输入与输出

输入为已冻结的家庭、十个既有日期、已通过原生执行的父批次、选题前建立的细分目标和固定版本的EB电器代码。输出仍为每户十题，每题一个完整A和一个B；此外记录实际事件时段、场景身份、完整执行凭据和未达成的跨国目标。

当前八国1000户的969项，是原18:00—19:00参考场景在选题前登记的“角色×电器×根动作细分”目标。969不是全部联合电器空间，也不是新增时段下所有可能行为的总数。扩展场景中实际选入的细分仍来自这套目标；探索到的其他原始类别单独登记。

## 具体算法

1. **冻结家庭与A。** 沿用调查来源、成员、参考周、设备、服务需求及原日期。禁止为覆盖改洗浴、吃饭、出行或家务钟点；B的收益和居民答案不进入A生成。
2. **寻找更多合法场景。** 只改变外部响应事件的时段。原EB论文代码从事件的trigger_h/end_h读取起止时刻，18/19是默认值。本扩展声明一个16:00—20:00开始、持续一小时、十分钟网格的实验场景域。它是可复核的实验设置，不是各国电网事件的经验分布。
3. **补完整候选。** 仍调用原有限动作枚举。热水器直接在原窗口/设定值动作中找见证；烘干需要洗衣配合时，只搜索既有同批洗衣动作。先试单根动作，再补必要依赖。缺少见证记为搜索未解决，不判成居民拒绝或物理不可能。
4. **联合分配题位。** CP-SAT同时约束每户十个原日期、每天一个B、全部原目标至少出现一次、每户已有基础题型和已达成的跨国覆盖。每户最多改四题。在这些约束下尽量少改题；求解预算内的可行解与已证最优分开报告。
5. **加入匹配对照。** 新时段不能只出现在补缺的E/F类中。按补缺方案使用的时段，为每个国家×角色组合配置相同题数。对照从原空调题位构造，保持原基础特征；另一个CP模型联合安排时段和题位，并保护已达成的原细分跨国覆盖。
6. **独立验收。** 比较全部家庭与A的身份，重新执行所有A/B；检查题量、日期、基础题型、原969项覆盖和匹配时段配额。独立复算工具从实际动作重新构造改动题目的细分标签，不能只读取生成器自报统计。

空调仍为连续温控设定；洗衣/烘干/洗碗保持完整程序；EV保留连续充电与原补能需求。新增事件时段没有增加停冷、硬件调整、程序缩短、人工装取等动作。

## 优化问题如何写入论文

令候选c对应家庭h、日期d和事件时段t，二元变量x_c表示是否选入。

- 每个(h,d)选择一个候选，且保留原十个日期。
- 每个冻结目标格至少被一个选中候选覆盖。
- 每户原有基础特征都保留，包括可用的电器修改类别、联合任务数和取舍类别。
- 已达成的细分跨国覆盖数不降低；未达成的双国目标继续列出。
- 每户与父批次不同的题不超过四道。

主目标是在上述约束下减少改题数。之后按时段t计算补充面板配额q_t，并使每个国家×角色组合在该时段都有q_t道题。对照求解优先保持原细分分配，再以固定种子破同分。

这是分阶段约束求解。不能称为所有家庭、场景和动作的全局最优算法，也不能将已有CP-SAT或IPOG-C重新命名为理论创新。适合的论文表述是：**调查约束、原生动作对齐、容量感知且有匹配对照的半合成决策情境构造算法。**

## 复用

完整家庭到计划入口增加场景补齐：

```bash
python -B -m benchmark.ab_generation.generation_pipeline \
  --households /secure/household_cases.jsonl \
  --expected-household-sha256 YOUR_FROZEN_SHA256 \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/appliance_sim.py \
  --start-date 2007-07-18 --workers 8 \
  --complete-scene-coverage --out /path/to/new-complete-batch
```

已有冻结原生父批次时，直接复用：

```bash
python -B -m benchmark.ab_generation.scene_pipeline \
  --batch /path/to/frozen-native-parent \
  --households /secure/household_cases.jsonl \
  --native-source /path/to/appliance_sim.py \
  --workers 8 --out /path/to/new-scene-batch
```

独立覆盖复算：

```bash
python -B -m benchmark.project.scene_coverage_audit \
  --parent /path/to/frozen-native-parent \
  --batch /path/to/new-scene-batch/native \
  --households /secure/household_cases.jsonl \
  --native-source /path/to/appliance_sim.py \
  --workers 8 --out /path/to/coverage-recomputation.json
```

依赖沿用[generation-requirements-lock.txt](generation-requirements-lock.txt)。输出目录必须新建；参数、代码、来源和各阶段退出码写入收据。换输入或扩大规模不能预先保证覆盖可行；求解失败的批次不能封存为通过版本。

## 后续IDF和问卷如何接

每道题除了A/B哈希，还包含event、context_sha256、scenario_sha256和pair_id。物理任务必须读取PAIR_INDEX里的context_relative_path；有扩展场景时不能仍用原18:00—19:00上下文。

结果关联必须同时核对场景和A/B身份。PHYSICS_HANDOFF采用v2，尚未生成的物理后果和真人答案保持null。UI91正式版仍应展示经同场景仿真得到的后果；本步骤不会填入示意电费、温度或接受标签。

## 解释边界

- 匹配补充面板在每个国家×角色组合中采用相同计数，主面板保留原时段。分析时应报告面板分层；这不等于估计全球事件发生率，也不声称全数据各变量统计独立。
- 一项至少出现一次意味着覆盖，不意味着足够独立样本支持该项单独的统计结论。
- 相同家庭的十题必须作为一个分组划分训练/验证/测试。源家庭与参考日程相近的依赖也应在最终拆分时检查。
- 原生执行、标签复算和复现检查证明构造一致性；生活自然性、热舒适、实际节能及人类偏好仍需物理验收和真人检查。

原参考配方、调查来源和生活规则见[完整算法](ALGORITHM.md)与[家庭依据表](../household_stage1/generator/EVIDENCE_MAP.md)。原版事件接口可直接核对[论文代码快照](paper_v1_clock_source.py#L96)及其[来源哈希](paper_v1_clock_source.provenance.json)。
