# 300 户合成家庭：数据制造路径与证据边界

本包的目标是中国**城市家庭户**角色扮演和同户用电方案评价。300 是实验角色数，不是 300 名受访者、300 栋实测住宅或全国多变量联合抽样。所有角色条件来自固定的 A/B/C 输入版本，见 `PACKAGE_MANIFEST.json`。当前无真人反馈。D 十天仿真和 G 逐日投影已完成 F 独立核对，并获工程预览放行；本 CSV 是此前生成的固定画像快照，不含十天结果，其 manifest 状态字段保持原样。

## 从公开材料到字段

| 环节 | 原始材料与实际可用信息 | 使用规则与输出字段 | 为什么可用、不能扩称什么 |
|---|---|---|---|
| 城市家庭人数与代际 | [七普 2020 城市表 5-1a](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/A0501a.xls)，A 的 `SOURCE_EVIDENCE.md`/`METHOD_AND_AUDIT.md`；A 沿用既有 300 户整数配额，并排除未满 20 岁单人户 | 固定 `role_id`、`family_size`、`generation_category`；300 户、749 人，人数×代际配额冻结 | 这是汇总格的配额运输，**不是**获得了 300 条普查户记录。七普标准时点为 2020-11-01，见[官方方案](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf)。 |
| 住房自然间数与建筑面积 | [七普城市表 8-3a](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/A0803a.xls)的省×代际×H7 自然房间数；[城市表 8-2a](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/A0802a.xls)的省级 H6 人均建筑面积分箱；[H6/H7 官方解释](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf) | 省×代际 H7 和省 H6 分箱整数配额不变；闭箱用中点，开口箱声明为 8、75㎡/人设计点；乘同住人数得本户 H6 类设计建筑面积 | H6、H7 来自不同表和分母，不存在可直接抽取的全国同户面积×房间联合表。H7 自然间数不等于卧室或 EnergyPlus 热区数。 |
| 局部同户结构辅助 | [CHNS 2015 官方问卷与数据页](https://chns.cpc.unc.edu/data/datasets/)；A 用 2,198 个本地核验有效城市点同户格的 L16 使用面积、L17 房间数；[CHNS 权重说明](https://dataverse.unc.edu/api/access/datafile/7505036) | 在人数×房间格内只取**每人使用面积相对秩**，在同省 H6 分箱内排序；另加角色卡几何筛网：2/3/4/5 间至少 20/35/45/60㎡，单间不超过 110㎡，家庭不超过 350㎡；输出 `h6_design_building_area_m2` 与 H7 房间 | 秩传输和筛网是实验假设。L16 使用面积不乘 1.33 充作本户建筑面积；CHNS 年份、地区及 L17 定义均不能提供 2020 全国 H6×H7 联合比例。A 对 4 户换房间配额内位置、35 户改无约束秩候选 H6 箱，保留原配额并记录。 |
| 城市落点与成员 | [UN WUP 2025 城市人口文件](https://population.un.org/wup/assets/Download/Cities/WUP2025-F21-DEGURBA-Cities_Pop.xlsx)经 A 既有行政匹配；七普年龄带与家庭模板 | 稳定分配至 178 城；在年龄带内用约束哈希给设计年龄，亲子至少差 18 岁，补关系链接；输出 `city/province`、`members_300.csv`、`member_links_300.csv` | 城市人口是城市落点代理，不是家庭户抽样权重；精确年龄、亲缘细节和 `cityrole` 身份是合成值。 |
| 合住面积口径 | 官方 H6 允许合住户按独用房间和公区分摊填本户面积；[CFPS 2020 问卷](https://www.isss.pku.edu.cn/cfps/docs/20230629111959565639.pdf)的 30㎡ 只是访员软核查。F 的 `shared_whole_dwelling_area_27.json` 又从冻结 C 的最终 IDF 逐个热区核**整套源单元净面积** | A 的 27 户 <30㎡ H6 类值继续是**本户分摊建筑面积**。对原 EB `X_AREA`“合租按整套住房”，B 新版用 F 整套净面积除以实验净/建筑比 0.95 得**整套设计建筑面积**并投原五档；保留独用房、分摊公区和两种面积口径 | 整套值是经几何验证的**实验设计值**，不是七普原始逐户住房值、现场测量或整栋 DeST 建筑面积。22 户纠正面积档，5 户档未变但依据改变。 |
| 收入、电费和态度 | [国家统计局 2023 收入公报](https://www.stats.gov.cn/sj/zxfb/202401/t20240116_1946622.html)的城镇人均年可支配收入中位数 47,122 元；[能源负担研究](https://www.nature.com/articles/s41560-023-01193-z)区分成本与负担；原 EB v4.5 问卷；江苏需求响应、西安空调中断、广东智能能源家居研究见 B 的 `SOURCES_AND_RULES.md` | B 以 2000/3200/4500/6500/9500 元五个人均月情境乘家庭人数形成总收入；账单独立轮转、与收入 12% 上限和设备情境下限做合理性筛网；电费压力、节费、舒适、电网友好、控制权、通知分轴生成。5 压力×5 取舍×3 控制权共 75 格各 4 户 | 中位数仅提供**量级锚点**，不能把可支配收入等同于题目的月总收入。态度没有同题同户全国频率，不设人口权重；预算说明是可扮演的实验背景，不是被调查者真实困难。 |
| 设备拥有、数量与时间 | [CHNS 2015 本地空调×洗衣机四格](../../CHNS_2015_AC_WASHER_JOINT_20260925.json)：2,196 个按 B 筛选的城市同户有效格，均无 102、仅空调 32、仅洗衣 494、两者均有 1,568；[国家统计局 2023 耐用品](https://www.stats.gov.cn/zt_18555/ztfx/xzg75njjshfzcj/202409/t20240920_1956595.html)为台/百户；[浙江调查总队 2024](https://zjzd.stats.gov.cn/dcfx/art/2025/art_3c052f0ab0554d53812047494e6c7b27.html)是地方边际 | 先按 CHNS 局部四格近似分配 AC/洗衣，再以 A 住房形态施加可控权：27 合住户只纳入私有空调；独立小面积限制洗碗机、烘干机、家充 EV；其他设备做实验覆盖。最终 AC/洗衣/洗碗/烘干/电热水器/家充 EV 为 224/255/30/36/165/24 户。设备频次、台数和普通日时钟来自 B 的确定性实验模板，遵守现行 66 题值域 | CHNS 四格是局部、旧年份、未代表全国；全国台/百户不是拥有户比例，浙江热水器不区分电/燃气。家充 EV 和电热水器配额尤其不能说成统计校准。普通日时钟不是逐户观察。 |
| 成员作息与在场 | [国家统计局 2024 时间利用调查](https://www.stats.gov.cn/sj/zxfb/202410/t20241031_1957217.html)只支持按工作/休息日区别；[Chen 等城市住宅行为研究](https://www.sciencedirect.com/science/article/pii/S0378778824010053)支持设备使用的时空差异 | B 依设计年龄给工作、居家、混合、轮班角色和典型工作日/周末在家窗；普通任务从 19:00 后可装载，EV 配给有成年典型外出成员的户。`H_ac` 必须按冻结码本解读：下午 **14:00–23:00**、傍晚 **18:00–23:00**、全天、或自选时段 | 调查没有给本 300 户的逐时在场；轮班固定时段为未知。典型日不等于某个十天事件日。空屋预冷只有确认实际预约/远控能力与家户许可后才可计入计划，空屋冷量不算舒适收益。 |
| 地区建筑与天气 | [DeST 官方建筑目录](https://www.dest.net.cn/dxjzk)，C 的 `FROZEN_INPUTS.json`、`building_300.json`、`source_unit_audit_300.json`、`static_audit_300.json`、`runtime_300.json`；[EnergyPlus IdealLoads](https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-zone-forced-air-units.html) | C 从 193 个去重源 IDF、106 个天气文件组合/派生 300 个实际 IDF/EPW 绑定；以 A 面积、H7 房间、户位和地区原型确定几何/热区。独立户净面积比用实验 `1/1.33`；合住本户份额净面积比用实验 `0.95`。CSV 保存源目录键、文件哈希、仓库相对引用、天气站与距城市的距离、家庭可控区边界 | 原型复用不等于 300 栋独立实测住宅。32 户天气代理站距城市 >100km；C 的 300 个一日基础运行只证明接口执行和代理计量，不是家庭实测能耗。源默认背景区不计作本户设备。 |
| 完整十天和采集 | D 最终证据链经 F 独立读回；G 按冻结政策完成 300 户×10 日实际离线运行，F 对实际逐日载荷、语义和展示对象独立核对。原 EB v4.5 字段契约仍是角色答题唯一问法 | 本 CSV 仍仅导出上述**固定画像**。G 的 3000 日案例单独投影到 `G_casebank/accepted_public/`，由 F 的 `ROLE_COLLECTION_RELEASE_GATE.json` 仅批准工程试填；真人选择、理由和评分仍待真实采集 | 旧 D 结果不能流入本 CSV。G 的模拟日和工程试填不等于真人反馈、实测家庭用电或真人采集批准。 |

## 可复查的制造链

```text
七普城市边际 + H6/H7 口径 ──配额/约束──> A family_300.json
CHNS 局部同户秩 + UN 城市代理 ────────┘
收入/设备/行为构念 + EB v4.5 66题 ─────> B profile_300.json / behavior_300.json
DeST 原型 + CSWD 天气 + A 面积/户位 ──> C building_300.json + IDF/EPW
A + B + C 固定哈希 ──> 本 E 的 300 户主表与成员/设备/热区/逐题/来源长表
D 最终证据 + G 3000 日真实离线运行 ──F 独立核对──> accepted_public 工程模拟案例，不混入本 CSV
真人逐日反馈（未采） ──> 独立真实回答表，不在本包预填
```

`observed` 的本项目逐户家庭/态度/回答目前为 **0**。`source_calibrated` 只指汇总边际配额或 DeST/天气原型引用；CHNS 条件相对秩、城市人口代理和住房匹配是 `matched/experimental`；确切年龄、时钟、台数、预算与态度是 `experimental`；C 冷量/COP 电量是 `derived_simulated_proxy`。本包 `provenance_300.csv` 逐户保留 A/B/C 字段标签及问卷题的来源 ID，`question_answers_300.csv` 保留 66 题原值、适用性和依据。

## 当前验收结论

- 字段/外键/CSV 回读：`export_profiles_csv.py --verify` 通过；300 户主表、749 成员、734 个拥有设备条目及 66×300 个题对完整。
- 语义：独立审计对 300 户×66 题的值域、条件适用、成员偏好、身份和完整角色卡覆盖通过；27 户合住 `X_AREA` 均与 F 整套设计建筑面积档匹配。整套面积的人口观察值仍为 0。
- 发布：本 CSV 的 `PACKAGE_MANIFEST.json` 仍标 `FIXED_PROFILE_EXPORT_SEMANTIC_PASS_D_RESULTS_PENDING`，这是生成时的**固定画像快照状态**，不随随后 D/G/F 进展改写。十天模拟结果在另一个经过 F 核对的案例包中，共 3000 日，其中 2277 日有当天动作差异、723 日等效。F 当前只签发 `ROLE_TECHNICAL_PREVIEW_APPROVED`、`human_collection_approved=false` 的工程门。天气引用指向仓库内私有研究资产，CSV 不捆绑 IDF/EPW；公开许可与可携带性须另核。真人反馈为 0，不能以模拟案例或本 CSV 声称真人偏好、家庭实测效果或整项 R1–R4 已通过。
