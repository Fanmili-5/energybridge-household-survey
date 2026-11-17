# 全队列分配与封存版重建

规则与参数依据见[统一依据表](../../docs/GENERATION_RULES.md)，复现范围见[流程](../../docs/GENERATION_REPRODUCIBILITY.md)，覆盖和分组见[聚合统计](../../docs/GENERATION_STATISTICS.md)。

入口为cohort_recipe.py。它接收完整、已验证的上游候选池，在固定家庭、任务和A上分配题位；不启动EnergyPlus、不调用LLM、不生成真人答案。

## 两个不同用途

| 用途 | 命令 | 选择从哪里来 |
|---|---|---|
| 新批次全队列分配 | solve，再rebuild --selection | CP-SAT重新求解；不读取历史选择文件 |
| 重建已经封存的版本 | reproduce | 明示的历史候选ID记录；重新应用补丁并执行原始电器检查 |

历史多轮有预算求解没有保存足以保证从头得到相同离散选择的全部运行次序，且可存在多个合格解。精确重建需要固定候选池与选择记录。这里证明的是完整封存数据的重建，不把它描述成独立重跑全部候选发现和历史优化过程。

历史选择来自算法分配，不是真人接受标签。重建包不复制最终B计划；它含调查许可约束下的家庭、已审A/任务/场景、完整候选补丁、初选、逐户保护条件和候选ID锁。原始调查、真实家庭卡、候选包及选择锁留在受控存储，不放GitHub。

## 准备一次受控输入包

使用Python3.14.3与本模块generation-requirements-lock.txt。候选池可由基础generation_pipeline和候选补全模块产生；本入口不重新运行候选发现。需要先补齐有机会的功能候选，不能靠改家庭生活消除缺口。

~~~bash
python -B -m benchmark.ab_generation.cohort_recipe freeze \
  --batch /authorised/sealed-native \
  --households /authorised/household_cases.jsonl \
  --out /authorised/cohort-recipe
~~~

默认从初选提取基础覆盖，从家庭控制集合及候选池确定功能要求；缺候选时只有可检查的有限域无机会证明才允许例外。--required与--opportunity可显式传入上游冻结合同。每个文件及整包都有内容指纹。原家庭、负载来源、准备时刻和A保持不变；新包须使用新目录。

## 一条命令重建当前1000户×10题

~~~bash
python -B -m benchmark.ab_generation.cohort_recipe reproduce \
  --bundle /authorised/cohort-recipe \
  --native-source /authorised/pinned/appliance_sim.py \
  --reference-batch /authorised/current-native \
  --reference-questions /authorised/current-question-inputs \
  --out /new/identical-materials --workers 7
~~~

命令先独立物化输出，再读取reference作比较。它根据历史候选ID，在同题A上应用完整补丁，重新核验原EB调用、任务、同批依赖和设备功能覆盖，对A/B都执行原始电器回放，再导出问卷输入。

逐题比较A/B内容和哈希、任务SHA、具体事件、上下文、场景身份、pair_id及完整问卷输入。少题、多题、重复题或任一项不同均失败；gzip压缩时间及运行日志不作为科学内容一致的条件。原题、原答卷及线上服务不覆盖。

## 真正重新求解一组新B

~~~bash
python -B -m benchmark.ab_generation.cohort_recipe solve \
  --bundle /authorised/cohort-recipe \
  --out /new/allocation --workers 6 \
  --deterministic-time 60 --seed 20261116

python -B -m benchmark.ab_generation.cohort_recipe rebuild \
  --bundle /authorised/cohort-recipe \
  --selection /new/allocation/CHOICES.json \
  --native-source /authorised/pinned/appliance_sim.py \
  --out /new/materials --workers 7
~~~

每个家庭日期恰选一个候选。硬约束保护每户初选基础覆盖、全部有事件机会的控制功能及当前池内有完整见证的根动作格；目标优先增加两国重复，再减少相对初选的换题。输入和约束按固定顺序编码，每角色单线程，记录种子、确定性预算、求解器版本、状态、目标值与界。FEASIBLE不写成OPTIMAL，UNKNOWN/INFEASIBLE不制造选择。

solve不会打开历史选择文件；实跑时该文件被从搬迁后的求解输入目录排除。新解可与封存版不同，预算内不保证达到原版跨国重复水平。新数据须作为独立版本验收，不能自动替换正式批次。

## 已验证范围

当前封存版1000户×10题已重建并逐题比较，10000题的任务、事件、A/B、场景和完整输入全部一致，差异0；搬迁工作目录、候选包及原始电器源码路径后同样通过。重建问卷索引SHA为d3e98203dea35988b7840250388da649f8b4fc29fff67a83e3e324e3c3a1c20c。

封存版保持939个根动作格、924格至少两国、15格单国。新求解也在全部1000户上完成并物化10000题，原始执行检查20000份，根动作939格；其两国重复为918格，未替换原版。差异体现有预算的候选池优化，不宣称全局最优或独立再现历史每轮搜索。

这些验证不产生物理后果或真人答案。日期/任务是参考情境，角色权重与国家等额是实验设计；既有物理、标签和分组划分边界继续适用。
