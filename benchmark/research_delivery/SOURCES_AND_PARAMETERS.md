# 来源与参数的实际支持范围

本表是方法审计，不是家庭分布的实测标定。机制声明与来源位于`unified/DEVICE_RULES.json`、`unified/EVIDENCE.json`、画像v3及生活输入中；JSON说明字段与实际执行检查的区别、逐设备入口和适用范围见[DEVICE_EXECUTION_MAP.md](DEVICE_EXECUTION_MAP.md)。

v2.10将精确任务数覆盖设为选题第一层目标，这是本项目明确的实验设计选择，非论文给定配比；MILP是成熟工具，日期—任务数最大匹配是独立核对工具。原始出处、实际核读范围及不支持的主张见[JOINT_ORDER_SELECTION_METHOD.md](JOINT_ORDER_SELECTION_METHOD.md)。

| 字段或决定 | 输入与实际作用位置 | 来源性质 | 必须公开的边界 |
|---|---|---|---|
| 六类核心 | v3冻结画像，B的立场和许可上下文 | 原EB角色的项目操作化 | 不当作真实人口分群或人口比例 |
| 类内随机与载荷0.7 | v3 Gaussian Copula；同户十天不重抽 | 成熟工具＋项目未拟合参数 | 载荷不是输出字段的实测相关系数；离散映射会改变相关结构 |
| 日程、家庭关系、设备与资格 | 原输入与原世界；A约束及B不变项 | 既有事实/生成来源各自保留 | 不因选题或成功而修改 |
| 逐设备时间、少操作取舍与舒适偏好 | 画像对应目标及B判断上下文 | v3条件映射和实验设定 | 不从旧A倒推习惯；尚未接入项记录原因 |
| 日期及跨日目标 | `dated_targets`、`target_ledger` | 原日期＋独立日期种子 | 不取统一钟点，不按B机会挑日期 |
| 缺少固定操作人的条件时间目标（显式启用） | `dated_target_context.derive` | 冻结v3坐标＋原资格日历＋项目条件映射 | 保留个人习惯/分工未知，不增加权限；局部见证不代表全屋可同时实现，见CONDITIONAL_TARGET_METHOD.md |
| 日衣物量、容量、洗碗餐次 | `compile_life`原库存与餐次规则 | 原生活配置中的项目服务模型 | 规则不是实测频率；原程序时长和物料不改 |
| 程序能耗及总回路 | 原设备/负载模型；排程累计功率与B名义轨迹 | 原输入及已有实验模型 | 平均程序功率不代表瞬态；额定上界不证明跳闸 |
| 同资产自动洗烘 | 显式`automatic_programs`或`reference50_A46_combo_v1`；分阶段排程，一次装取 | 原项目A46服务契约＋成熟区间/累计约束工具 | 封存原文及哈希；不从A时间或习惯推能力，不是论文给出的参数或厂商认证；见AUTOMATIC_SEQUENCE_METHOD.md |
| 人员资格、提案许可、执行确认 | 原authority、画像偏好、请求上下文 | 原权限与实验授权偏好分开 | 可用时间不等于愿意帮忙；提案不是执行同意 |
| CP-SAT及目标权重 | `a_solver.solve`，机器/人工分开归一化 | 成熟求解器＋项目权重 | 可行与最优分开；不证明真人会如此安排 |
| IPOG-C与二/具名三因素 | `ipog.generate`与存在性oracle | 成熟组合方法＋家庭因素映射 | 不保证低阶因素解释全部判断，不限制B只改两台 |
| 占用/洗烘约束传播 | `interval_propagation.propagate`，显式启用 | 局部一致性技术思想＋本项目区间支持判定 | 只删无必要工程支持的查询值；非空域不是全局可行证明；见INTERVAL_SEARCH_METHOD.md |
| 传播后的MRV/前向搜索 | `interval_search.assignments` | 成熟约束搜索思想＋项目值次序/1024节点预算 | 节点与旧笛卡尔积遍历不是相同CPU工作；不假定效果优于对照 |
| 装取模板、硬许可掩码 | `factorized.py`与原生域 | 项目计算表示 | 能还原全部被排除坐标，不能靠丢弃失败提速 |
| 装取日历冲突保留 | `handling_calendar_domain=include_life_conflicts` | 本benchmark提案任务的明确规则；不是论文给定冲突率 | 原数值服务边界及资格不扩大；日历/预约冲突是待判断事实；旧新动作域须列对应，不作同域优势比较 |
| 上游释放与完整程序最早界 | `service_bounds`及输入侧账本 | 原需求、时长和必要先后不等式 | 不以便利或后果剪枝；缺证据不给排除结论；独立网格检查证书 |
| 时间10分钟、温度步长 | 原输入能力优先，配置与原生网格 | 项目数值离散设定 | 不声称厂家精度或安全认证 |
| 冷温差0.5—2℃、水箱1—5℃ | 默认控制实验域；原始量纲仍保留 | 项目控制提案范围 | 不是舒适、健康或响应经验阈值；未知能力不补造 |
| 40℃停冷回退 | `AC_CONTRACT`与分轴状态描述 | 固定EB/项目编码路径 | 不是舒适温度、实际开停或制热停机 |
| 相对分位1/3、2/3 | 同动作维度位置 | 项目描述参数 | 不代表整份B强度或家庭负担大小 |
| 物化16×U、4倍查询、编码256 | 本轮影子基础预算；默认更大预算另列 | 项目计算设置 | 失败和重复计入；未知不能写成不存在 |
| A确定性时间20、单B查询0.05 | 锁定OR-Tools单线程求解 | 项目计算设置 | 确定性时间不是墙钟秒；未证明全局最优 |
| 设备/组合/语义重复权重0.25/0.5/1 | MILP归一化覆盖与去重 | 项目设置 | 需要零/半/双量敏感性；不决定接受答案 |
| 语义签名 | 机制、关系与成员角色，不以日期和ID造差异 | 项目有限语义代理 | 不宣称所有真人判断情境均可由签名区分 |
| 联合阶数选题因素 | 单任务、双任务、三任务及以上；保留原精确任务数 | 预声明有限因素映射 | 50户目录有4—6任务候选但最终题集未选入，不能将三任务及以上得分写成每个阶数都覆盖 |
| 十题与50户计算块 | 原采集设计与有限题位分配 | 项目设计/计算设置 | 不等于最优题量或1000户全局最优 |
| 对照矩阵 | 八户×三原日期×八种子，全部公开结果 | 预声明计算实验 | 八个家庭才是家庭层分析单位；不作人口推断 |

