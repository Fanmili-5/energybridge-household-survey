# G 案例到独立角色 HTTP 页的接入边界

当前 `/roles` 可预览 300 个公开合成角色。D v3 最终证据链已由 F 独立读回；G 已按冻结政策完成 300 户×10 日的实际离线运行。F 审查 G 的实际文件后，E 才投影到 `G_casebank/accepted_public/`，F 再核对投影并签发 `ROLE_COLLECTION_RELEASE_GATE.json`，状态为 `ROLE_TECHNICAL_PREVIEW_APPROVED`、`engineering_only=true`、`human_collection_approved=false`。因此当前页面只开放已验收模拟案例的**工程试填**，不开放真人研究采集。角色服务绝不读取旧 `f372...` 或 `f2ca...` 数值作为放行依据。

## 放行文件

服务默认只读 `G_casebank/accepted_public/` 下的三个文件：

1. `casebank.json`：满足 E 的 `eb.offline_casebank.v1`，300 角色×10 日，状态 `accepted_offline`，每个日槽含 A/B 各自前事件状态、当日动作哈希和计划哈希。第 1 日共用背景且不收偏好。根对象含工程试填说明、`consent_version`、`study_batch_id`、`profile_sha256`、`public_role_manifest_sha256`、`meter_version_sha256` 和 `final_evidence_sha256`。当前工程批次为 `eb.engineering.preview.g3000.20260926.v1`；工程说明不能充当真人知情同意。
2. `accepted_contrasts.json`：满足 `eb.accepted_day_contrast.v1` 且 `independently_accepted`，按日绑定实际模板、前事件状态、当日动作/计划哈希和语义判断。F 对 G 的真实载荷和新单户 meter 版本独立核验后才允许投影；`pending` 文件没有直接改名充数。3000 日中 2277 日有当天动作差异、723 日等效。温度、任务完成、舒适和电网服务不是本批对照标签的独立依据。
3. `display_payloads.json`：按 `case_id` 映射 `{context,weather,plans}`。`weather={summary,station_key,simulated_day_index}`；`plans.A/B` 各是 `{branch_history_summary,device_schedule,indoor_temperature_c,controlled_device_kwh,task_completion,metrics}`。`device_schedule` 是不含内部 A/B 标签的可读字符串数组；`metrics` 保留经核对的限定指标。展示对象及 `metrics` 的规范化 SHA 必须与 casebank 对应哈希一致。任何本机路径、源几何或未核指标均不得进入此文件。`summary` 只能说模拟夏季日序/日期与温度，不应让用户误以为当下预报。

G 的 `display_payload_3000.jsonl` 是上游原始展示包。接入投影应逐日从 `history_by_branch`、`weather`、`ac_timeline`、`device_timeline` 和已审定的 `metrics` 生成上述简明中文内容，保留两分支各自历史但在浏览器只写“左侧/右侧”；绝不能把内部 A/B 名称写进自然语言。第 d 日只说明 d−1 日以前的分支背景。`attributable_kwh` 显示为“本户受控设备代理电量”，不得写成全户电表或人民币电费；`weighted_energy_index` 如显示须注明实验权重指数。

## 已冻结的上游身份与投影对应

G 的 `POLICY_LOCK.json` 写明 `meter_identity_sha256=8a733339576b738ef64431d61af4bbd46a94935fd21dda5478ef402419642824`，其中 D 最终证据链 SHA 为 `5fd5e1efc61f6772c5d98e6c2d5f97d3483dd5f271251158be5b41b9bad88832`，公开角色 manifest SHA 为 `54531a2880f96d6b2a1cb743a30f0e89e2acff0bfca86d47de1f8f5a04d96ace`。F 离线生产门绑定 G 政策锁 SHA `acffad28fed2d633a7cbe463157e9c15ee2f84f83cd10fa9db04d3e369ed787a`。E casebank 的 `meter_version_sha256` 对应 G 的 `meter_identity_sha256`，`final_evidence_sha256` 对应 D 最终证据链 SHA，`public_role_manifest_sha256` 对应公开包实际文件 SHA；`profile_sha256` 对应 B 固定画像 SHA。这些值经 F 的模拟投影和工程预览门逐值核对；该门不构成真人采集批准。

