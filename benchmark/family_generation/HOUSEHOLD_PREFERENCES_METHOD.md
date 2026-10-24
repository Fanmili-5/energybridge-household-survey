# EB共享家庭与成员偏好继承 v4

历史版本说明：v4按固定规则匹配成员画像。新启用的`within_class_joint_v1`改为六类固定、成员只做类内联合随机，不能沿用下文跨类别成员分配规则解释新模式。现行候选方法见[JOINT_SAMPLING_METHOD.md](JOINT_SAMPLING_METHOD.md)。旧配置仍保留v4路径。

2026-10-22。本地候选材料版本；实现于`household_preferences.py`，由统一的`device_persona.generate_personas`调用，家庭构造、既有家庭补充和日程接口均使用同一编译入口。本次只验0696、0756两户及既有20组A/B，不更新线上，不运行EP，不启动1000户。

## 来源与继承

固定EB提交`2b17ae63e613da776c93e900f5dace50d63a88a8`。`ENERGY_PORTRAIT_SOURCES.json`锁定原角色卡、六个basic角色、五个household、四个实际启用的atom角色及家庭加载代码，共17个文件。`EB_HOUSEHOLD_PREFERENCE_SOURCES.json`只保存继承所需字段；不移入评分权重、接受概率、答卷或真实家庭分布声明。

顺序为：本户原设备清单/原服务需求与明确声明 → EB家庭共享使用规则 → 成员偏好保留并按实际受影响范围关联。原EB household配置优先于个人appliance示例，个人`present=false`不能删除共享设备，个人`dr_adjustable=false`不能替换家庭机器的共享资格。成员对改变的反感仍保留，不等于其个人角色卡已授权家庭机器。

六类标签保留为本户给定的总体决策取向，不再暗示每个成员心理都相同。成员角色为实验角色，不是真人测量。EB原五种家庭本身不是六种互斥的家庭人口分类。

## 确定性联合分配

先读取白名单内的家庭、成员、资产资格、原日程、原服务及既有权限；不读A/B命令、评分、结果或选题标签。

共享情境参照顺序：明确`EB_household_id`优先；否则明确照护→S2，明确居家工作→S3，给定C类→S5，给定F且拥有EV→S4，其余→S1共享家务参照。这里只取共享规则，不复制原家庭的人口、关系、原EV拥有、原洗浴时刻或固定成员数；也不宣称新家庭完全等同原EB情境。该匹配顺序是**项目实验设定**，不是文献拟合出的分布。

成员方面，明确`energy_preferences.member_personas`优先，其次原决策人保留给定六类角色。只继承角色内部联合的能源偏好维度，不复制其通勤作息、人口身份或个人设备拥有；例如选用D类能源偏好，不会把原在家成员变成通勤者。当前新增联合规则为：

| 联合情境 | 非决策成员的角色分配 | 来源及边界 |
|---|---|---|
| B类舒适主导 | 有原学校/学习活动者分配`atom_task_rigid`；原共享家务登记操作人分配D类；其他人分配`atom_price_indifferent` | 复用EB完整成员角色，组成新实验组合；先匹配学习者，再匹配操作人，不按年龄或性别推断偏好 |
| F类居家工作情境 | 居家工作者分配B类；其他有学校/学习活动者分配`atom_task_rigid`；其余分配`atom_control_auto` | 参照S3成员分歧及S1固定任务机制；不会把其个人设备配置覆盖到共享设备 |
| F类灵活情境 | 原共享家务操作人分配D类，其余分配`atom_price_indifferent` | 参照S4整体角色组合，适配原成员数量；不新增人或设备 |
| 其他情境 | 继承家庭核心；有明确成员声明时覆盖 | 明确记录是默认实验继承，不能声称每个成员都被独立测量 |

