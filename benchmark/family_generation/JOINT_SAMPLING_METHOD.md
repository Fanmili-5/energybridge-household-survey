# 六类固定、类内联合随机 v1（本地候选）

历史方法记录：本轮候选已修订为[家庭画像v2](HOUSEHOLD_PORTRAIT_V2_METHOD.md)。下文保留v1的原公式、时间并集规则及历史验证，不推荐在新候选中使用。v2只验收家庭画像，不代表A/B接口已完成。

这是原家庭生成器的显式可选模式`within_class_joint_v1`。原pipeline不变：家庭与设备→住房→生活/A→机会→B→后果→问卷。旧配置不启用采样，旧画像、A/B、仿真和线上数据不迁移。已有50户只做独立候选画像及冲突审计。新偏好不作为B准入条件，不生成接受/拒绝标签。

## 成熟算法与项目设定

采用高斯Copula变换：`Z ~ N(0,R), U=Phi(Z), X_j=F_j^-1(U_j)`。数值原语来自NumPy PCG64与SciPy `ndtr`。家庭共同倾向和成员/设备差异用标准共享因子构造：`Z_hj=lambda H_h+sqrt(1-lambda^2)epsilon_hj`。同一维度、相同载荷、独立残差下，两个潜变量的相关系数为`lambda^2`。离散化和可行域映射后的字段相关性不等于这个值。

