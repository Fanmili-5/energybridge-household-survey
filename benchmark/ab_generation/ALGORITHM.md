# 调查约束、任务先行的配对计划构造

本模块把调查约束的家庭、参考生活、明确任务与EB原版动作连接为完整A/B判断题。使用既有配额、整数规划、CP-SAT和IPOG-C式搜索，不声称新的通用优化器或实测行为模型。

## 输入输出

输入：版本锁定的家庭JSONL、EB参考设备参数、日期、10分钟指令网格、外部事件、种子和搜索预算。输出：完整A/B、同题任务/上下文、来源与实现指纹、候选/选择台账、原版执行证明、索引和问卷输入；不生成物理后果或真人标签。

家庭来源及算法见[家庭生成器](../household_stage1/generator/METHODS.md)。当前八国各125户、六类166/198/125/151/156/204；每户4—6类且AC必控。

## 算法

1. task_context.derive_tasks只读家庭生活、日期和设备参数。衣物来自前一天活动/换衣；洗碗指定已记录在家餐次。准备时间取负载备齐与原设备最早执行时刻的较晚者。烘干等待同批洗衣。任务不能由B反推。
2. household_routine_A用单线程CP-SAT安排连续完整程序，满足准备/截止、同批前置和共享设备独占。先尽量减少22:00后完成，再减少参考启动偏移及洗后等待；模型最优不代表拟合真实作息。AC/WH/EV使用明示参考规则。A不读取响应收益、B或标签。
3. unified.candidates在相同A/任务和原动作域做IPOG-C式受约束组合搜索。只改完整程序起点、AC制冷设定、可控热水许可窗口/目标和EV许可窗口。不改功率/容量/程序长度/需求/EV目标，不增加装卸、插拔、停冷。
4. 核对原版调用和实际时钟、任务准备、同批顺序、设备独占、完整程序与连续补能。接口/任务错误排除；软偏好冲突和负/零名义事件效果不直接排除。UNKNOWN与已证无解分开。
5. 户内整数规划每日期只选一个B，优先保护已见证联合任务阶数，再权衡功能/取舍与重复。队列CP-SAT保护每户基础覆盖，覆盖有机会的功能和有完整见证的根动作格，争取跨国重复、减少换题。预算内可行解不等于全局最优。
6. 需要时在同一任务/A上补合法完整见证；补充事件先声明再生成候选。默认18:00—19:00；额外事件起点16:00—20:00、10分钟一格、持续1小时，不代表各国真实频率。无机会须有冻结域证明，搜索失败不等于无解。
7. 对落盘A/B重新调用原接口并封存身份。question_inputs核对家庭、任务、场景、A/B，拒绝旧B事后补任务、任务改写、身份错配和隐藏的非EV跨日改变。生成器判断和覆盖诊断不投给受试者或模型。

~~~text
H = survey_compatible_households(quotas, sources, seed)
for household, date:
    T = derive_tasks(H, date, reference)  # no A/B/outcome/label input
    A = solve_ordinary_reference_plan(H, T)
    candidates = bounded_original_EB_candidates(H, T, A, declared_event)
    keep task-valid and native-executable candidates
    select one B for this household/date
complete witnessed gaps without changing H, T or A
allocate cohort slots while protecting per-household coverage
replay and seal A/B identities
compile judgment input; consequences=null; targets=null
~~~

## 原版依据和实验条件

主消费者锁定为[family_runner.py，c58a2a7a](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0/experiments/benchmark/family_runner.py)，电器源码为[appliance_sim.py](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0/energybridge/simulation/appliance_sim.py)，SHA256为be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9。

洗衣/洗碗/烘干120/90/90分钟、1.5/1.2/2.5kW来自原版[all_appliances_full.json](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0/energybridge/roleplay/personas/all_appliances_full.json)，是本版参考参数，不是接口唯一合法参数。旧HPXML四小时程序不再作为这批计划的依据。

每日给定完整程序、同批洗后再烘、非EV不跨夜和EV连续补能，是本实验任务子域。后加adaptive-v3或独立RL baseline范围不作原EB禁令。22:00只影响A构造；居民偏好留待判断。设定值/许可窗口与实际室温、水温和能耗分别报告。

## 当前封存范围

- 1000户×10个独立日情境，10000对计划、10000份同题输入、20000次原版执行检查；不是连续10天车辆/家庭状态轨迹。
- 当前939个有完整见证的根动作格全部入选；924格至少两国、15格一国。不是全部连续动作或高阶组合覆盖。
- 旧969格中925格命中、44格在当前冻结条件下未获机会；另有14个本版新格。旧969/969是上一批成绩。
- 4990个有事件机会的家庭×功能项入选；另11项保留无机会证明，不为覆盖改生活。
- 负/零名义效果和软偏好冲突保留；未知热效应不算零。
- 本版后果和真人答案为空，尚不是可训练的完整偏好数据集。

## 统一入口

任务预提交由task_commitment完成：整批在任何A生成前保存任务，调用者已有冻结任务则先核验身份；缺失或不匹配直接失败。generation_pipeline在封存后调用prepare_question_inputs。主验收Python3.14.3，使用统一依赖锁；只写新目录，不启动EnergyPlus、LLM或线上问卷。

~~~bash
python -m pip install -r benchmark/ab_generation/generation-requirements-lock.txt
python -B -m benchmark.ab_generation.generation_pipeline \
  --make-example-pool \
  --household-config benchmark/household_stage1/generator/configs/pilot96.json \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --native-source /path/to/pinned/appliance_sim.py \
  --start-date 2007-07-18 --workers 4 --out /path/to/new-demo96
~~~

演示为SYNTHETIC源池，不代表调查数据。真实数据按许可准备，或传入冻结的--households和--expected-household-sha256，不能混用源池模式。

公开generation_pipeline提供基础候选补全、队列重选与封存，可生成新批；不承诺逐字节重建当前V4经过额外全队列分配后的每个B。--reference-batch仅最后比较计划哈希，不参与生成。额外全队列分配及封存版重建现由[cohort_recipe命令](COHORT_RECIPE.md)提供：solve重新求解，reproduce依明示历史候选ID锁重建；后者不构成独立重跑历史所有搜索。

单户与分步入口见[README](README.md)。已封存、已绑定任务身份的批次可导出同题输入：

~~~bash
python -B -m benchmark.ab_generation.prepare_question_inputs \
  --households /path/to/household_cases.jsonl \
  --batch /path/to/sealed-native-batch \
  --out /path/to/new-question-inputs
~~~

该命令不把旧未绑定任务的批次升级为合格题目。见[输入合同](QUESTION_INPUTS.md)。

家庭来源、配额、控制覆盖、任务因果、原版执行和身份绑定分别验收；物理服务及真人理解需后续验证。拆分需处理家庭、来源、C/D构造组与参与者关系。内部审查报告和工程日志不放本仓库。
