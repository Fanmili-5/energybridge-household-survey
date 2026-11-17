# 家庭与A/B的规则依据

本方法生成调查锚定的参考家庭决策情境：给定家庭、独立日任务与完整计划，收集真人对调整方案的判断。来源依据、建模原则和实验参数分别列出；标准求解器承担约束实现，不作为新的通用优化算法主张。

## 1. 家庭来源与选择

| 国家 | 主源版本 | 主要用途与边界 |
|---|---|---|
| 中国 | CRECS 2012 | 成员、亲属、就业、住房面积档、设备与可用在家信息；使用项目已有冻结原件 |
| 美国 | RECS 2020 v7 | 住宅、设备、人数及受访者信息；保留源插补标记 |
| 英国、西班牙、德国 | ENABLE.EU 1.0 | 共享调查工具便于映射；2019是发布年，不统一当作访问年 |
| 印度 | IRES 2020 | 家庭年龄组、设备、可用使用量与热水信息 |
| 墨西哥 | ENASIC 2022；ENIGH 2024 | 成员与照护来自ENASIC；住房跨户匹配ENIGH，不能写成同户观测 |
| 澳大利亚 | ECA June 2025原始表 | 家庭人数、就业、按日在家、设备与停车；与外部角色证据中的June 2026区分 |

原件网址、字段范围和八份文件SHA见[来源目录](../benchmark/household_stage1/SOURCES.json)。选国考虑逐户资料可取得、字段可映射和情境互补。每国125户用于均衡情境覆盖；不使用国家人口或源调查权重来估计全球分布。

