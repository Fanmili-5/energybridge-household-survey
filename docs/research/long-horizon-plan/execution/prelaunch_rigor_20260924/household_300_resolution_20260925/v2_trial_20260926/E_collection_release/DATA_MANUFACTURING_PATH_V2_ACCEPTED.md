# V2 隔离工程角色包制造路径（2026-09-26）

本包只用于固定合成角色的工程核对。无真人问卷回答、偏好反馈、人口权重、实测住户电费或正式采集放行。公开发布与线上接入未批准。

1. A v2 家庭结构 `A_structure/family_300_v2.json` SHA `1e880b8573124cd2b1050c55e41efc803d3a08d384950f2137cc748abb66870d`：300 个合成角色，H6/H7 口径和家庭成员设计。
2. B 经 C 绑定和 REVIEW_023 控制边界后的 `B_profile/profile_300_v2_c_control1.json` SHA `aab74ca47d480bc93ddd5d7243020044d439b9408a9f4ed8af0092159fc26334`、`behavior_300_v2_c_control1.json` SHA `5f9feaf70c8e2fcad2775d92667fc7dca226c2c7495ac146ce49644884eceafc`：原合成持有设备与 EB 本轮纳入设备分列；经济、习惯和态度仍为情境。
3. C `C_idf/building_300.json` SHA `bb063fb494fd5d1ca8faaeafafab1444fe9f1fe6cd54b09ee5657e19dc957c0d`：设计几何、住宅原型与天气代理，不是本户物理校准。
4. D `D_integration/behavior_input_manifest.json` SHA `c8bcb9415e0d03f490fa577bc3da5a8955458a679f50945c6192f11b56984c25`、`runtime_300.json` SHA `300485bb6604124fb0e28646c001a0319747ccc4e318619730a20faa282c181a`：本轮设备注入、274 个实际受控空调区和 300 户各 10 天基线运行。
5. G `G_casebank/candidate_input_manifest_300.json` SHA `6b73e0ce5fd040908a6d5775a2363a0709c1915bd806058761ab3b6cb227ba9e`、`candidate_runtime_300.json` SHA `5fb4102e3e5017c7b6b5d908de0e99ac4e3a28261deff9d70d3018af29560ae8`：同源起点的固定候选策略。A 写出的逐日 pending 案例/对比/展示文件 SHA 分别为 `a614a26887ea43f6c15de4c8790ba15a20317efd2c88b4953dc6c6cd0113ffb4`、`c9ac7035281bac788abc9b6ad11a1bbb8d17e870ae8c934b779f75d30ea518e7`、`bcdd74a19e0ecf9956cda93134ba301325d1acdc86aeff54b7c08b2db306455b`。这些原始 pending 字节未修改。
6. F `F_independent_review/v2_trial_g_payloads_300_readback.json` SHA `906dade754b1c5208303e3907d6a6f7233b5ca1b9e97a9a0cce951bc51a7d249` 独立核对 300 户、3,000 天、6,000 分支日，失败 0。`V2_E_RELEASE_GATE.json` SHA `b0923ced35a9fdaab377b2afffab02a73bed739bd0b923c35734dc50d29f1e65` 绑定这批实际字节，只放行隔离工程导出。
7. E `prepare_v2_exports.py --build` 对六个静态/输入 SHA、D/G 运行角色与日期、66 题适用/多值、设备拥有与控制数量、C 候选和 D 实际空调区做只读检查后生成九张 CSV。`PACKAGE_MANIFEST.json` SHA `baf8e16390b471e76776550883b519c241f25be0037aac34d964145f0de2fa73`；七张公开候选表的 `PUBLIC_MANIFEST.json` SHA `4387f3759068b42fea3c94789be21ff3f3a4fbd90732472057ae14b26ebd71e3`。所有 CSV 逐格读回；F 对 E 实物的独立读回 SHA `74afafe87fb8cc4036f61ad0698d402b077f7fe7cb3daef9871b277d41015eb7`，失败 0。
8. `promote_v2_g.py --promote` 只从 F 已审的 v2 pending 三件生成隔离工程案例投影：`G_casebank/accepted_public/casebank.json` SHA `74dc0997dfbd78d778b38ccb44c1816e2a8320db46e8b33cad338f5423adb7a1`、`accepted_contrasts.json` SHA `71df472107dbcdc7efe5447a137543067218feb55f376b969c9982893dd86e99`、`display_payloads.json` SHA `c17cf93a1d86176be8f17616a95563efd3a4b7ccc2d88d44e5cc454ed9bf7a17`。后者仅去掉 G pending 展示对象的 F 审计附加字段，A/B 计划可见内容及其哈希不变；`validate_v2_role_payload.py` 对 300 家庭卡和 3,000 天的角色、天气站、A/B 哈希、私有路径及现有离线契约读回通过。该接受状态仅表示模拟案例可做隔离工程预览；2,253 个有意义比较日不构成真人可采集批准。

九表逐表行数与 SHA 以 `PACKAGE_MANIFEST.json` 为准；字段含义见 `DATA_DICTIONARY_V2_E.md`。G accepted 三件已通过 F 独立实物读回；这只支持隔离工程预览。旧 v1 E/G 链、原问卷、线上服务和会话数据均未修改。

补充逐题来源核对：`audit_v2_question_mapping.py` 从所选 B control1 的 300×66 条 `basis` 重新生成 `QUESTION_MAPPING_66_V2.json`，SHA `cec28641d9952afbd9ac6319899bcc87737e8603b6a90620d72e070375a39a05`。它保留父映射中的构念参考，但以 v2 生成规则和当前实际 basis 替代七题过期说明；每题 300 个状态计数，66/66 题有来源或显式实验规则。该映射不回写旧 B，也不改变已审仿真数值。

## 公开说明所需的来源引用

- 建筑原型来源：[DeST 典型建筑库](https://www.dest.net.cn/dxjzk)要求引用 An J, Wu Y, Gui C, et al. (2023), “Chinese prototype building models for simulating the energy performance of the nationwide building stock,” *Building Simulation* 16:1559–1582, [DOI:10.1007/s12273-023-1058-5](https://doi.org/10.1007/s12273-023-1058-5)。此引用不表示源模型或转换后的 IDF 可随本包再分发。
- 天气来源：[Climate.OneBuilding 的网站引用说明](https://climate.onebuilding.org/about/)列为 Lawrie, Linda K. and Drury B. Crawley (2026), “Development of Global Typical Meteorological Years (TMYx),” Climate.OneBuilding.org（网站注明论文仍在准备中）。网站引用不等于 CSWD 天气文件的再分发许可；本包不附天气文件。
- 统计数据来源：如引用国家统计局网站内容，应按其[服务条款](https://www.stats.gov.cn/wzgl/202302/t20230217_1912857.html)在显著位置注明“引自国家统计局网站”并标明 `www.stats.gov.cn`；具体所用统计指标仍须在相应报告中逐项标注。
- CHNS 来源：若 A donor 审计确认本研究使用 CHNS 数据，由项目方按 [CHNS Data Use Agreement 的 M 条](https://www.cpc.unc.edu/projects/china/data/datasets/DataUseAgreementCHNS_20201020.pdf)在相应出版物加入协议要求的完整致谢，并复核数据使用与派生披露范围。当前工程包不含原始 CHNS 记录；本段不预先认定协议对每个候选字段的适用性。
