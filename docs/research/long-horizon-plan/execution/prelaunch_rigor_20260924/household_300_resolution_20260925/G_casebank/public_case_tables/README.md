# 3000 日案例元数据表

`cases_3000.csv` 是 300 个固定合成家庭各 10 日的**案例元数据**，UTF-8 BOM 编码，可直接用表格软件打开。它来自 G 的固定候选方案、两条实际 EnergyPlus 仿真轨迹和 F 已核的离线展示文件；`MANIFEST.json` 绑定表本身与来源哈希。此表是公开候选，仍需 F 对导出表独立复核，不能据此开放真人采集。

每行给出案例 ID、城市、模拟日期、方案族、当日是否存在实际动作差异及理由、基线/候选的本户设备和选中空调代理电量、两者之差、模拟天气范围及室温汇总。`candidate_minus_baseline_attributable_kwh` 是候选减基线，负值只表示此实验代理电量较低，不是已测节费。纯设备移时可有当日动作差异而逐日总电量相同。

电量单位为 kWh，只含本户私有设备和选中热区按 COP=3 计算的空调代理；它不是全户电表或人民币电费。室温列是**本户全部房间的 24 小时等权均温**，房间和小时均等权，含未由空调控制的房间；不是空调受控房间专属温度或舒适评分。天气是 CSWD 典型年模拟情境，不是实时天气。任务完成、水温、车辆电量状态和真人偏好均未由此表证明或填入。

表内不含本机路径、源几何、逐房间逐时明细或真人答案。固定角色画像公开候选表位于 `E_collection_release/public_role_package/`；完整本地审计链在 `G_casebank/candidate_input_manifest_300.json`、`candidate_runtime_300.json`、`day_payload_3000.jsonl`、`display_payload_3000.jsonl`，页面投影在 `display_payloads_pending.json`。原始 B/C/D IDF 和天气仍是研究工作区私有输入，不随本表发布。

重新导出时，先进入本 README 所在目录的上一级 `G_casebank/`，再运行 `python3 export_public_case_tables.py`。脚本先核对 F 的 `G_SIMULATION_ACCEPTANCE.json` 与全部固定 G 来源哈希，再写出 CSV 与 manifest。重新执行物理生产属于另一流程，见同一 `G_casebank/` 目录下的 `HANDOFF.md`。
