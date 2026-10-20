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

每个身份固定一户及该户10题。开始时按完整提交人数、有效期内的填写会话、历史开始数分配；两小时的分配占用只用于负载均衡，到期不删除身份、草稿或答卷。无需邀请码，也没有12个位置上限。匿名身份不证明自然人唯一，由组织者在私有招募台账中核对。

保存记录绑定发布/家庭/案例/页面/问卷口径。查看历史独立于草稿持久化；提交追加修订、有回执、支持恢复与撤回。VPP客观值从封存案例复制，参与者只填自己的判断。四项1—5评分、接受/拒绝和原因必填，无默认答案。

私有管理命令：

```bash
python -B benchmark/collector/admin.py status --release /controlled/reference50_v1 --data-root /private/collection69
python -B benchmark/collector/admin.py backup --data-root /private/collection69 --output /private/backups
python -B benchmark/collector/admin.py review --release /controlled/reference50_v1 --data-root /private/collection69 --review-file /private/review.json
python -B benchmark/collector/admin.py export --release /controlled/reference50_v1 --data-root /private/collection69 --quality valid --output /private/reviewed.jsonl
```

复核JSON必须包含`actor_id,case_id,answer_revision,status,rule_version,reviewer,reason`；status为`valid/excluded/pending`。结论追加保存并精确绑定答卷修订，新修订恢复为未复核。raw导出默认包含未复核记录并标注状态；`--quality valid`只导出当前修订已人工复核有效、同意且未撤回的记录。系统不按VPP达标、分数方向或多数意见自动筛答案。

状态分别统计身份数、最新提交和复核有效数，不能互换。SQLite及原始恢复pepper一致备份，保留前一快照；数据库、码、问卷原文答案和备份均不入Git。后续1000户使用同一接口，但仍须准备对应物理/摘要资料并单独验收，不能把50户结果外推为1000户已完成。
