# EnergyBridge 家庭用电偏好 Benchmark

当前基线是**50户、500组A46/B57**，每名参与者评价固定一户的10个日期。免邀请码、无时间轴，四项评分、接受判断及原因必填；支持保存、恢复、修订、撤回和版本化人工质控。

**[打开当前50户问卷](https://47.85.194.154/household50-current/)** · [版本清单](benchmark/releases/reference50-v1/MANIFEST.json) · [11项验收状态](benchmark/ACCEPTANCE.md)

| 对象 | 与当前版本的关系 | 已完成与待完成 |
|---|---|---|
| 50户/500组 | 同源原比例子集，六类5/15/16/5/4/5 | 当前参考物理V61、摘要V62及采集V69；真人有效标签待实际采集 |
| 1000户/10000组 | 包含这50户的同一主数据，A46/B57 | 输入已生成；本版全量物理、标签及最终评测未完成，继续暂缓 |
| 线上版本 | `reference50-v1` / V69，每人10题 | 不再限制为12人3题；保留原排程、仿真和B失败，不预填答案 |

旧版全1000户验收不能用于证明当前A46/B57已完成全量仿真。历史`/household50`、`/household950`及原自报家庭入口不代表当前版本。

## 数据如何生成

有来源约束的家庭骨架和住房 → 设备与支持边界 → 上游生活日程 → 正常A → 同需求下的VPP调整B → 同版A/B仿真 → 能耗、生活和客观VPP摘要 → 家庭角色评价。B可失败、不利或被拒绝；客观达标不等于接受。

[完整生成规则](benchmark/GENERATION.md) · [数据卡](benchmark/DATASET_CARD.md) · [采集质控](benchmark/COLLECTION.md) · [评测边界](benchmark/EVALUATION.md) · [复现步骤](benchmark/REPRODUCTION.md)

## 独立住房与仿真生成

[住房生成模块](benchmark/housing_simulation/README.md)提供不依赖历史1000户的完整物理构造流程：参考外壳、成员与设备自动装配、日历和服务绑定、A/B编译、EnergyPlus运行及统一审计。公开非空实例可复现三种家庭场景；输入Schema、算法、来源依据、项目规则及验证结果对应发布。该构造模块与上表中的既有数据集版本分别管理。

## 核验当前公开版本

```bash
python -B benchmark/verify_publication.py
python -B benchmark/collector/test_protocol.py
```

公开clone可核验源码、50/1000同源摘要与HTTP采集协议；测试只用虚构临时数据，不跑EP、不创建真人标签。获准研究工作区可按[采集器说明](benchmark/collector/README.md)构建、验证及部署对应受控资料包。

公开内容是当前代码、方法、格式、聚合证据和输入哈希。调查、逐户受控包、住宅/天气原件、完整EP输出及真人记录不在Git中；取得许可原件不自动意味着可以再分发。[来源与许可](THIRD_PARTY.md)

当前不是已完成真实标签、独立测试集和模型成绩的论文benchmark发布。具体划分与正式评测指标待确认冻结，工程测试与物理参考不能替代真人理解和研究有效性。

[完整基准入口](benchmark/README.md) · [旧主说明归档](docs/history/README_BEFORE_REFERENCE50_20261017.md)
