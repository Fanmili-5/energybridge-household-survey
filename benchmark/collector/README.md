# 参考家庭问卷采集器

Python标准库实现，无模型API依赖。公开HTTP协议测试完全使用新造的虚构数据，不需要微观调查、住房原件、EnergyPlus或生产数据库：

```bash
python -B benchmark/collector/test_protocol.py
```

这些输入只检验协议，不是可用于论文的仿真、家庭样本或人类标签。

有权限使用已封存50户源包的研究工作区可构建正式资料包：

```bash
python -B benchmark/collector/build.py --source /controlled/collection50_v67_20261017 --output /controlled/reference50_v1 --cohort-id reference50
python -B benchmark/collector/test_protocol.py --release /controlled/reference50_v1
python -B benchmark/collector/server.py --release /controlled/reference50_v1 --data-root /private/collection69 --public-origin https://your-host.example --port 18791
```

仅本地工程浏览器调试加`--fixture-mode`，生产答卷和测试库须分目录。虚构协议包强制只能在fixture模式运行。

家庭由系统分配，不能通过链接或请求字段自行挑选。一名匿名参与者对应固定`participant_id`及一个恢复码；每轮有独立`assignment_id`和`round_number`，固定一户及其10题。未填完只恢复原进度；完成且没有未提交修改后，可自愿点击“再评价一户”。同一身份不重复领取已领家庭，不预设每人轮数，完成本版本全部家庭后停止分配。新家庭必须重新阅读其角色背景，上一轮答卷原样保留。

分配按完整轮次数、有效期内未完成轮次数、历史开始数依次优先取少，相同时随机打散；实际候选、排位与分配结果保存在私有`participant_rounds.allocation_json`。完整不等于质量合格，分配不使用评分、接受判断或仿真成败。两小时占用只用于负载均衡，到期不删除身份、草稿或答卷。无需邀请码，没有12个位置上限。

原恢复码跨轮次找回最新进度。领取下一户以原轮次为幂等键，重复点击和并发不会领取多户；所有已恢复设备一起切到最新轮次，旧标签页写入被轮次绑定拒绝。撤回覆盖同一身份全部轮次。匿名cookie及恢复码不证明自然人唯一；清除cookie且不用恢复码会被当成新身份，不采集姓名或联系方式。后续分析、置信区间与训练/测试划分必须按`participant_id`关联多轮，不能把同一人的轮次当成独立受访者。

工程回归只用隔离虚构资料：`python -B benchmark/collector/test_rounds.py -v`。检查续填、多轮恢复、去重、并发幂等、旧页隔离、未提交修改、重启/备份和全轮撤回，不创建正式标签，不运行EnergyPlus。

保存记录绑定发布/家庭/案例/页面/问卷口径。查看历史独立于草稿持久化；提交追加修订、有回执、支持恢复与撤回。VPP客观值从封存案例复制，参与者只填自己的判断。四项1—5评分、接受/拒绝和原因必填，无默认答案。

私有管理命令：

```bash
python -B benchmark/collector/admin.py status --release /controlled/reference50_v1 --data-root /private/collection69
python -B benchmark/collector/admin.py backup --data-root /private/collection69 --output /private/backups
python -B benchmark/collector/admin.py review --release /controlled/reference50_v1 --data-root /private/collection69 --review-file /private/review.json
python -B benchmark/collector/admin.py export --release /controlled/reference50_v1 --data-root /private/collection69 --quality valid --output /private/reviewed.jsonl
```

复核JSON必须包含`actor_id,case_id,answer_revision,status,rule_version,reviewer,reason`；这里`actor_id`对应导出中的`assignment_id`，不可用跨轮次`participant_id`代替；status为`valid/excluded/pending`。结论追加保存并精确绑定答卷修订，新修订恢复为未复核。raw导出默认包含未复核记录并标注状态；`--quality valid`只导出当前修订已人工复核有效、同意且未撤回的记录。系统不按VPP达标、分数方向或多数意见自动筛答案。

状态分别统计匿名参与者数、分配轮次数、完整轮次数、最新提交和复核有效数，不能互换。SQLite及原始恢复pepper一致备份，保留前一快照；数据库、码、问卷原文答案和备份均不入Git。后续1000户使用同一接口，但仍须准备对应物理/摘要资料并单独验收，不能把50户结果外推为1000户已完成。