## 原始来源

- [Mackworth作者原文](https://www.cs.ubc.ca/~mack/Publications/AI77.pdf)，1977，DOI `10.1016/0004-3702(77)90007-8`：核读摘要、第6节及第7.1节；支持搜索前局部一致性传播，未支持本项目行为模型、预算或长尾比例。本项目使用专用区间传播及独立枚举验证，不宣称完整实现论文全部算法。

- [原EB固定架构提交](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/docs/ADAPTIVE_HARNESS_ARCHITECTURE.md)：保留共享设备及提案—同意—执行—后果分离，不继承其预设答案。
- [Ghosh、Henderson作者稿](https://people.orie.cornell.edu/shane/pubs/ChessboardOR.pdf)，发表DOI `10.1287/opre.50.5.820.364`：NORTA变换及其局限；作者稿日期2001，发表年2002。
- [Chen等作者稿](https://arxiv.org/pdf/2111.01881)，发表DOI `10.1016/j.apenergy.2022.119890`：活动与设备映射的方法比较，不能移植调查概率。
- [CP-SAT-LP原始说明](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.CP.2023.3)：求解工具，不提供家庭偏好权重。
- [IPOG-C原文](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=913191)，DOI `10.1109/ICST.2013.35`：条件组合生成和约束处理。
- [NIST IR7878](https://nvlpubs.nist.gov/nistpubs/ir/2012/NIST.IR.7878.pdf)：有限因素空间的覆盖定义。
- [Fanitabasi、Pournaras作者稿](https://arxiv.org/abs/1907.03470)，发表DOI `10.1109/ACCESS.2020.3001763`：设备级习惯、柔性及舒适取舍的区分。
- [Sanandaji等作者稿](https://arxiv.org/pdf/1310.1693)，发表DOI `10.1109/ACC.2014.6858956`：温控负荷的状态与动态约束，未验证本项目热后果。
- [Hainmueller等情境实验外部验证](https://eprints.lse.ac.uk/86341/1/Hainmueller_Hnagartner_Yamamoto_Validating%20vignette.pdf)，DOI `10.1073/pnas.1416587112`：情境判断不自动等于真实行为有效性。
- [ACM SIGIR artifact要求](https://sigir.org/general-information/acm-sigir-artifact-badging/)：用于组织文档、可运行性、完整性和验证材料，不声称获得认证。

## 后续论文有效性

本轮没有真人采集或模型训练。画像/错配画像对照保持同一A/B，采样对照保持题量和训练预算；记录理解度、理由对家庭证据的引用及分歧。不得用生成器规则定义真人答案的正确性。来源情境关联组的具体标识还须在训练前核验，本轮不输出已验收训练划分。

- [Haralick与Elliott作者托管IJCAI1979原文](https://www.haralick.org/DV/conferences/increasing_tree_search_efficiency_for_constraint_satisfaction_problems.pdf)：核读原页356—358及第2节，支持前向检查与剩余标签少者优先。1980扩展版DOI `10.1016/0004-3702(80)90051-X`仅核对元信息和摘要。两篇均不支持本项目家庭分布、预算或实际性能优势。
