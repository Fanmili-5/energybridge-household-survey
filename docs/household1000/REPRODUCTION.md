# 50户正式问卷；950户暂停

50户500组新版任务已上线：[正式入口](https://47.85.194.154/household50)。修复热水目标控温漏项、同热区空调控制绑定，并要求具体服务、人工安排或模拟后果差异；500组同显示后果为0。B可以不方便、不能完成服务或明显不合理；接受/拒绝由演员填写，不自动生成标签。家庭、正常A、硬件及原10个日期保持不变。

沿用原成熟前端，保留影响、简略动作及填写者本人年龄/性别。原50已在学校完成500正式+200敏感性、控制SQL与500页真实浏览器及提交全流程验收。学校离线前封存包已复制：本地再次校验501文件、500组页面与实际JS绑定，并在问卷服务器以隔离假参与者库复核提交/修订/恢复/撤回，正式库写入0。50入口已核实际HTTPS版本；邀请码与所有数据库行保持不变。

证据边界：学校最终验收SHA已从成功工具输出记录，原始JSON收据留在离线学校盘上，尚未复制。公开OBSERVED文件是执行观察摘要，不能冒充原件；本地封存包复核也不冒充重新仿真或浏览器测试。

950户源规则、物理、实质后果和控制SQL通过曾被观察到，但正式包最终验收结果未取回。按用户要求暂停，入口返回503；旧包/邀请码/记录保留，未发布950新版，也未重新跑1000户全量EP。恢复后先核远端任务状态与证据，再决定后续。

这支持条件参考任务生产与50户采集，不证明真人可辨性/角色有效性、全国六类自然偏好比例或实测住宅设备校准。全部主观答案仍待真人采集，训练与最终科学benchmark未准入。

源码及方法：[V30.3](../research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015/METHODS_AND_ACCEPTANCE.md)。[学校执行观察](../research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015/SCHOOL_50_ACCEPTANCE_OBSERVED.json)、[封存包复核](../research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015/SEALED50_LOCAL_REVIEW.json)、[上线收据](../research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015/ACTIVATION_RECEIPT50_V30.json)。旧V29的任务充分性验收已[撤回](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/ACCEPTANCE_WITHDRAWN.json)。

以下为历史源链/方法/证据边界；旧版本的当前完成状态不替代上述50限定发布。

# V29当前入口与冻结顺序

当前阶段 `contrast_repair_v29_20261015`，方法见[V29修正与验收](../research/collection-adjustment-20260930/household1000/contrast_repair_v29_20261015/METHODS_AND_ACCEPTANCE.md)。V28世界、家庭、需求、正常A、硬件、日期与角色政策为冻结父版本；V29修正B请求和显示语义。只复用精确相同物理输入的SQL，所有读回重新绑定。

受控学校顺序：`bootstrap_v29.py` → 全10000组只读候选预检 → `contrast_controls.py` → `repair_contrast.py --scope formal50` → `compile_repaired.py --scope formal50` → `execute_physics.py --scope original50` → 材料/绑定/正式包/全案例/API/500页实际浏览器 → `final_contrast.py --batch formal50`。完整原50证据通过后才能以同规则处理formal950、other950及weather_sensitivity；再核9500源案例、1000页浏览器、六类覆盖及最终合并，最后发布。

材料与接口使用原成熟前端和 `deploy/formal_questionnaires_20261014/`。实际浏览器由 `deploy/contrast_validation_20261015/browser_fixture.py` 在学校以独立虚构身份验收；`complete_review.py`连接全部当前物理/正式材料/角色覆盖收据。命令不会替参与者生成真人答案。旧静态/生成辅助模块不能直接覆盖新阶段，现有目录与历史失败均保留。

`household1000.py require-generation` 是只读验证，当前输入/代码变化即拒绝旧收据，不自动启动EP。公开clone缺少许可原件和逐户完整输入；学校准备好的工作区才能核完整证据。G6真人与实测限制见[研究门](RESEARCH_GATES.md)。

下面是历史V28及更早版本的源链和复现说明，其当前状态或启动顺序不能替代上述V29入口。

# V28复现与验收顺序

当前V28全1000户参考验收和50/950正式采集包见[当前方法](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/METHODS_AND_ACCEPTANCE.md)。需要获准使用的前置人口/联合调查/住房/EB与天气输入；公开clone没有这些私有输入，不会自动下载或运行EP。


V28入口顺序：`bootstrap.py` → `repair_chronology.py`/`adapt_full_cluster.py`/范围适配 → `produce_static.py` → `prepare_sensitivity.py` → `weather_qc.py` → `repair_external_bindings.py` → `execute_physics.py`。已有目录不得覆盖历史证据，恢复运行依赖实际内容门与当前报告；不要把辅助旧V27模块的独立CLI当作V28入口。

物理完成后，`deploy/formal_questionnaires_20261014/render_materials.py`按50/950分别导出成熟前端资料；Node的`bind_frontend.js`/`verify_case_bindings.js`固定实际JS数值/哈希语义；`build_release.py`构建独立正式包，`release_acceptance.py`逐条核对实际世界/A-B/回读证据，`test_protocol.py`仅在虚构测试库检查协议。`activate.py`验证包、备份旧数据、分户邀请码并激活正式服务，后续备份由`backup.py`完成。

2026-10-15强化准入：`release_acceptance.py --node /path/to/node20`核当前内容门、物理报告签名与完整集合、逐项源数值，并重新构造全部源案例；派生绑定通过实际发布JS单独核。`test_release_acceptance.py`及`test_recovery.py`在受控/临时输入下检查拒收和故障恢复。公开状态与载荷可只读运行`python3 scripts/verify_household1000_publication.py`；它不启动EP、不替代人类有效性验证。

`python3 scripts/household1000.py require-generation --scope full1000EP`在公开clone返回2（缺受控当前输入）；在正确学校工作区验证原50、950、气象敏感性三组实际内容绑定回执，仍不启动EP。任何当前输入或模型改变都须重新审核，不凭JSON状态字段准入。

下面V23命令与门策略是历史复现说明，不能替代上述V28当前入口。

## 公开checkout

`scripts/household1000.py status/stages/check-source/doctor`只读，核公开版本、实际源码字节与受控输入可用性。缺失私有输入时如实报告；源码hash通过不等于物理、人类或全国代表性验证。

## 已准备合法输入的学校工作区

```bash
python3 scripts/household1000.py doctor --workspace /path/to/prepared/energybridge-household-survey
python3 scripts/household1000.py check-bindings --workspace /path/to/prepared/energybridge-household-survey --scope pilot50
python3 scripts/household1000.py check-bindings --workspace /path/to/prepared/energybridge-household-survey --scope static1000
```

入口从STATUS的 `active_stage` 读取V23。生成、校验、编译和物理回读在学校Linux执行；历史阶段不覆盖。受控阶段依赖见 [INPUTS.md](INPUTS.md) 与 [PIPELINE.json](PIPELINE.json)。源版本/data schema仍为V22，当前验收为V23。

在受控V23目录中，依次执行并保留失败：

1. `prepare_revision.py`：仅在新目录准备原50集合、外部输入锁、设计不变性与历史来源，不重抽家庭/日期/A/B。
2. `acceptance_controls.py`：隔离副本中测试实际内容变动、缺/重复/错配结果、A硬边界拒收和B保留；不启动EP。
3. 全量静态/输入/日程/模型/材料审核；`scientific_review.py`核证据、目的、当前反例代码hash和实际输入签名。发现关键问题拒绝原50执行。
4. 原50的500对基线、200对前史/入水敏感性、50对空调模型形式诊断形成固定期望清单。原50及日期不可替换。`reuse_physical_results.py`逐一核精确物理身份和SQL，或在许可的原50范围内重跑改变过的输入。
5. `physics.py readback --scope all`、`--scope sensitivity`，以及 `model_form_diagnostic.py readback`按当前账本验收，不以已有结果的交集定义成功。weather-only诊断单列，不是家庭仿真。
6. `materials.py`、材料与500案例绑定/时轴审核、真实浏览器输出隔离检查；沿用原问卷，不产生真人标签。材料变更后重签当前输入并检查结果身份。
7. `final_acceptance.py`将当前物理/材料证据、目标复核、失败保留、输出hash与DELIVERY闭合。只有通过的限定范围可标验收。

实际原50运行输出留在学校，公开汇总写明旧SQL复用与新引擎调用数量。`ep_gate.py`只接受 `original50`；全量1000执行被拒绝。任何输入、代码、模型或材料变更必须重新签名/验收；批次前后核完整实际内容，逐作业核实际关联输入。

## 前端与后续反馈

去案例模板的六段JSON为空，需要当前同版本角色/任务/物理后果填充。原前端二元采用、四评分、理由保持。`FRONTEND_BROWSER_REVIEW`记录工程检查，真人身份、理解、角色信息效应、反馈预算和独立分组评测仍见 [RESEARCH_GATES.md](RESEARCH_GATES.md)。不将工程记录重命名为真人答案。

本发布的校验范围见PUBLICATION_CHECK与RELEASE_MANIFEST。历史硬路径和获准输入依赖如实保留；移植时需在新阶段配置并重核路径/hash，不声称任意机器clone即可生成完整数据集。
