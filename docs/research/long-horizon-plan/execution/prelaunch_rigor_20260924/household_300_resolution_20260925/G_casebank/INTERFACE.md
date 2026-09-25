# G → E/前端：离线展示接口 v1

状态：冻结策略的 G 已生成 300 户真实候选运行与 3000 个逐日载荷。F 已独立核验候选 IDF、真实 SQL、逐日语义和 6000 条分支展示投影，并以 `G_SIMULATION_ACCEPTANCE.json` 仅接受离线仿真投影。B 已从确切的冻结 pending 文件投影 `accepted_public/` 三件；F 的 `ROLE_COLLECTION_RELEASE_GATE.json` 现为 `ROLE_TECHNICAL_PREVIEW_APPROVED`、`engineering_only=true`、`human_collection_approved=false`。这只允许工程技术预览和隔离测试，不是正式真人研究采集。前端只读已验收的离线载荷，不能在请求时调用 EB 规划 API 或制造方案。

## 发布身份与预结果锁

`POLICY_LOCK.json` 在读取任何 G 候选结果前冻结策略版本、种子、生成器源码 SHA 和输入身份。输入身份同时绑定 D v3 的 `ac_meter_contract_version=eb.D.single_household_AC_meter.v3`、D 输入清单/300 户运行/最终证据链 SHA、B 固定画像 SHA，以及 `E_collection_release/public_role_package/PUBLIC_MANIFEST.json` 的实际文件哈希。G 生成器启动时还逐个重算该公开角色包中 7 张 CSV 的 SHA；仅有字段格式正确而实际 CSV 被替换会失败。候选结果不能反向决定策略、偏移或挑选哪台设备。

G 的候选清单写出 `meter_identity`、`meter_identity_sha256`、`preresult_policy_lock_sha256` 和公开角色包指纹；后续 casebank、逐日展示载荷和 F 放行记录逐值绑定这些指纹与最终证据链。`accepted_public/` 的 `casebank.json`、`accepted_contrasts.json`、`display_payloads.json` 已由 B 在 F 仿真接受后派生并经 F 再核实际文件。服务按 `E_collection_release/ROLE_HTTP_INTERFACE.md` 逐次验证 F 的当前技术预览门与三个实际文件 SHA，撤回时停止新展示和提交。G 自检、原始 pending 文件或把它们改名，都不构成独立放行。

## 读取位置

| 本地文件 | 用途 | 对外边界 |
| --- | --- | --- |
| `candidate_input_manifest_300.json` | 300 户 B 候选 IDF、改动日程和来源 SHA | 私有：含本机 IDF/EPW 路径，不送浏览器 |
| `candidate_runtime_300.json` | 300 户 B 的 EnergyPlus 十天分项结果及复合缓存签名 | 私有核验，展示仅取当日限定摘要 |
| `day_payload_3000.jsonl` | 按 `case_id` 的 3000 条完整 A/B 日载荷 | 本地完整包，路径字段禁入 |
| `display_payload_3000.jsonl` | 与上表逐条同 `case_id`、去路径/私有标识的展示载荷 | 已审上游审计文件；工程页面读取下述 accepted 投影 |
| `display_payloads_pending.json` | 3000 条投影为 E 页面 `{context,weather,plans}` 的冻结上游对象，casebank 中的展示/指标哈希逐项绑定它 | 审计源，不由服务直接加载 |
| `casebank_pending.json`、`contrast_index_pending.json` | E 合同日索引和逐日对照的冻结上游证据 | 保留原始 pending 状态供追溯；服务读取派生的 accepted 版本 |
| `accepted_public/casebank.json`、`accepted_contrasts.json`、`display_payloads.json` | B 派生、F 已核的 3000 日正式离线投影三件 | 仅在 F 当前技术预览门逐次核验通过时供工程页面读取；真人研究采集未批准 |
| `trajectory_evidence_300.json` | 每户两分支运行、首日同起点、输入/输出哈希和日计数 | 本地验证 |
| `payload_self_audit_3000.json` | G 对上述真实文件的读回、哈希、逐时/逐日核算自检 | 自检，不替代 F 独立审查 |

## `display_payload_3000.jsonl` 单条键

