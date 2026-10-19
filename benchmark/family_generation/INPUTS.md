# 家庭生成输入与产物

生成配置`eb.family_generation.input.v1`只接受`total,subset_size,seed,prefix,pool`，其中`pool={path,sha256}`解析于配置目录内。数量为正整数，同源子集不能超过主批次。角色人数从固定EB实验构成用有理数最大余数法计算，不用外部簇占比或B结果。

参考池`eb.family_reference_pool.v1`包含完整`templates`及公共`assembly,shell_defaults,world_defaults`。其中：

| 对象 | 必需内容与处理 |
|---|---|
| 来源 | 唯一`template_id`、`evidence_kind`、`source_reference`，及`field_origins`逐项说明roster/relationships/housing/devices/permissions/life来源 |
| 成员事实`facts.members` | 成员ID、所属家庭、整数年龄、性别（可unknown）、工作状态（可unknown）、代际层级；与物理名册完全一致 |
| 家庭事实 | 目标N/G、完整共享家庭ID、明确成年决策人、关系边、照护条件和出行依据；不填补收入或实际偏好 |
| 关系边 | `subject,object,type`；parent/partner/sibling有明确代际条件；原始关系细分未知用`source_relation_unspecified`并保存`source_label`，不编造继亲或收养故事 |
| 住房`shell` | 与住房模块一致的面积、自然间、共享户数、设施和参照；原布局/设备条件不为成功重抽 |
| `world` | 住房/生活模块原格式的成员、床组、设备与使用权、安装条件、电力预算等；床组不能跨家庭，未登记操作权不自动授予 |
| `life` | 生活模块原格式的完整成员日历、服务政策、温控习惯和明确出行；本模块不从年龄推断职业和真实时间日记 |
| `eligible_archetypes` | 可实现的实验情境A–F，不是实测类型标签；F要求目标家庭有EV、成人操作权和明确工作日出行；E要求目标家庭有明确照护情境 |

parent边默认15岁最小代际年龄差、partner双方至少18岁、操作人至少16岁，均为**本参考构造的项目规则**，不是法律、医学结论或人口估计。已知继亲/收养应有独立明确字段/模型再支持；不能靠这些推测挽救来源含糊的情境。当前新入口要求同住成年决策人；旧批次16户外来监护支持不在此导出域中，保留为待显式访问模型支持的边界，不偷偷补成同住人口。

新批次对每个名额固定一次有来源的参考选择，不以结果失败为由重抽另一户。若某类没有合法来源，保留`source_support_unavailable`；构造或连接失败分别保留`construction_rejected/connection_rejected`。不从成功家庭重新归一化角色比例。

输出`families/*.json`保存完整规范事实及场景，`SUMMARY.json`保留所有请求名额；`SUBSET.json`引用主批次原文件和SHA，不另造家庭、不按能耗或接受结果选取。所有输入及产物的内容摘要进入`MANIFEST.json`，缺文件、额外文件或哈希不同均不能复用旧成功记录。

`connect`输出住房外壳与每户生活输入/需求/A及统一记录。共享住户使用与住房编译器一致的`-aux-01`身份。源中同房多台独立AC目前会保留明确不支持原因，不合并或删减设备。房型或A服务失败保留在总分母中；没有真实EP执行就不输出仿真通过结论。

规范样例可直接阅读`examples/REFERENCE_POOL.json`。原数据许可、匿名化及人口抽样责任由来源持有人承担；“授权联合来源”不意味着可以公开其记录。本仓库只提交合成公开样例和汇总，不提交调查原件。
