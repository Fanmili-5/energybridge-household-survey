# 家庭生成与稳定画像

六类核心固定，类内采用相关采样，同一户十天冻结；不从A倒推个人习惯，不随机扩大设备能力或授权。
当前家庭基线为v3，相关算法、实验参数及成员归属见[方法](HOUSEHOLD_PORTRAIT_V3_METHOD.md)。

公开六类合成池可以独立生成家庭：

```sh
python -B -m benchmark.family_generation generate --input benchmark/family_generation/examples/batch_joint_v3.json --out NEW_FAMILIES
python -B -m benchmark.family_generation verify NEW_FAMILIES
```

生产规模由输入配置决定，公开池不代表人口分布。旧batch.json及历史模式保留。
下游当前方法、配置和公开六类生活→A/B入口见[REPRODUCE](../research_delivery/REPRODUCE.md)。

源码保留历史验证入口，但原50户完整输入、逐户候选画像和家庭派生测试夹具未公开。
依赖examples/energy_portrait/input.json或current_two.json的历史测试只可在授权完整资料环境运行；
不能用公开子集的缺失文件声称该历史验证已公开重放。公开CI只运行明确列出的子集。
本包PACKAGE_MANIFEST锁定实际公开文件；原完整清单身份记入发布边界，不把裁剪后清单当作原验证。

来源见[SOURCES](SOURCES.json)及[采样证据](JOINT_SAMPLING_EVIDENCE_V3.json)。
成熟随机方法不证明偏好分布真实，v2.10也未重新生成原50户画像或日程。
