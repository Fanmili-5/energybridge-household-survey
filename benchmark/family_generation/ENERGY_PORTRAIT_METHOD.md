# 能源与逐设备画像 v3

> 2026-10-22：当前本地候选新增[家庭共享与成员偏好v4](HOUSEHOLD_PREFERENCES_METHOD.md)。下文及v3报告为历史版本，不能用作v4的验证结果。v4已纠正“用个人B/C/E设备标志替代家庭共享资格”的规则，并实际继承共享习惯与成员偏好。

2026-10-21。本版修正v2把全家空闲合并、按“有无照护”套句子、缺少储水设温/制热动作说明及沿用旧案例日期的问题。代码统一用于家庭构造、住房/日程绑定和现有家庭独立补充；不改已有成员、设备、生活安排或A/B，不更新线上。

## 输入和信息边界

偏好生成只读取以下声明：EB角色；原成员与资产；逐设备操作资格与登记操作人；完整既有日历及每人操作窗口；明确权限；**事先给定的服务需求**和原设备政策。`habit_days`形成跨案例的同一家庭条件，不能因选中哪个B而更换个性。

需求输入采用`decision_conditions.contract_input`字段白名单，保留释放/完成期限、原程序时长、取出等待上限、用水需求、原行程/连接期与目标SOC；排除A决定的启动、装取、实际等待、是否已经使用预约等字段。A/B命令、VPP选题结果、仿真后果和答卷均不进入偏好函数。需求及日历本身也是原项目声明情境，不冒充实测习惯。

`from_formal`按当前封存50户的正式日期匹配原日历与源上下文，核对A来源摘要；不再取旧版本日期。`from_life`将原需求的全程时间原点换为各日原点，跨午夜保留到次日，不取模。家庭阶段尚未形成具体服务时，使用同一规则库形成已知原则并标记`not_yet_bound`；后续只绑定已有需求，不从A执行时间推测偏好。未知字段不随机补齐。

## 统一算法

```text
facts = whitelist(家庭/资产/权限/完整日历/事前需求)
for each owned asset × supported device kind:
    handlers = explicitly qualified residents + originally declared external operators
    evidence = per-handler windows/care/work + actual room activities + service contracts
    active_rules = evaluate conditional tradeoffs(evidence)   # 确定性，无随机数
    preference = EB role core + active_rules                 # 有条件的实验声明
    consent = per-action scope ∩ explicit existing permission ∩ mode-specific bounds
render the same structured rules as participant family material
independently audit existing A/B against original constraints; retain every source pair
```

这是项目自行设计的**条件编译与约束核对算法**，不是从数据拟合出的个体心理预测器，也不声称复现了论文中的调度优化器。`conditional_preferences`逐条保存`rule_id/trigger/preference/evidence_fields/origin/strength`，`decision_conditions`保留实际证据。所有新增习惯为可审查的实验条件；不生成接受/拒绝、评分或理由真值。

操作资格、登记默认操作人、某次A的实际操作人和问卷中的确认人分别保存。登记字段不代表某次一定由该人装取；不能为了新画像把已有A换人。非同住监护支持者只使用原已声明资格与到访窗口，不增加同住人口、不臆测其全天生活。人有空不表示愿意代劳，更不表示已授权控制。

## 逐设备规则与来源

| 设备 | 自动关联条件与实际取舍 | 保留的边界 |
|---|---|---|
| 洗衣 | 查本设备合格人员各自的工作/照护/操作窗口；有照护负担不均时不默认把任务转给较重者；装入和取出分别衔接，保留原等待上限 | 原衣物量、完整程序、释放/交付期限不变。程序结束不等于已可穿 |
| 烘干 | 明确声明自动洗烘一体机且同资产才声明自动衔接，不补人工转移；同资产但没有自动转换声明时保留未知；独立烘干只关联原上游需求 | 不新增烘干需求，不缩短程序，不把设备拥有当作自动转程序的证据 |
| 洗碗 | 关联原餐具释放与完成期限、逐设备装取人员及等待上限；未绑定需求时不声称有无限库存或可任意拖到下一餐 | 不临时变成手洗，不补造餐具库存，不额外加操作 |
| 热水 | 按原用水区间的相交/首尾相接分组，无人为“相近”阈值；存在分段用水就保护各段；只有儿童用水与明确协助活动实际重叠才添加照护准备偏好 | 储水设温、加热时刻、洗浴时间及出水温度分开。原水量/出水要求不降低；不从年龄推断医学温度 |
| 空调 | 每房间读真实的睡眠、儿童休息、工作/学习和普通活动；组合相应稳定使用偏好；不把儿童照护推广到全屋 | 制冷、制热、提前运行、停机分别授权；40℃退让命令不是偏好或实际室温；制冷许可不自动延伸为制热许可 |
| EV | 读取原已声明行程目的、连接期、离车时间及目标SOC，区分工作相关与其他既定任务；不统一假定每天固定早班通勤 | 既有85%等目标原值保留，不替换为EB示例80%或出行最低值；不增加插拔、出行或V2G |

上述逐人负担、房间活动、期限和行程是**已有声明事实**；把这些条件映射为“少临时打断、少未经约定换人、保护睡眠、各段备水”等偏好，是**本项目条件化实验设定**。没有文献证明某类真人必然选择这些偏好，也不据此估计人群比例。

### EB必须保留的核心

