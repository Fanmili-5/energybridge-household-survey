# 完整项目：三条生成主线与问卷交付

项目要产出的是：**有来源的家庭情境、生活方案A、围绕VPP的调整方案B、同版本的参考后果，以及参与者站在该家庭立场给出的评分、接受判断和原因。** 节电、VPP达标和服务完成都是案例信息，不能自动成为人的答案。

三条主线有明确的实现和接口，但模块实现、某批数据通过、真人效度及最终benchmark成绩是不同结论。本页解释完整路径；专项修复/补生成已由PR #24合入main；线上激活仍须另外核验。实际采集版本以[当前资料指针](household1000/CURRENT_QUESTIONNAIRE50.json)、其对应发布清单及激活凭据共同核对。准备完成不代表已经上线。

## 1. 三条线怎样组成一个项目

先固定家庭、角色及权限契约；住房装配和生活生成共同使用该契约。住房提供空间、设备和资源条件，生活安排生成服务需求及A。冻结A后提出B，再把同一家庭、住房、需求和A/B交给配对仿真；最后把资料投影到既定问卷，并单独采集人的判断。

`家庭契约 → 住房/设备与生活日历 → 服务需求 → 冻结A → B候选 → 十天选题 → 同世界A/B仿真 → UI91资料 → 独立人类评价`

住房需要在生成A前提供资源条件，又在选定B后执行仿真。因此三条线存在前后交接，不能把住房只当作最后添加的一张图。

### 第一条：家庭与设备生成

