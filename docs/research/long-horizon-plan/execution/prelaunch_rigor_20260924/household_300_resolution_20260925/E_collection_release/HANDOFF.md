# E 固定画像、离线合同与独立角色入口交接

2026-09-26。已形成 A/B/C/F **固定角色输入**的 CSV 包、经 F 核对的 G 3000 日工程案例、离线采集合同与独立角色 HTTP 入口；不含真人回答。CSV 导出状态 `FIXED_PROFILE_EXPORT_SEMANTIC_PASS_D_RESULTS_PENDING` 是早于 D/G 完成的固定画像快照，未改写状态字段；具体每文件哈希和行数以 `PACKAGE_MANIFEST.json` 为准。当前 F 角色门仅批准工程预览，真人采集未获批准。

## 已完成

- `DATA_MANUFACTURING_PATH.md` 从七普/CHNS/UN/NBS/原 EB 问卷与 DeST/天气逐层指向 A/B/C/F 算法和 300 户字段，区分边际校准、局部匹配、实验设定、物理代理、未来真人反馈。
- `export_profiles_csv.py` 固定输入 SHA：A `d8446c68dd81fa6865cb79add18602fa609188b18631b4134c315385a90ad810`、B `7dbd4e5c87cc440de9f23a5042d83a809bd1cfea9d422245d228816146daaa69`、C `bdaab43a705bfb1fba0a675e73e86284aefe38dbcc0db9dd0271190fa42753d3`、F `4ccfc37140dce0a644a313baa7e53082d93db8df7e2797c2401d82868385fb35`。任何输入变更使导出停止，须审版本后更新锁。
- UTF-8 BOM 主表 `households_300.csv` 恰 300 行；长表 `members_300.csv` 749、`member_links_300.csv` 585、`member_windows_300.csv` 2,878、`devices_300.csv` 734、`zones_300.csv` 2,191、`question_answers_300.csv` 20,594、`provenance_300.csv` 79,827 行。多值、关系、成员时窗和跳题状态均为结构化长表；主表不装整条 JSON。`DATA_DICTIONARY.md` 解释全部表、单位、空值及状态。
- `export_profiles_csv.py --verify` 逐格反读、行数、300 唯一户键、成员/关系外键、设备唯一键、66×300 户题组合和 27 户整套面积来源标记均通过。`audit_profile_semantics.py` 独立核 66 题、成员偏好、角色卡及 F 整套面积绑定，通过 300/300；完整卡在主表 `actor_card_full`。`SEMANTIC_AUDIT.json` 与 `shared_area_resolution_27.csv` 保存结果和逐户数值链。
- B 画像中的旧合住 `X_AREA` 错误按已确认的 F 证据修复。22 户改变面积档、5 户档位相同而依据改变。B 行为子集 SHA **不变**（`e71dad6b90ca311a1af103c1eda014b28df643bf21cb91059349ae905b1c8181`）；成员、设备、态度、普通时间窗及物理 IDF/EPW 均未随修复改变。B 的 `validate_profile_300.py` 300/300 通过。
- `build_public_role_package.py` 由已锁定私有 CSV 派生 `public_role_package/`：七张公开候选表（300 户、749 成员、585 关系、2,878 时窗、734 设备、20,594 问卷行、79,827 来源行），去掉 `zones_300.csv` 及主表中的 IDF/EPW 本地路径，保留来源标识、城市、原型、天气站与内容指纹。逐表重读、哈希绑定和绝对路径/运行标记检查通过；`PUBLIC_MANIFEST.json` 状态为 `PUBLIC_CANDIDATE_FIXED_ROLES_ONLY_NOT_COLLECTION_READY`。真正公开前仍须按 F 白名单逐文件复核。
- `offline_collection_contract.py` 与 `OFFLINE_CASEBANK_AND_FEEDBACK_CONTRACT.md` 定义最终验收离线十天案例、A/B 盲序、固定角色、中断续答、五种选择、原四项评分、幂等/修订/撤回、工程测试隔离和训练切分边界。`test_offline_collection_contract.py` 的 8 项检查仅用内存虚构样本验证合同；真实模拟案例由独立的 G→F→E 路径产生。
- 合同已按主任务复核修订：语义差异以反馈前的当日证据为准，允许哈希不同但等效/不适用时禁止收集；服务端同意与来源核验、提交深拷贝、主轨未见家庭/严格附轨未见家庭及方案族拆分均有反例测试。`METHOD_EXPLANATION.md` 给出 14 行中文方法口径。本批 G 仅以同日合法设备动作差异形成 2277 个可评价日；温度、任务、费用或电网收益没有独立对照标签。
- `realtime_pilot/role_ten_day.py`、`static/roles.html`/`roles.css`/`roles.js` 和 `server.py` 小范围路由形成独立 `/roles` HTTP 入口。浏览器上方显示城市与 CSWD **模拟夏季**代理天气，中部用源模型之外的通用住宅 SVG 加面积/成员年龄/设备/经济态度；可展开完整角色卡、成员时窗、设备使用/调整条件和原问卷 66 题的中文角色事实。下方按同户十天展示左/右盲序、各自此前轨迹、设备时间、室温与本户受控设备代理电量。页面明确“预先生成的两条十天安排，回答不改变后续轨迹”。原 `/` 自报问卷、原题和规划逻辑未修改。
- 角色服务用独立 SQLite 保存匿名 cookie 固定户、同意版本/时间/批次、反馈快照、幂等/修订与撤回。第 1 日及非对照日确认阅读，对照日回答或明确跳过，才开放下一天；服务端记录展示和操作顺序。已看过未来日后修订早日标记 `future_exposure`，严格顺序训练导出排除，审计保留。`data_origin` 由服务端按工程/真人模式定，不接受浏览器自报；管理员受控导出区分审计与训练视图，工程测试不会进入真人训练。所有角色 POST 仍走原服务同源检查。工程模式浏览器回归在独立临时端口和数据目录完成，未调用模型 API。
- `ROLE_HTTP_INTERFACE.md` 规定 G→E 三个实际已验收输入文件及 F 当前有效放行文件。F 对 G 真实 3000 日与投影逐项读回，E 写入 `G_casebank/accepted_public/{casebank.json,accepted_contrasts.json,display_payloads.json}`；F `ROLE_COLLECTION_RELEASE_GATE.json` 签发 `ROLE_TECHNICAL_PREVIEW_APPROVED`，`engineering_only=true`、`human_collection_approved=false`。启动时重算公开包 manifest 和七张实际 CSV 的 SHA；案例库与 F 门逐值绑定画像、公开包、meter 和最终证据身份。放行缺失、指纹不符或撤回立即锁定，已登录者仍可撤回单日或整批记录。角色真人模式须单独启用并获 F 的真人门；临时工程夹具仅用于接口测试。
- 验证：E 合同 8 项单元测试；角色 HTTP 10 项集成测试，含原问卷 `human_pilot=true` 与角色工程预览同时运行、工程回答来源及训练导出隔离、角色真人模式被技术门拒绝，以及旧 `/api/households` 回归、F 撤回、逐日解锁、幂等/修订/撤回和来源绑定。浏览器与 HTTP 已接入 G 真实 3000 日投影，在第 1/2 日实际显示、评价并检验旧入口；浏览器试填仍只记 `synthetic_engineering_test`。角色预览覆盖独居/多人/合住/无空调/多设备；窄屏页面已核对城市、第 1 日天气与住宅摘要。真人训练导出样本为 0。

## 交给主任务/后续整合的事项

1. D v3 单户计量和最终链已获 F 独立读回；旧 `f372...`、`f2ca...` 不能作数值或采集放行。G 真实运行、F 审查、E accepted 投影、F 工程预览门均已完成；下一门是适用知情同意、认知试填和 F **真人采集**批准，不能把当前技术门升级为真人门。
2. `display_payloads.json` 已从 G 的实际输出投影并受哈希锁定；`indoor_temperature_c` 按本户全部房间及 24 小时等权平均，含未受控空调房间。房子图展示通用住户单元或合住私有房间/共用空间示意，不是源模型几何；合住不能把整套空间全计为本户控制。
3. 公开 GitHub 前需审 IDF/天气资产许可和可携带性、私有研究路径/原始数据白名单。完整的本地审计包仍保留仓库相对模型路径；公开候选包已经去除路径和源模型内部热区表，且未捆绑 IDF/EPW。此处真人样本数为 0，未推送 GitHub。

本任务未修改原真实问卷页面或题目、A/C/D 几何或仿真文件，未调用模型 API，未提交或推送 GitHub。
