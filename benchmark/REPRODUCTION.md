# 当前v4复现入口

新B与v69封存请使用[项目模块](project/README.md)的reference_collection与reference_collection_release命令。未计算结果保持空值；不调用旧B物理输出。完整500题需获准的原50户输入，公开六户用于方法复现。

[当前发布](releases/reference50-v4-proposal/MANIFEST.json) · [方法与来源](ab_generation/COLLECTION_METHOD.md)

---

以下为**历史reference50-v1 / A46-B57**说明，保留来源和验证历史，不代表当前新B的物理结果。

# 复现与版本核验

## 公开clone可以做什么

```bash
git clone https://github.com/Fanmili-5/energybridge-household-survey.git
cd energybridge-household-survey
python -B benchmark/verify_publication.py
python -B benchmark/collector/test_protocol.py
```

第一条检查当前公开清单、源代码哈希、50/1000同源关系及状态一致性。第二条以临时虚构50户500例跑真实HTTP/SQLite协议测试，不调用模型或EnergyPlus，不需要私有原件，也不产生人类标签。测试夹具不是仿真数据或可浏览研究样本。

## 已获准的研究工作区

需要对应版本的调查/匹配资料、住房与天气、EB源、EnergyPlus24.1及阶段输入锁。按原路径准备受控输入，不在Git中放原件。各个阶段的最终源码及只读祖先依赖已公开；私有输入缺失时不能宣称完整重生成成功。

| 阶段 | 固定位置及入口 |
|---|---|
| 主数据V33 | `scripts/household_master.py resources/build/review/export/seal/verify` |
| A46 | `scripts/generation_thermal.py A build/review/design-review/family-review/...`，`normal_A_v46_20261017` |
| B57 | `scripts/generation_semantic_closure.py B build/review/report/seal/verify`，`candidate_B_v57_20261017` |
| 物理V61 | `unified_physics50_v61_20261017/code/experiments.py`，限定原50户 |
| 摘要V62 | `impact_summary50_v62_20261017/code/regenerate.py`及`code/verify.py` |
| 页面与采集V69 | `benchmark/collector/build.py`、`server.py`、`admin.py` |

按“家庭与设备→生活日程与A→B→同版仿真→影响摘要→页面→答卷”的顺序生成，旧阶段不覆盖。源码目录完整路径及哈希见`generation/SOURCE_CATALOG.json`；所有输入、种子、参数、执行回执和再生成原因须保留在受控阶段。由于来源许可和部分早期开发快照不完整，这里不承诺任意公开机器可从空目录重建全国调查或每轮中间产物。

已封存50户源包可按[采集器说明](collector/README.md)重建页面/采集包并运行受控资料协议验收。用`verify_publication.py --controlled-release /path/to/reference50_v1`核对500份案例与50份家庭字节，不启动EP。公开索引不是原始数据替代物。

线上版本以`releases/reference50-v1/MANIFEST.json`和`/household50-current/api/health`中的发布摘要核对。部署源码摘要必须相同；数据库绑定发布，不将新包挂到旧库，不把旧模型结果挪到新版本。备份须含SQLite与同一恢复pepper，并实际测试恢复。

后续1000户继续使用同一采集器和数据协议，仍须独立生成并验收10000组对应物理/摘要及负载。当前50户的通过范围不会因规模字段改成1000而扩张。

## 独立家庭构造与连接

[家庭模块的公开命令](family_generation/README.md#公开复现)可在没有旧世界、调查个人原件和历史运行目录的环境中生成六类合成参考家庭，并实际连接住房装配及生活A。基础生成只用标准库；连接使用住房固定依赖。运行包与输入完整性检查、20项测试和CI随模块发布。六个公开示例不等于历史1000户人口抽样已可公开重建，且本流程不启动EP、不产生接受标签。
