# 家庭与A/B生成

本版采用任务先行：家庭和参考生活 → 明确负载来源与准备时间 → 日常A → 原版EB动作候选 → 每日期一个B → 封存并投影同题输入。

- [完整算法、依据、覆盖与复现范围](ALGORITHM.md)
- [家庭生成](../household_stage1/generator/README.md)
- [同题问卷输入合同](QUESTION_INPUTS.md)
- [当前聚合状态](../../docs/BENCHMARK_STATUS.json)

A用CP-SAT安排完整程序，优先减少晚间延后及参考时刻偏移；B使用有限原版动作域、IPOG-C式受约束搜索和整数规划选择，队列分配争取覆盖。B可以不受居民欢迎，不能通过偏好或节电正负代替真人标签。

本版洗衣/洗碗/烘干120/90/90分钟来自原EB persona参数，完整不中断；同批先洗后烘，非EV不跨夜，EV连接内连续补能。每日工作负荷和连续补能是实验条件；原EB接口、参考硬件、任务和居民软偏好分别验证。

## 复用

使用Python3.14.3及generation-requirements-lock.txt。完整基础入口为generation_pipeline，见[统一入口](ALGORITHM.md#统一入口)。它支持公开合成源池、授权调查来源或冻结家庭，不启动物理引擎或生成标签。当前V4在该基础上额外做了固定A的全队列补全/分配；公开基础入口不承诺精确重建该封存批次每个B。

单户原生计划：

~~~bash
python -B -m benchmark.ab_generation.generate_native \
  --households /path/to/household_cases.jsonl --case-id YOUR_CASE_ID \
  --reference benchmark/ab_generation/examples/EB_REFERENCE_RULES.json \
  --start-date 2007-07-18 --days 10 \
  --native-source /path/to/pinned/appliance_sim.py --out /path/to/new-output
~~~

整批基础生成用generate_cohort（去掉--case-id，增加--workers）。完整基础配方另外进行候选补全、队列重选与封存，不应将单次候选生成称作全覆盖验收。

已封存、已绑定完整任务/场景身份的批次，通过prepare_question_inputs导出同题材料；旧任务结构不能事后升级。输出后果与答案为null，collection_ready=false。

## 范围

1000户×10题、20000次原版执行检查；当前939个见证根动作格均出现，924格至少两国、15格一国。旧969格中925格命中、44格在当前冻结条件下未获机会，另有14个新格。物理后果和正式真人采集仍未完成。

[旧场景分配方法](SCENE_ALGORITHM.md)及其他历史示例保留各自版本，不能继承其仿真结果或覆盖成绩。原“4335个B一概不合格”的口径已撤回；居民拒绝与执行错误分别处理。
