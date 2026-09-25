# 300 个合成家庭与十天模拟案例：公开包入口

本包含 **300 个固定合成家庭**、每户十天的 **3,000 个离线模拟案例日**，以及一个仅用于工程预览的角色网页。2,277 日的 A/B 当日受控动作不同，723 日等价。**真人反馈 0 行；没有真人研究采集许可。** 每户第 1 日两分支完全相同，后续分别连续运行，不因页面回答改轨迹。

## 从哪里读

- [300 户公开角色表](../E_collection_release/public_role_package/README.md)：7 张 CSV、字段/来源清单；家庭、成员、在家窗、设备、66 题事实分开保存。
- [3,000 日案例元数据](../G_casebank/public_case_tables/README.md)：一行一案例，含模拟 A/B 分项代理电量、全天全本户房间均温、当日动作差异类别；`feedback_rows=0` 是**数量**，未填写人类选择或评分。
- [工程案例库](../G_casebank/accepted_public/casebank.json)、[逐日对照索引](../G_casebank/accepted_public/accepted_contrasts.json)、[页面展示载荷](../G_casebank/accepted_public/display_payloads.json)：只供固定工程批次 `eb.engineering.preview.g3000.20260926.v1` 使用。三件均经 [F 实际文件读回](G_accepted_public_readback.json)，角色 CSV 和案例表另经 [F 公开表读回](G_public_case_table_readback.json)。
- [受控技术门](ROLE_COLLECTION_RELEASE_GATE.json)：状态 `ROLE_TECHNICAL_PREVIEW_APPROVED`，`human_collection_approved=false`。不以工程试填冒充研究同意或正式 benchmark 样本。

## 来源与制造范围

[来源记录](../A_structure/SOURCE_EVIDENCE.md)与 [G 冻结策略](../G_casebank/CASEBANK_PLAN.md)给出数据和方案规则。家庭人数等城市边际来自[七普官方资料](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/)，CHNS 仅提供旧年份局部同户参照；DeST 原型和 CSWD 典型年天气用于物理模拟。成员具体年龄、作息、设备时钟、态度和方案均有实验设定，不能当作全国实测联合分布。[DeST 原型目录](https://www.dest.net.cn/dxjzk)、[CSWD 来源页](https://climate.onebuilding.org/sources/)和 [CHNS 数据入口](https://chns.cpc.unc.edu/data/datasets/)供有权使用者自行取得原始材料；仓库不镜像原模型、天气文件或调查微数据。

本仓库中的 A/B/C/D/G 构建脚本记录生成步骤；完整物理复跑还需另行取得有权使用的源资产与 EnergyPlus 环境。可直接复查公开文件的 SHA、300/3,000/2,277 计数、两分支日级哈希和 [F 有限模拟接受范围](G_SIMULATION_ACCEPTANCE.json)。本包未发布 IDF、EPW、EnergyPlus SQL、私人路径、工程测试数据库或个人反馈。

## 数值边界与本地页面

`attributable_kwh` 是**本户受控设备电量加选中空调冷量按 COP 3 折算的实验代理量**，不是全户电表、真实电费或节省金额。展示单值温度是**本户所有纳入房间、24 小时逐房逐时等权均值**，含未受控空调房间；不是受控房间舒适温度、个人即时体验或实测温度。设备任务是否完成没有单独物理模型，不从排程推出成功。

在仓库根目录可启动隔离工程页，例如 `python3 realtime_pilot/server.py --port 8766 --data-dir /tmp/energybridge-role-preview --disable-planning --session-cookie-name eb_role_preview_session`，访问 `http://127.0.0.1:8766/roles`。与原问卷在同一主机并行时，即使端口不同，浏览器 cookie 仍按主机共享；工程服务须使用独立 cookie 名和数据目录。页面默认不是 `--human-pilot`；工程回答只写指定本地测试目录。服务端 [反馈合同](../E_collection_release/OFFLINE_CASEBANK_AND_FEEDBACK_CONTRACT.md)描述按批次、同意版本和曝光顺序过滤训练导出；当前没有可发布的真人 benchmark 回答。真实研究需要另行完成适用的同意与认知试填、独立签发真人采集门，不能借用本工程批次。