- **输入**：完整联合家庭参考记录或声明的合成情境，成员关系、住房条件、生活输入，以及设备使用权和操作权限。
- **依据**：[六类方法与外部问卷证据](../benchmark/household_archetypes/README.md)、[家庭来源登记](../benchmark/family_generation/SOURCES.json)。EB六类是预定义实验条件；外部调查支持相关维度及部分组合，不证明总体六类份额。
- **规则**：整体抽取家庭记录，保持成员、年龄和关系一致；显式装配共享住户、床位、设备与权限，再连接住房和生活A。实现见[core.py](../benchmark/family_generation/core.py)与[connect.py](../benchmark/family_generation/connect.py)。
- **人为设定**：角色配额、合成情境、设备覆盖及支持契约。拟议EB配额、当前既有50户构成和公开六户示例分别登记，不能相互替代。
- **验证**：[结构、失败分母、字节复现及住房/生活A连接](../benchmark/family_generation/VALIDATION.json)。这些不等于人口代表性或真实家庭偏好验证。
- **复现**：[公开输入和命令](../benchmark/family_generation/README.md#公开复现)。六条公开情境适合验证实现；复制到1000条不会增加情境多样性，正式扩展仍需要足够丰富且获授权的联合输入。

### 第二条：生活安排、A与不同取舍的B

- **输入**：同户生活日历、设备能力、操作/空间资源、服务需求和截止时间；先生成并冻结完整A，再给定VPP。正式十天方法固定18:00—19:00。
- **依据**：[生活到A方法](../benchmark/ab_generation/docs/life/LIFE_METHOD.md)、[十天采集方法](../benchmark/ab_generation/docs/collection/COLLECTION_METHOD.md)、[来源](../benchmark/ab_generation/SOURCES.json)。设备排程的先后/独占约束、温控状态与热动态、覆盖饱和和冗余惩罚分别有方法依据；论文不提供本项目全部数值或题量配比。
- **规则**：程序设备保留任务、程序、负载和时长，改变机器或装取安排；EV保留原连接和出行；空调/热水改变声明域内的控制请求。联合B每台改变的设备必须是事件根或有具体支持见证。候选先满足基本语义，再以归一化覆盖和重复软惩罚分配每户十题，不按收益最优或成功筛选。实现见[候选构造](../benchmark/ab_generation/collection_candidates.py)、[准入](../benchmark/ab_generation/collection_admission.py)、[关联见证](../benchmark/ab_generation/collection_relevance.py)、[选题概念](../benchmark/ab_generation/collection_selection.py)和[分配](../benchmark/ab_generation/collection_assignment.py)。
- **人为设定**：10分钟网格、温差/时长档位、搜索预算、覆盖权重和去重阈值，见[参数登记](../benchmark/ab_generation/COLLECTION_PARAMETERS.json)。不设成功、冲突、设备或对照的固定题量配比；小中大按各设备的实际单位分轴报告，不给整个B伪造总幅度。
- **验证**：[计划与覆盖验收](../benchmark/ab_generation/docs/collection/COLLECTION_VALIDATION.md)和相关反例测试；实际批次另外绑定自己的完整A/B、选题、覆盖及缺额。完整未来A是[离线反事实条件](../benchmark/ab_generation/docs/core/OFFLINE_EXPERIMENT.md)，不声称实时预测或预知人的答案。
- **复现**：新十天入口为`benchmark.ab_generation.collection`；既有50户A侧导入为[reference_collection.py](../benchmark/ab_generation/reference_collection.py)。[旧长尾复现](../benchmark/ab_generation/docs/core/REPRODUCE.md)保留历史方法身份，不能把旧十层配额当作当前选题规则。单一家庭没有某种机会时如实缺额，不能改A或硬加事件外动作。

### 第三条：住房、设备执行与配对仿真

- **输入**：家庭契约、参考住房/材料与登记天气、同户设备、固定A/B、服务需求及共同初始化条件。
- **依据**：[构造方法](../benchmark/housing_simulation/METHOD.md)、[逐阶段证据矩阵](../benchmark/housing_simulation/EVIDENCE.md)、[来源](../benchmark/housing_simulation/SOURCES.json)。区分住宅原型资料、EnergyPlus机制、采用的参考值与项目模型假设。
- **规则**：匹配/构造参考外壳、联合安装和权限绑定，编译两臂模型，执行并回读SQL，审查数值、计量、服务、事件与恢复。见[模块命令及实现](../benchmark/housing_simulation/README.md#接口与实现)。同房多空调按每台设备的控制门分别执行；不得删设备来掩盖兼容问题。
- **人为设定**：几何、安装网格、参考材料/换气、前史/尾期及数值容差，见[假设登记](../benchmark/housing_simulation/ASSUMPTIONS.json)和[设计决策](../benchmark/housing_simulation/DESIGN_DECISIONS.md)。实际批次的天气、引擎及模型修复必须有独立版本证据。
- **验证**：[非空公开配对验证](../benchmark/housing_simulation/VALIDATION.json)、[敏感性与收敛结果](../benchmark/housing_simulation/ROBUSTNESS_RESULTS.json)及具体发布的配对审计。模型估算不是实测室温、实测账单或住宅安装认证。
- **复现**：[完整物理复现](../benchmark/housing_simulation/REPRODUCE.md)需固定依赖、EnergyPlus和登记资源。公开美国TMY3示例验证接口，不代替中国正式批次天气或逐户校准。完整实验在研究计算环境执行，不因文档修改重跑。

## 2. 接口怎样保证没有串户、串计划或串结果

| 交接 | 必须保持的身份与内容 | 对应实现/证据 |
|---|---|---|
| 家庭→住房/生活 | 同一成员、关系、资产、使用权、操作权与来源摘要 | [家庭连接](../benchmark/family_generation/connect.py) |
| 生活→A | 完整需求、库存/服务链、人员和资源窗口；先生成A再接入本次VPP | [生活规则](../benchmark/ab_generation/LIFE_RULES.json) |
| A→B与十天选题 | A命令摘要、设备参数、需求、授权与事件；B补丁、逐设备理由、候选和未选原因 | [采集方法](../benchmark/ab_generation/docs/collection/COLLECTION_METHOD.md) |
| 选题→物理 | 同一冻结A/B及需求、住房、天气、初态、引擎与逐臂模型身份 | [物理导出](../benchmark/project/reference_collection_physics.py)、[修复与补生成](../benchmark/project/PHYSICS_REPAIR_PRODUCTION.md) |
| 物理→UI91 | 配对结果与A/B摘要绑定；控制设定、实际模型后果、VPP目标及人的判断分开 | [物理资料适配](../benchmark/project/reference_physical_release.py) |
| UI91→答卷 | 发布、案例、参与者实际可见资料、回答修订及同意/撤回状态 | [采集协议](COLLECTION.md)、[采集器](../benchmark/collector/README.md) |

页面不重新选B，也不把参考画像或客观目标推导为评分。系统每轮分配一户十题，同一参与者可在完成后自愿开始另一户，参与者身份跨轮保持；不是让参与者自由挑户，也不能把多轮当成不同自然人。UI91是资料呈现版本；沿用的v69量表/回答协议有自己的版本身份，两者可以同时登记。

## 3. 三种已有路径要分开使用

| 路径 | 实际用途 | 不能据此宣称 |
|---|---|---|
| 公开六户37案`benchmark.project build` | 家庭→住房→生活A→旧目录取样→v69只读资料的接口示例；事件为18:10—19:10，原无效样本和A=B保持 | 它不是新版18—19、每户十天的正式500题；后果未计算，旧工程错误不得直接准入正式采集 |
| 公开新十天`benchmark.ab_generation.collection` | 在已固定A上验证新版机会、关联、准入、覆盖和去重；不运行引擎 | 六户试点不证明50+950户已完成，也不证明全部交互/物理或真人有效性 |
| 既有50户正式资料 | 导入原家庭与A，再生成新B、做同版配对仿真并派生UI91；发布及工程补生成另有清单 | 原50户没有按新家庭生成入口重造；旧B后果和旧答卷不能挪用 |

历史A46/B57的1000户/10000案另作归档，不是新版B的全量生产结果。新方法950户与1000户仿真继续暂缓。当前不存在已经证明可从六条公开情境一键重建正式50+950户全部数据的结论。

## 4. 失败与准入的四个层次

| 情况 | 处理 | 是否可据此推定人的答案 |
|---|---|---|
| 明显工程逻辑错误：先运行后装载、改过去、未授权、身份错位 | 保存请求、错误原因与分母，隔离为工程诊断；修规则形成新版本 | 否，也不作为正常正式题凑覆盖 |
| 可表达但不方便/服务冲突：赶不上方便窗口、等待过长、名义补能不足等 | 保留原B与约束原因；不自动修成成功方案 | 否，参与者仍须按家庭立场评价 |
| 有可用模型结果但没帮助、费用增加、服务失败或VPP未达标 | 保留结果、原方案及失败维度 | 否，客观结果与接受标签独立 |
| 天气/数值/输入完整性使后果不可计算 | 保留失败，先修底层；正式后果版执行零未知门槛。确需补生成时按事前顺序、原因和谱系另记，不能按节电或达标择优 | 否，不得填0或伪造后果 |

离线提案示例可以明确保留`not_computed/null`；正式要求完整后果的发布必须达到对应门槛。工程补生成是可追踪的样本选择条件，后续分析要披露，不能声称完全无条件的随机样本。

## 5. 从公开仓库开始核验

下列检查不运行EnergyPlus、不生成真人标签，也不连接生产数据库：

```bash
python -B benchmark/verify_publication.py
python -B -m benchmark.family_generation.verify_package
python -B benchmark/household_archetypes/verify.py
python -B -m benchmark.housing_simulation.verify_package
python -B -m benchmark.project.verify_package
python -B -m benchmark.project verify-questionnaire benchmark/project/examples/questionnaire
node benchmark/project/verify_display.js benchmark/project/examples/questionnaire
```

实际生成公开家庭并连接住房/生活A，可按[家庭公开命令](../benchmark/family_generation/README.md#公开复现)安装依赖，输出到新目录。新版十天的生成、回放和敏感性命令见[采集方法第6节](../benchmark/ab_generation/docs/collection/COLLECTION_METHOD.md#6-验证与复现)，不要误用旧37案示例代替。物理运行是另外的显式步骤。

公开源码、规则、合成示例和聚合验证可核验；受许可限制的原调查、逐户完整包、住宅/天气原件、完整SQL及真人记录不随Git发布。原正式数据重建需要相应授权输入，见[来源与许可](../THIRD_PARTY.md)。哈希只能证明身份对应，不能单独证明参数有经验依据。

## 6. 现在可以做出的结论与剩余工作

三条线都有代码、方法、来源/设定登记、阶段产物和验证入口，已经构成可解释的研究生产项目。具体50户版本的计算及上线状态须按自己的清单核验，不能由某个模块测试通过推定。

仍需独立完成：正式采集中的题意理解与标签质控；冻结按家庭/共享来源分组的训练验证测试清单、模型可见信息和指标；用有效人类评价验证roleplay模型。人口代表性、实际住宅校准和所有可能设备组合的穷尽覆盖均不是当前已证实结论。见[评测边界](EVALUATION.md)与[数据与验收](DATASET.md)。

正式采集的数据库位置、JSONL导出、请求体边界和备份见[存储与维护说明](household1000/COLLECTION_STORAGE_AND_OPERATIONS.md)。后续维护已按当前要求清理退役采集记录及其备份；冻结源计划和工程失败谱系保留，历史上线时的保留策略不代表当前采集记录策略。