```json
{
  "schema_version": "eb.G_display_payload.v1",
  "case_id": "cityrole-0001/day-02",
  "role_id": "cityrole-0001",
  "day_index": 2,
  "calendar_day": "07-15",
  "city": "南昌市",
  "province": "江西省",
  "source_context": {
    "source_catalog_key": "DeST source catalog ID",
    "weather_station_key": "CSWD station ID",
    "weather_kind": "CSWD typical-year scenario",
    "home_city_to_station_km": 0.0
  },
  "weather": {
    "outdoor_drybulb_c_hourly": [0.0],
    "min_c": 0.0,
    "max_c": 0.0
  },
  "cost_weight": {
    "kind": "uniform_experimental_time_weight_not_local_tariff",
    "unit": "weighted_kwh_index_not_RMB",
    "hourly_weights": [1.0]
  },
  "metrics_scope": "owned_device_electricity_plus_selected_AC_COP3_proxy_only_not_whole_home_bill",
  "history_by_branch": {
    "A": {"prior_days": 1, "prior_plan_hashes": [], "cumulative_attributable_kwh": 0.0, "previous_day_end_room_temp_c": {}},
    "B": {"prior_days": 1, "prior_plan_hashes": [], "cumulative_attributable_kwh": 0.0, "previous_day_end_room_temp_c": {}}
  },
  "plans": {
    "A": {"plan_hash": "sha256", "ac_timeline": [], "device_timeline": [], "metrics": {"device_kwh": {}, "ac_proxy_kwh": 0.0, "attributable_kwh": 0.0, "weighted_energy_index": 0.0, "controlled_room_temp_c_hourly": {}}},
    "B": {"plan_hash": "sha256", "ac_timeline": [], "device_timeline": [], "metrics": {"device_kwh": {}, "ac_proxy_kwh": 0.0, "attributable_kwh": 0.0, "weighted_energy_index": 0.0, "controlled_room_temp_c_hourly": {}}}
  },
  "semantic_contrast": {"status": "meaningful", "basis": "temperature_setpoint", "reason": null},
  "collectable_after_independent_acceptance": true,
  "participant_feedback": null
}
```

数组示意仅为键形；实物 `outdoor_drybulb_c_hourly`、`hourly_weights` 与室温按 24 个小时点填充。`ac_timeline` 和 `device_timeline` 是从实际 10 分钟计划压缩出的可读 `[start_min,end_min,value]` 片段，带设备/热区标识与单位，不包含绝对本机路径。`metrics` 另含 `attributable_kwh_hourly` 的 24 点以核实验权重。`history_by_branch` 的第 d 日只含前 d−1 日结果；两分支从同一起点出发，此后各自连续运行，不在每天重置热状态。第 1 日是相同背景日，`collectable_after_independent_acceptance=false`。

案例库按 E 的 `eb.offline_casebank.v1` 结构提供 300 户×10 日槽、逐日计划/载荷/指标哈希及真实语义决定；有意义差异可以零节电，纯标识差异不可收集。`participant_feedback` 始终为 `null`，左右盲化顺序、同意与真人来源由 E 服务端产生，不写在 G 展示载荷内。

## 当前实物与核验边界

`candidate_runtime_300.json` 为 300/300 户 `runtime_and_accounting_passed`：297 户新的 EnergyPlus 候选运行，3 户候选 IDF 与 D 基线完全相同且复用原 SQL。`trajectory_evidence_300.json` 逐户比较 07-14 的全部逐时 `ReportData` 行，300/300 A/B 完全相同。3000 日中，2277 日当日 10 分钟动作切片实质不同，723 日等效；分类为 AC 加设备移时 1081、设备移时 852、AC 设定点 344、无对照 723。纯设备移时可使逐日电量相同，但逐小时用电时序不同。`payload_self_audit_3000.json` 跨文件读回失败 0 项，最大的逐小时合计与逐日代理电量差约 `5.01e-7 kWh`。F 对冻结的真实 G 输入、SQL、逐日载荷及页面投影已另行独立读回，批准范围仅为仿真案例投影和工程预览准备。

冻结上游 pending 案例库所有日槽仍是 `collectable=false`、`pair_status=pending_review`，它本身不可被服务用于提交；经 B/F 验收的派生三件由当前工程技术预览门控制。真人反馈仍为 0。页面投影用匿名房间名；40°C 是 D 停用制冷的仿真哨兵值，不作为用户方案展示。单一温度值是**本户全部房间的 24 小时等权均温**，房间和小时均等权，含未由空调控制的房间；它不是受控空调房间温度或舒适评分。逐房间逐时数据保留在原始载荷。任务完成、水温、车辆电量状态未建模。费用权重均匀，指标单位是实验加权 kWh 指数，不是地方电价或人民币账单。