投影关系固定为：G 每日 `case_id/role_id/day_index` → E 日槽键；G `history_by_branch.A/B` → E 各分支 `branch_history_summary`，仅取目标日前的历史；G `weather` 与 `source_context.weather_station_key` → E `weather.summary/station_key/simulated_day_index`；G 每分支 `ac_timeline` 与 `device_timeline` → E 可读 `device_schedule`；G 每分支室温指标、`metrics.attributable_kwh` 与任务结果 → E `indoor_temperature_c`、`controlled_device_kwh`、`task_completion` 和经审定的 `metrics`。这里 `indoor_temperature_c` 是本户**所有房间及 24 小时等权平均**的仿真温度，包括未受控空调房间，不是受控房间温度或舒适评分。E 日槽的计划切片、当日动作、展示对象及指标哈希由实际投影后的内容重算并绑定 F 独立接受的对照索引；未提供或语义未审定的字段不以占位值补齐。

服务启动时重算 `public_role_package/PUBLIC_MANIFEST.json` 和七张实际 CSV 的 SHA，核对 manifest 固定 B 画像 SHA、casebank 画像 SHA 与公开包 SHA。新案例库、meter 版本、公开角色包和最终物理证据各有独立身份，不能只看 SHA 的格式。更换公开包或案例库须重启服务并重新核验。

除了三个文件，服务还**每次读取/提交**核对 `F_independent_review/ROLE_COLLECTION_RELEASE_GATE.json`。其 schema 为 `eb.F_role_collection_release.v1`，当前状态为 `ROLE_TECHNICAL_PREVIEW_APPROVED`、`revoked=false`、`engineering_only=true`、`human_collection_approved=false`。案例、对照、展示、公开包、画像、单户 meter 版本和最终证据 SHA 及验收时间均须与加载内容逐值相等；F 已在实际 G 3000 日载荷独立审查及 E 投影读回后签发。真人模式仍只接受日后单独签发的 `ROLE_COLLECTION_APPROVED`、`human_collection_approved=true` 且非工程批次的批准物；当前启动真人模式不能借工程门开放。部署应使 F 路径仅由审核流程写入、服务只读；HTTP 客户端不能指定批准文件或切换真人模式。真人模式服务器还拒绝案例目录、批准路径及角色数的工程覆盖参数，不把测试用 `b`×64 meter 当作正式身份。文件缺失或撤回立即停止工程同意、逐日读取、反馈和训练导出；已登录参与者仍可按安全事件标识撤回单日回答或整批同意，不返回旧数值。`G_OFFLINE_PRODUCTION_GATE.json`、G 候选文件和 G 自行改写的 gate 均不构成 F 独立放行。HTTP 路由与代码存在也不意味着已向真人开放。

`GET /api/roles/session` 在门撤回时仍给当前会话返回可撤回事件的 `event_id` 和日序，不提供旧方案或天气。旧案例/同意版本的会话标 `current_enrollment=false`，不返回新批日程，仍可撤回旧记录。`POST /api/roles/withdraw-day` 与 `POST /api/roles/withdraw-actor` 在门撤回时继续工作。`GET /api/roles/day/<n>` 要求前一天完成；第 1 天及非对照日须 `POST /api/roles/day-action` 确认阅读，对照日须回答或附简短原因明确跳过，才能开放下一天。服务端记录每次展示、确认、跳过、提交/修订和撤回；`GET /api/admin/roles/action-log` 提供受控操作记录。回看早期日后修订时，如服务端已展示过更晚日，该修订标 `future_exposure=true`，严格顺序训练导出排除它，审计事件仍保留。按钮确认不证明真人理解或注意力。

持久反馈只写服务端 `--data-dir/role_ten_day/feedback.sqlite3`；匿名浏览器 cookie 固定角色，服务端记录同意/来源，所有 POST 校验同源和幂等。受控审计导出保留旧批次、案例、画像、meter 和公开包指纹。训练导出只取当前已放行批次/案例、当前同意版本、未撤回且没有未来展示暴露的真人记录。原问卷的 `--human-pilot` 与角色模式分离：部署默认的原问卷真人来源保持原状，角色页默认仍为工程预览；角色真人模式须显式使用 `--role-human-pilot` 且取得独立的 F 真人门。当前工程回答只标记 `synthetic_engineering_test`，训练导出排除，即使工程浏览器试填成功，真人训练行仍为 0。自动化测试另在临时目录注入两户工程夹具及 `b`×64 假 meter，只证明接口行为；不可复制到真人部署。真实收集另需正式同意文案、认知试填与 F 的真人采集放行。

`GET /api/roles/profile/<id>` 返回完整 `actor_card_full`、成员时窗、设备条件和按原问卷题号聚合的 66 条中文角色事实。页面摘要保持简短，三处可展开区域显示上述细节；未填与条件不适用分别显示，不输出原始编码，不补写人类评价。完整角色卡供扮演参考，不能暗示左/右选择。
