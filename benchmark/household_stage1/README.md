# 八国家庭生成第一步：调查支持的受控情境

当前版本V9：八国各125户，共1000户；每户必须配备空调，且空调必须纳入4—6类可控电器。当前指针和数据内容摘要见[CURRENT.json](CURRENT.json)，验收证据见[VALIDATION.json](VALIDATION.json)。本批只验收家庭与结构化服务输入，实际A/B问题、物理结果和真人答案均为0；10000是每户十题的覆盖蓝图槽位。

## 数据来源

下列是筛选后的候选记录数，还需逐角色检查，不是原调查样本总量。各国最终均选125个不同源家庭。中国原件为项目已有CRECS2012文件。ENABLE.EU的2019是发布年，不是个人访问年。

| 国家 | 调查来源 | 候选记录 | 实际使用与限制 |
|---|---|---:|---|
| CN | [CRECS 2012 中国家庭能源消费调查](https://crecs.ruc.edu.cn/jj/gyCRECS/index.htm) | 505 | 逐人成员、亲属、出生年、就业、面积档、设备和通常在家/居家工作人数 |
| US | [EIA Residential Energy Consumption Survey 2020 v7](https://www.eia.gov/consumption/residential/data/2020/index.php?view=microdata) | 14,404 | 年龄人数、受访者、住房、设备、工作日在家天数；源调查插补状态保留 |
| GB | [ENABLE.EU 1.0, released 2019-10-31](https://zenodo.org/records/3523916) | 750 | 性别年龄组人数、受访者出生年/就业、住房和设备；在家字段未确认 |
| ES | [ENABLE.EU 1.0, released 2019-10-31](https://zenodo.org/records/3523916) | 615 | 同体系家庭字段；C4G是个人供暖语境而非整户天数 |
| DE | [ENABLE.EU 1.0, released 2019-10-31](https://zenodo.org/records/3523916) | 539 | 同体系家庭字段；个人供暖语境在家约束 |
| IN | [India Residential Energy Survey 2020](https://www.ceew.in/sites/default/files/CEEW-IRES-Design-and-data-quality-4Oct20.pdf) | 291 | 年龄组、学生人数、设备、每周洗衣机使用次数和可用热水容量 |
| MX | [INEGI ENASIC 2022](https://www.inegi.org.mx/programas/enasic/2022/default.html) | 543 | 逐人成员年龄/就业/照护/工作量；住房参考另用ENIGH2024跨户匹配 |
| AU | [Consumer Energy Report Card, June2025 labelled raw workbook](https://energyconsumersaustralia.com.au/our-work/surveys/energy-consumer-survey-data) | 1,000 | 成人儿童、就业、按日在家/WFH、设备与停车；功能使用不等于产权 |

墨西哥住房类型另用[ENIGH2024](https://www.inegi.org.mx/programas/enigh/nc/2024/default.html)按人数、房间数及洗衣支持条件匹配，明确为跨户参考。来源和原件哈希见[SOURCES.json](SOURCES.json)，原件、逐户卡与真人记录不随Git发布。

## 实际生成方法

1. 按问卷和字典统一字段，保留同户关系、源调查插补、缺失及年份范围。中国代际年龄等需核实或不适配的56户隔离，不猜改原答复。
2. 按固定八国×六类配额进行确定性规则选户。固定哈希排序、来源支持优先与可行性筛选共同作用；同一源户不重复使用，不按后续B成功或真人回答选户。这是实验配额选择，不是总体概率抽样。
3. 六类角色与态度按EB定义赋值，全球A/B/C/D/E/F配额166/198/125/151/156/204。家庭背景不等于天然角色标签，具体时刻和未测身份不冒充同户实测。
4. 规则生成七天参考工作、通勤、上学、餐饮、洗浴、照护和可用手动操作窗口，保留已有工作量、托幼时长、在家和洗衣次数约束。C/D按结构块与设备支持配成125对，不宣称其他背景完全相同或因果角色效应。
5. 混合整数规划分配控制集合：每户必须含AC，再选其他3—5类；4/5/6类共333/333/334户。每国覆盖16种合法集合、50种合法二元状态，每个国家×类别均覆盖六功能；F还须EV，C/D匹配对控制集合相同。整数规划用于电器组合，生活作息由规则构造。
6. 独立原件和生活/控制/服务检查、反例测试及字节重放，冻结原件、代码、入选户、配额与结果。按源户和C/D匹配组进行后续数据划分。

## 空调是必备且必控

[required_controls.py](required_controls.py)是当前服务器构造器实际使用的约束，与独立原件验收分开。不能把“有空调但不控制”计为满足本要求；每户蓝图也包含空调曝光。调查没有或未确认空调时，明确作为实验增配，原始设备答复保持不变；安装与IDF可行性仍由下一阶段检查。六类控制外的背景电器不计覆盖。空调必控不意味着每道题都调整空调，也不意味着所有季节强制制冷；须有实际热服务需求才实例化相应题目。

V8有937户配备空调、915户纳入控制。V9保留同一1000户、角色、成员、住房和生活日历，重新分配控制集合后，配备及控制均为1000户。原22组合中有6种不含AC，因此本版本的合法目标为16种，不能沿用22种或60个二元状态的旧验收。旧V8冻结记录保留，新增要求单独产生V9。

## 验收与复现边界

当前1000户已独立核对，40/40故障被检出，包括旧版有效但不控制AC的家庭；同一基线和冻结控制配置跨进程重新生成的文件逐字节相同。调查事实、实验设定和原始资料的访问条件分开登记。来源选择、日历规则与控制配置的可复现性不证明全球代表性、跨文化态度有效性或人类生活自然程度。

公开环境只需Python标准库：

```bash
python -B -m benchmark.household_stage1.verify_publication
python -B -m unittest benchmark.household_stage1.test_required_controls -v
```

授权持有冻结家庭文件时，可额外核验文件身份、配额及空调控制契约：

```bash
python -B -m benchmark.household_stage1.verify_publication --households /authorized/household_cases.jsonl
```

公开核验器不重跑原始调查解码和完整服务器生成链；这批原件复读与全量生活验收证据由VALIDATION.json绑定，完整服务器依赖另行冻结。旧[family_generation](../family_generation/)六类合成画像v3保留其自己的来源与模式，不把Copula画像算法说成这1000户源家庭的选取方法，也不声称用六条合成模板可重建本批1000户。

下一阶段：逐户IDF/安装/气象和价格绑定、A/B双方的生活合理性及同版本仿真、问卷小样理解与真人质控。本次GitHub更新不修改既有50户线上资料或问卷数据库。