**这些分配是声明出来供roleplay的联合实验条件，不是“做居家工作的人必然是B类”的经验规律。** 没有随机数、ID哈希档位或逐户唯一约束；不变输入可以生成相同偏好。任意950户的心理真实性、分布代表性和全部类型有效性尚未证明。

## 逐设备含义

- 洗衣/烘干/洗碗：EB共享惯常时间与窗口进入实际家庭文字，不再仅存为未使用的参考字段；明确的原程序偏好时间优先。参考时间为软偏好，不是新的硬期限，不要求改A来满足。烘干参考时间不自动证明同一批；原洗烘一体/批次与程序依赖不变。
- 空调：共享制冷范围和实际使用成员的个人偏好同时保留。决策人若并未使用某房间，不因其确认权而把其个人温度偏好塞进该房间。制热、提前运行和停机不由制冷偏好自动授权。
- 热水：习惯提前备水；EB预热窗口只是参考，原各段用水时间、温度、水量不变。成员需求不被平均成只有第一人需要热水。
- EV：使用原行程、连接和目标SOC；两户原85%不替换为EB个体F的80%或原出行最低值。偏好择时和授权择时分开。
- 冰箱：若原清单没有独立冰箱记录，不新增设备。EB共享源中的冰箱只保留为来源参考，不虚构控制或功率。

## 授权与成员作用范围

按原登记操作人关联洗烘/洗碗；按原用水人/出行人关联热水/EV；空调只关联原日历中的房间实际使用者。登记家庭决策人另存，不能当作每台设备的实际使用者。

常驻自动动作仍须满足原明确预授权和原动作边界。新增成员分歧只触发“需相关意见/确认”的实验门控，不自动扩充权限，不修改原权限文件，也不生成真实受访者已同意的声明。儿童偏好是需要被协调的需求，不授予新设备操作权。未声明储水设温或制热范围继续逐案确认。A的自行使用不因新增偏好而被等同于未经授权的外部控制。

## 已实现与仍待验证

这是确定性的分层继承、条件匹配和逐设备成员作用范围编译器，并没有实现一个新的人口统计估计器或通用CSP求解器。可用约束满足理论说明一致性问题的建模方式，但不能写成已经复现某篇优化算法。

Fanitabasi与Pournaras（2020），[Appliance-Level Flexible Scheduling for Socio-Technical Smart Grid Optimization](https://eprints.whiterose.ac.uk/id/eprint/165733/)，支持分别建模设备特点、自主提供的柔性、舒适及使用偏好；不支持本项目具体的成员分配规律。本次只核对其机构库摘要。

[NIST IR 7878](https://www.nist.gov/publications/combinatorial-coverage-measurement)支持度量已给定样本的组合覆盖。当前两户核对不等于已完成总体覆盖测量，更不代表现实人群覆盖。

本次报告区分：设备及来源守恒；原A静态逻辑；B的生活冲突/服务风险/待确认事项；新增画像自身的设定来源。B的冲突继续保留，不根据成功、节能或是否符合新增偏好筛选。两户测试不是画像心理有效性或benchmark有效性的实证证明。

## 复现

```sh
python -B -m unittest benchmark.family_generation.test_household_preferences \
  benchmark.family_generation.test_device_persona benchmark.family_generation.test_energy_portrait \
  benchmark.family_generation.test_persona_conditions benchmark.family_generation.test_persona_checks \
  benchmark.family_generation.test_generation benchmark.family_generation.test_connection
python -B -m benchmark.family_generation.validate_household_preferences \
  --artifacts /path/to/reference50-selection-v4-20261020 \
  --before /path/to/preserved-v3/profiles --out /path/to/new-pair-check
python -B -m benchmark.family_generation verify /path/to/new-pair-check
```

接口测试的住房几何依赖Shapely，不会执行EnergyPlus。独立校验脚本对输入摘要进行前后核对，所有既有A/B、日程和封存结果文件只读；输出包含补前、补后阅读版、逐字段对照、20组检查及来源/方法摘要。
