# 家庭六类偏好：第一条方法主线 v1

本模块固定**EB预定义六类 → 外部原始问卷核查 → 明示实验设定 → 前序实验构成参考配额 → 版本化披露**的方法。六类用于覆盖不同决策情境，不是本研究从人口调查发现的六个互斥人群。

**定型范围是方法、证据与拟议配额政策。现有50户/1000户的成员、设备、角色、A/B、仿真、费用和问卷均未修改，线上版本未更新，1000户仿真继续暂停。** 未来配额166/198/125/151/156/204尚未应用，不能将它描述为现有数据构成。本模块也不宣称已验收全部家庭人口/住房/设备生成或完成真人偏好验证。

| 阅读目的 | 文件 |
|---|---|
| 六类如何定义、哪些有依据、哪些是人为设定 | [METHOD.md](METHOD.md) |
| 各调查实际验证了什么、没有验证什么 | [EVIDENCE.md](EVIDENCE.md)、[evidence/SUMMARY.json](evidence/SUMMARY.json) |
| EB配比来源、逐步计算和拟议结果 | [ALLOCATION.md](ALLOCATION.md)、[PROPOSED_ALLOCATION.json](PROPOSED_ALLOCATION.json) |
| 论文可以直接采用的中文/英文方法表述 | [PAPER_TEXT.md](PAPER_TEXT.md) |
| 从公开原始文件复算及离线核验 | [REPRODUCE.md](REPRODUCE.md)、[INPUTS.lock.json](INPUTS.lock.json) |
| 来源、版本、许可和证据限制 | [SOURCES.json](SOURCES.json) |
| 方法与证据包的内容锁 | [PACKAGE_MANIFEST.json](PACKAGE_MANIFEST.json) |

仅复算配额不需要第三方Python库、原始答卷、旧1000户或EnergyPlus：

```bash
python -B benchmark/household_archetypes/allocate.py
python -B benchmark/household_archetypes/verify.py
```

参考配额与未来模型性能要分开评价。正式评测拟报告逐类、六类等权平均及整批结果；这是同一批数据上的汇总方式，不拆分数据，也不声称已经完成模型性能或真人效度实验。角色的普通请求接受先验不作为任何案例的答案标签，费用收益、VPP达标和约束可行也不直接生成接受标签。

v1更新规则：来源数据、角色定义、配额规则或证据解释有实质变化时另发方法版本并记录原因；实际数据迁移另立版本，不能只换标签、文件名或论文措辞。后续A/B与住房仿真两条方法主线与本模块分别管理。