| 规则 | 依据层次与采用方式 | 约束属性 | 实现 |
|---|---|---|---|
| 六角色及配额 | [EB附录A表7](https://arxiv.org/html/2608.08691v1#A1)的584名角色扮演者，计数97/116/73/88/91/119；最大余数分配166/198/125/151/156/204 | 实验配额；不是人口分类发生率 | [quotas.py](../benchmark/household_stage1/generator/quotas.py)、[ROLES.json](../benchmark/household_stage1/generator/ROLES.json) |
| 国家×角色交叉 | 整数矩阵保持行列总数，每国六类非空，单元接近边际乘积 | 设计硬约束 | quotas.py |
| 选源家庭 | 固定种子哈希排序，按就业、年龄、在家和照护相容性搜索；每源最多尝试4个补全；源键去重 | 相容性筛选；不等同于概率抽样 | [pipeline.py](../benchmark/household_stage1/generator/pipeline.py) |
| C/D配对 | 同国、匹配块及来源设备签名内选择不同源户；相同控制组合 | 设计控制；不证明角色因果效应 | pipeline.py、[allocation.py](../benchmark/household_stage1/generator/allocation.py) |
| 角色与态度 | EB实验角色语义；[Fell等](https://discovery.ucl.ac.uk/id/eprint/1471898/)支持区分经济、自动化与控制接受度等维度 | 角色条件；不由源户国籍或收入推断个人偏好 | ROLES.json、[规则表R01—R02](../benchmark/household_stage1/generator/RULES.json) |
| 参考周 | 调查可用生活约束；[Richardson等](https://doi.org/10.1016/j.enbuild.2008.02.006)支持活动/在家与工作日、周末的区分；[LPG](https://doi.org/10.21105/joss.03574)支持由人的活动导出用能需求 | 活动相容性为硬约束；本实现不运行上述论文的随机/心理模型 | [规则表L01—L06](../benchmark/household_stage1/generator/RULES.json) |
| 4—6类控制 | 六功能AC/WM/DR/DW/WH/EV；AC必备必控，F含EV；4/5/6类333/333/334户 | 本实验设计；补设备保留干预来源 | allocation.py、规则表C01—C02 |

## 2. 具体生活参数

这些值将参考情境具体化，不声称由八国时间使用数据估计。源约束优先，无法相容时拒绝候选，不为凑覆盖改原事实。关键字段的逐国家来源数量见[聚合统计](GENERATION_STATISTICS.md)。

| 参数 | 本版值或规则 | 依据及解释 |
|---|---|---|
| 工作和通勤缺省量 | 全职40小时/周、兼职20小时/周、往返通勤40分钟 | 仅缺失时的实验默认；有可用源量时使用源约束 |
| C的日程变化 | 工作日偏移[0,60,-30,45,-60]分钟；参考通知提前60分钟 | 受控变化条件，不估计真实随机性 |
| 用餐 | 早餐不晚于07:30、午餐12:30附近、晚餐18:00后结合返家安排 | 参考模板，检查交通与人员冲突 |
| 洗浴与协助 | 默认10分钟；不足6岁15分钟并安排协助 | 情境规则，非医疗结论或各国规范 |
| 舒适参数 | 角色对应参考温度偏好与调整容忍；具体字段见规则表T03及ROLES.json | 偏好用于条件描述，不自动作为B动作禁令或接受标签 |
| EV硬件 | 参考50/60/75kWh、效率0.9、目标SOC0.8；缺失Level2功率3.6/7.2kW | 具体以家庭卡为准；不是源户设备测量 |
| 独立日状态 | 每题分别给定连接、到家SOC及目标；同题A/B一致 | 十题不组成连续十天的车辆状态轨迹；同一情境内不重置需求 |

生活规则的完整机器记录见[RULES.json](../benchmark/household_stage1/generator/RULES.json)，文献支持范围见[EVIDENCE_MAP](../benchmark/household_stage1/generator/EVIDENCE_MAP.md)和[REFERENCES](../benchmark/household_stage1/generator/REFERENCES.json)。

## 3. 任务、A、B与选题

| 对象 | 本版规则 | 依据与属性 | 实现 |
|---|---|---|---|
| 任务承诺 | 在A/B之前固定日期、批次、来源事件、准备时间、截止和设备需求 | 同题比较条件；生成器不读取后果或标签 | [task_commitment.py](../benchmark/ab_generation/task_commitment.py) |
| 洗衣与烘干 | 前一天参考换衣批次；有烘干时接同一批洗衣 | 负载来源是明示实验规则；原活动不是衣物数量测量 | [task_context.py](../benchmark/ab_generation/task_context.py) |
| 洗碗 | 从既有在家餐次中确定一批；备齐且满足原设备最早执行时刻才可开始 | 选择在计划前完成，不能事后补餐次解释B | task_context.py |
| 每日完整任务 | 题目给定一次完整所需程序，非EV当天完成 | 本实验任务子域，不推断真实逐日使用频率 | task_context.py |
| 程序时长/功率 | WM120min/1.5kW；DW90min/1.2kW；DR90min/2.5kW | 锁定[EB persona配置](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0/energybridge/roleplay/personas/all_appliances_full.json)的参考参数，不是接口唯一合法值 | [参考参数](../benchmark/ab_generation/examples/EB_REFERENCE_RULES.json) |
| A排程硬约束 | 准备/截止、完整连续程序、同批先后、共享设备独占 | 任务一致性；最优解不证明自然作息分布拟合 | [household_routine_A.py](../benchmark/ab_generation/household_routine_A.py) |
| A排程目标 | 优先减少22:00后完成，再减少参考时刻偏移、洗后等待；在家仅作软时刻条件 | 22:00为实验软偏好，不是B禁令；A不读取事件收益/B/答案 | household_routine_A.py |
| A参考启动 | WM按A—F取19/10/19/13/10/20点锚点；可用周末上午偏好10点；DW跟随实际批次准备 | 采用的EB角色参考锚点及本项目具体化；锚点为软目标 | 参考参数ordinary_A、household_routine_A.py |
| A热服务 | AC/WH按明示参考服务规则；EV给定连接与SOC需求 | 设定/许可不保证实际温度或服务结果 | [eb_primary.py](../benchmark/ab_generation/eb_primary.py) |
| B动作范围 | AC制冷设定；完整程序起点；可控WH一段许可窗口/目标；EV连接内连续许可窗口 | 锁定[原EB主消费者](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0/experiments/benchmark/family_runner.py)及原电器源码；不新增装卸、插拔或停冷 | [原动作核对](../benchmark/ab_generation/eb_agent_contract.py) |
| 连续与能量要求 | 程序不拆碎；EV硬件、初始/目标SOC不变；连续EV是本任务子域 | 不声称所有间断充电都物理错误 | [eb_primary_candidates.py](../benchmark/ab_generation/eb_primary_candidates.py) |
| 候选搜索 | 在完整见证约束下进行IPOG-C式横向/纵向组合扩展；有预算和UNKNOWN状态 | 参考[Yu等，ICST2013](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=913191)；项目增加完整扩展见证、预算和混合强度处理，不声称等同原ACTS全部实现 | [ipog.py](../benchmark/ab_generation/unified/ipog.py)、[candidates.py](../benchmark/ab_generation/unified/candidates.py) |
| 户内与全队列选择 | 每日期一个B，保护户内基础与有机会功能、根动作覆盖，再争取跨国重复 | 标准MILP及CP-SAT；预算内FEASIBLE不等于全局OPTIMAL | [selection.py](../benchmark/ab_generation/unified/selection.py)、[cohort_recipe.py](../benchmark/ab_generation/cohort_recipe.py) |
| 外部事件 | 默认18—19；补充起点16—20、10分钟网格、持续1小时 | 先声明事件再产生候选；是场景覆盖设置，不代表各国电网事件频率 | [scene_coverage.py](../benchmark/ab_generation/scene_coverage.py) |
| 拒绝与软冲突 | 动作/任务硬错误排除；不喜欢、软舒适冲突、零/负名义效果可保留 | 不预造接受标签；未知热响应不当作零 | [ALGORITHM](../benchmark/ab_generation/ALGORITHM.md) |

CP-SAT与MILP的求解语义分别见[OR-Tools官方文档](https://developers.google.com/optimization/cp/cp_solver)和[SciPy官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)。版本与实际预算取运行清单及[依赖锁](../benchmark/ab_generation/generation-requirements-lock.txt)；统一generation_pipeline入口默认读取[GENERATION_REPAIR_CONFIG](../benchmark/ab_generation/GENERATION_REPAIR_CONFIG.json)及[COMPLETION_CONFIG](../benchmark/ab_generation/COMPLETION_CONFIG.json)；其他统一模块可读取[CURRENT_CONFIG](../benchmark/ab_generation/unified/CURRENT_CONFIG.json)，二者不混称同一套默认值。封存历史复现使用归档配置，不能以最新默认值代替。

## 4. 可支持的论文主张

本方法提供来源可追溯、任务一致、对齐原EB动作且覆盖可检查的家庭用电配对情境。八国历史调查、角色模板和活动规则共同约束情境；完整作息不是同户真实日记。整份计划的真人判断是后续监督信号。

规则检查支持构造一致性。自然性、实际物理服务及偏好预测有效性需要相应证据；物理后果和真人标签当前为空。复现层级见[流程](GENERATION_REPRODUCIBILITY.md)，有限覆盖和分组见[统计](GENERATION_STATISTICS.md)。