固定原EB提交`2b17ae63e613da776c93e900f5dace50d63a88a8`，七份角色卡/基础角色文件摘要见`ENERGY_PORTRAIT_SOURCES.json`。A关注费用但先解释确认；B舒适和原节奏优先；C当天确认且可撤回；D在明确边界内积极响应；E照护与稳定、默认建议；F优先保护原出行电量。六类作为实验条件，不是人口自然分类。

同时保留原逐设备DR开关，特别是B/C/E基础角色洗衣的常规DR关闭标志。真实拥有的设备不被EB基础角色的`present=false`删除；将同一态度扩展到该设备须标`device_absent_from_basic_EB_persona_requires_extension`，属于项目扩展，不冒充原EB已有授权。

EB的舒适偏好与原项目控制边界分别存储。例如A的“最好不超过26℃”与原项目“常用25.5℃、临时提高1℃、60分钟”可形成取舍，不能把允许提出的26.5℃改写成家庭肯定喜欢它。原EB制冷温度不直接套到冬季制热。原EB内部角色卡与basic JSON的B类温度表述有细微差异，两份来源均保留，不当作精确实测分布。

### 授权不等于能力或已经接受

`proposal_actions`只说明可提出什么；`routine_DR_eligible`只说明实验提议资格；两者都不代表已取得本次同意。`standing_consent_actions`必须同时满足原明确预授权、该动作的具体范围和必要服务条件。D/F角色本身、有空、目标值、设备支持预约或`target_control_authorized`均不能单独授权。

储水设温变化、制热变化有独立动作项。**当前50户未声明两者的数值调整授权范围**，因此逐案说明确认；不从A里的60℃水箱命令推断偏好或可降幅度，也不把制冷+1℃当成制热许可。完整移时仍保留原范围，超范围、换人、加人工操作、改程序/水量/目标SOC、占用房间停机等需要另行说明。未声明范围与已有物理后果是不同字段，前者不把封存后果改成未知。

## 文献能支撑什么

- Barsanti、Yilmaz、Binder，2024，[Beyond the average consumer](https://doi.org/10.1016/j.erss.2024.103463)：支持区分设备使用模式、生活背景与移时不便，不支持给这50户推定真人偏好或授权。
- Fanitabasi、Pournaras，2020，[Appliance-Level Flexible Scheduling for Socio-Technical Smart Grid Optimization](https://eprints.whiterose.ac.uk/id/eprint/165733/)，DOI `10.1109/ACCESS.2020.3001763`：支持分别建模设备、使用偏好、舒适与自主提供的柔性。论文的自主偏好输入不等于本文条件规则已获实证验证。

本次核查范围为出版社摘要/研究亮点和作者机构库摘要，未将摘要写成对全文算法的复现。具体关联规则、角色扩展和授权细化明确登记为项目方法，见`DEVICE_PERSONA_EVIDENCE.json`及`DEVICE_PERSONA_RULES.json`。

## 检查、保留与复现

先验证0653、0250两户，再检查其余48户。每户用当前正式10天日历，读取全部500组已有A/B。独立核对设备归属、正时长、洗烘先后、装取先后、原操作资格/窗口、同人操作重叠、原服务期限/等待、原移时及模式授权范围。对B不喜欢、没有帮助或失败不筛选，不更改A或重抽B。

- **工程诊断**：如装衣晚于启动、取衣早于完成、设备不存在，保留问题，不拿来冒充正常生活取舍。
- **生活/服务冲突**：如B让人在既定睡眠时装取、同人同时操作、错过原交付期限，保留为有意义的负面案例。
- **待另行确认/软偏好取舍**：超原移时、改变未授权的储水/制热、与舒适偏好有张力，不自动等同于不接受或物理失败。

同一对可以有多项发现，计数不可相加作总失败数。既有500组封存后果只保存原摘要与来源哈希，不重算、不按其成功与否生成画像。新增画像是新材料版本，未来正式采用时须单独管理，不能直接混用旧材料下的答卷。

重复性统计使用**生效规则与动作权限的结构签名**，忽略姓名/ID/年龄、措辞、日期、具体时间数值、温度/等待数值和重复同类空调数量。另列同态度同设备类别的组内比较、逐设备条件组合和去掉空调后的统计。共同条件应允许相同偏好，不靠同义改写、随机参数或强制每户唯一“去重”。这不证明真实偏好多样性或950户将有同等差异。

```bash
python -B -m benchmark.family_generation portrait \
  --input benchmark/family_generation/examples/energy_portrait/current_two.json --out /tmp/persona-two
python -B -m benchmark.family_generation verify /tmp/persona-two
python -B -m unittest benchmark.family_generation.test_persona_conditions \
  benchmark.family_generation.test_persona_checks benchmark.family_generation.test_device_persona \
  benchmark.family_generation.test_energy_portrait benchmark.family_generation.test_generation \
  benchmark.family_generation.test_connection
# 已有封存产物的本地影子核查；输出目录必须新建
python -B -m benchmark.family_generation.validate_device_personas \
  --artifacts /path/to/reference50-selection-v4-20261020 --out /tmp/persona-release-audit
python -B -m benchmark.family_generation verify /tmp/persona-release-audit
```

正式本地记录：[报告与自查](validation/device_persona_v3/READOUT.md)、[规则对应表](validation/device_persona_v3/RULE_MAPPING.md)、[两户阅读版](validation/device_persona_v3/PARTICIPANT_FAMILIES.md)、[500组检查](validation/device_persona_v3/AB_CHECKS500.json)。v1/v2报告保留为历史，不作为本版验收。此次不部署、不跑仿真、不启动1000户。
