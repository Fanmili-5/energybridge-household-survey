# V28复现与验收顺序

当前V28全1000户参考验收和50/950正式采集包见[当前方法](../research/collection-adjustment-20260930/household1000/formal50_950_production_v28_20261014/METHODS_AND_ACCEPTANCE.md)。需要获准使用的前置人口/联合调查/住房/EB与天气输入；公开clone没有这些私有输入，不会自动下载或运行EP。


V28入口顺序：`bootstrap.py` → `repair_chronology.py`/`adapt_full_cluster.py`/范围适配 → `produce_static.py` → `prepare_sensitivity.py` → `weather_qc.py` → `repair_external_bindings.py` → `execute_physics.py`。已有目录不得覆盖历史证据，恢复运行依赖实际内容门与当前报告；不要把辅助旧V27模块的独立CLI当作V28入口。

物理完成后，`deploy/formal_questionnaires_20261014/render_materials.py`按50/950分别导出成熟前端资料；Node的`bind_frontend.js`/`verify_case_bindings.js`固定实际JS数值/哈希语义；`build_release.py`构建独立正式包，`release_acceptance.py`逐条核对实际世界/A-B/回读证据，`test_protocol.py`仅在虚构测试库检查协议。`activate.py`验证包、备份旧数据、分户邀请码并激活正式服务，后续备份由`backup.py`完成。

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