[Ghosh与Henderson论文第1节](https://people.orie.cornell.edu/shane/pubs/ChessboardOR.pdf)给出NORTA变换及局限；[作者算法说明](https://people.orie.cornell.edu/shane/NORTASoftware.html)说明其与高斯Copula的关系。本实现不求解任意输出相关矩阵，不实现Chessboard算法，也不宣称发明新的随机算法。[设备级柔性研究](https://eprints.whiterose.ac.uk/id/eprint/165733/)支持区分设备物理特点、偏好和舒适要求，不支持本项目的具体参数。

| 字段 | 来源与作用 |
| --- | --- |
| 六类核心 | EB角色的项目操作化；家庭类别固定，成员只做类内差异，不按工作日历另配A—F |
| 六个语义维度 | 时间取向、节奏稳定性、操作负担、温度水平、舒适敏感、自主控制；潜在均匀边际及因子结构是实验设定，不是心理量表 |
| 载荷0.7 | 未拟合的实验起点，预先检查0、0.35、0.7、0.9；不按讨喜或成功结果选参数 |
| 制冷偏好 | EB该类软参考范围内按0.1℃网格作分位映射；范围来自EB，均匀分布及粒度是实验设定；不是制热或停机权限 |
| 移时意愿 | `(1-节奏稳定性)*(1-操作负担敏感度)`映射到已有移时边界并取10分钟粒度；是实验映射，不是硬许可或接受概率；没有原边界则留空 |
| 授权偏好 | A/B/C/E保留逐案、当天或建议确认；D/F可偏好在原许可内仍先确认；0.5阈值是实验设定，不产生新权限 |
| 热水、EV、烘干取舍 | 备水与少运行、早备足与允许推迟、等待敏感度均为实验角色设定，不能声称从职业、年龄或日程估计了心理 |

完整字段范围、因子用途和实验参数在[规则表](JOINT_SAMPLING_RULES.json)；原始文献及实际核读范围在[来源表](JOINT_SAMPLING_EVIDENCE.json)。相关字段共同使用相应倾向，避免独立拼档位。温度水平有独立因子，不因喜欢早洗衣而自动偏好更低温度。成员意见不被平均成已经同意，未成年人不因此获得操作权。

## 时间、服务链与缺失处理

既有两户只读取事前释放/期限、完整程序、机器窗口、人员资格和原日历。10分钟网格上保留可完成装入→完整运行→取出的局部候选。跨午夜时间保留日偏移，缺少次日日历不假设有人可操作。原登记操作人优先；未指定时只可使用唯一合格人员，不能把多名合格者随意当替代者。

同一稳定分位数映射各日期；工作日/周末偏好是各自可行时钟网格并集上的目标，逐日期目标也保留。它不保证每天都能实现，也不保证全屋资源可行。没有窗口或证据则保留空值和原因，`retry_count=0`，不换种子重抽。这是项目定义的约束映射，不冒称对任意联合分布做了精确条件采样。

一体机洗烘共享设备偏好与原批次链，完整链必须适合原窗口；烘干时刻由洗衣目标加原时长导出。分体烘干不另抽时刻，只从上游目标和原10分钟装取规则导出请求目标；真实转移与资源仍由原调度器处理，缺少可衔接目标则留空。

新家庭只有程序/日历时，先计算潜在服务偏好；到家与餐后释放复用原生活编译规则。是否真的产生衣物批次仍由原库存/需求模块决定，不捏造任务凑偏好。

## 接口、冻结和实际作用

原批次配置显式添加：

```json
"preference_sampling": {"mode": "within_class_joint_v1", "loading": 0.7}
```

种子复用批次`seed`。独立画像上下文在`energy_preferences.preference_sampling`记录同一`mode/seed/loading`。随机流由版本、种子、家庭ID、成员/设备ID和语义维度稳定区分，不受列表顺序影响。

原`energy_use_profile`增加`joint_sampling`和设备`sampled_preferences`，保留旧字段。保存输入、规则、代码及画像哈希、运行库版本、分布与来源账本。十天使用同一`profile_sha256`；住房/生活编译后复用冻结画像，不从A或后果重抽。

| 原入口 | 生效范围 | 不变项 |
| --- | --- | --- |
| `program_policies.preferred_start_min` | 洗衣、洗碗及可衔接烘干的软目标 | 数量、程序、期限、窗口、装取上限、人员资格与日历 |
| `thermostat_policies.cooling_setpoint_C` | 新批次制冷偏好 | 制热、40℃停冷哨兵、运行模式与用房；死区冲突不应用并记录原因 |
| 画像/评价上下文 | 软移时意愿、成员意见、热水/EV偏好与更保守的确认偏好 | 不声称已改变热水/EV的A，不变成B准入筛选 |

新批次保存`PREFERENCE_APPLICATION.json`，逐字段记录旧值、新值或不应用原因。原调度器可以偏离软偏好，仍须遵守硬约束。既有50户不调用该适配器重写题目。

## 复现与验收

```bash
python -m pip install -r benchmark/family_generation/requirements.txt
python -B -m benchmark.family_generation generate \
  --input benchmark/family_generation/examples/batch_joint.json --out /tmp/family-joint
# 公开小情境的原住房/生活调度连接，不运行EP：
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.family_generation connect \
  --families /tmp/family-joint --out /tmp/family-joint-connected
python -B -m unittest benchmark.family_generation.test_joint_sampling -v
```

两户输入先由原`validate_household_preferences`对封存源投影并核验，再运行：

```bash
python -B -m benchmark.family_generation.validate_joint_sampling \
  --source-pair /path/to/verified-source-pair \
  --artifacts /path/to/reference50-selection-v4-20261020 \
  --out /path/to/new-joint-validation
```

固定0696/0756、种子0—7和四种载荷，保存全部64个候选；种子0只作预先声明的展示例。原公开文件含7个小样例，覆盖六类，全部保留并生成56份画像，不丢掉第二个A类。检查原20组A/B的工程、生活、服务风险、软偏好和待确认事项，不剔除样本。

数学验收比较标准正态CDF的独立实现与潜在相关性，只测试随机向量，不生产更多家庭或运行物理仿真。公开六种新情境用相同ID/种子对照旧路径，检查事实/硬件/原生活输入一致，A需求确实读取新目标，A后不重抽画像。

本轮支持生成一致性、可复现性和类内变化，不支持真实人口代表性或真人行为有效性。后者仍需“仅六类/共享习惯/完整偏好”的受访者对照实验，训练测试按家庭及来源情境隔离。
