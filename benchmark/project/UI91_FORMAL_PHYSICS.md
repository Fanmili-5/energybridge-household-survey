# 冻结50户新A/B与UI91正式采集

当前线上入口临时切为[试填测试版](https://47.85.194.154/household50-current/)，标题注明“测试版·含示例数据”。50户500题沿用UI91及0—5整数选项；其中56题用临时空调示例覆盖展示，系填写测试数值，不是新增仿真或可信物理预测，不用于科研结论或模型训练。原始A/B、原生结果和旧答卷均保留，测试答卷独立保存。范围、规则和上线核验见[测试发布清单](../releases/reference50-v4-ui91-trial/MANIFEST.json)。1000户仍暂缓。

这是提案版之后的新信息版本，原A46与已选collection-selection-v4 B不变。原提案包、旧B57包、旧身份/查看/草稿/答卷均独立保留；旧答案不转换成看过新仿真结果的答案。1000户及950户扩展未执行。

## 输入、运行与边界

1. `reference_collection_physics`核对冻结500组、原全年A和原家庭设备/住房包，导出全部50户×10日期。车辆初态只从原全年A账本积分，不读取旧B结果。
2. 同房多台空调的参考门控与适用边界见[具体方法](../housing_simulation/MULTI_AC_METHOD.md)。全部设备、原房间和每台请求保留，不通过修改A或换B解决兼容问题。
3. `reference_physics_batch`按明示历史天数编译，固定5分钟物理步长、9日后续期、参考换气与典型天气。历史不足112天时登记原有实际天数，不补造日程。`reference_physics_execute`采用独立进程、受限并发，每臂一次引擎尝试；中断恢复只读取已完成输出，失败不重试。IDF、天气、引擎、SQL、轨迹和源计划均绑定哈希。
4. `reference_physics_results`保留完整500行。服务未完成、舒适范围超出、回路容量超限、VPP未达标和恢复残差保留为结果；读取/单位/能量闭合/通知前轨迹等完整性错误保留为诊断，正式资料中实际后果保持未知。正常退出也不等于内部迭代求解通过：逐臂读取已封存的原生错误日志，出现明确湿球求解不收敛或Severe/Fatal错误时，整组后果不进入正式展示。原日志、SQL及旧诊断回读保留，不重跑、不换B，也不把未知记为无响应或未达标。

受控执行命令：

```sh
python -B -m benchmark.project.reference_collection_physics \
  --collection /controlled/frozen-selection \
  --stage /controlled/original-physics-inputs \
  --original-a /controlled/original-annual-A --out /controlled/new-inputs
python -B -m benchmark.project.reference_physics_batch \
  --collection /controlled/frozen-selection --exported /controlled/new-inputs \
  --out /controlled/full500 --engine /pinned/energyplus \
  --engine-sha256 ENGINE_SHA256 --workers 6
python -B -m benchmark.project.reference_physical_release \
  --proposal-release /controlled/sealed-UI91-proposals \
  --results /controlled/full500/results --out /controlled/new-formal-release
python -B benchmark/collector/test_protocol.py --release /controlled/new-formal-release
```

如调度器中断，已绑定的未封存运行可用同一批次的`--resume`恢复；不改输入，也不对失败臂另开一次引擎尝试。最终执行凭据及已完成臂的哈希必须通过核验。

旧回读器曾以单位是否为J区分累加/平均，因而把原生累计水量m³误作均值。本版按原生SQL的`ReportDataDictionary.Type`聚合Sum与Avg。`reference_physics_readback`可从旧运行派生修正的TRACE/RESULT，原运行不变、SQL逐字节相同，不新增引擎尝试；电量与室温数值不变。正式绑定采用修正后的回读版本，编译源版本与回读源版本分别保留，不能冒称历史编译使用了后来的回读代码。

### 数值可用性与警告

[EnergyPlus24.1原生湿空气源码](https://github.com/NatLabRockies/EnergyPlus/blob/v24.1.0/src/EnergyPlus/Psychrometrics.cc#L347-L549)在湿球迭代中调用饱和压力函数，并在达到迭代上限仍未收敛时另报不收敛；饱和压力函数会对超范围试探值作边界处理。因而范围警告中的试探值不能当成实际房间温度，也不能把所有警告一律等同物理失败。本版保留全部警告，但将明确不收敛作为后果准入门槛。

原生日志复核先识别22组湿球不收敛和7组起始天气Severe错误，合计58臂、29组。天气错误来自乌苏CSWD原文件的113%相对湿度，并非下载失败。单独调用官方24.1原生湿球函数，以日志中的温度、含湿量和压力为输入，无需家庭或A/B模型即可复现代表案例的不收敛；这定位了一个可独立触发的数值问题，但不证明22组所有调用的具体机制均已查明。

进一步对照[原生天气读取源码](https://github.com/NatLabRockies/EnergyPlus/blob/v24.1.0/src/EnergyPlus/WeatherManager.cc#L2230-L2282)：起始天气将RH超过110%报Severe（消息文本写0—100%），后续日通常只累计越界计数，不能只按Severe日志判断源天气可用。因此新增`reference_weather_audit`，按两臂实际编译RunPeriod的月日范围，逐条检查整段前史、主日及恢复期的原EPW相对湿度，绑定天气哈希、起止日期、越界行及数值；只对RH<0或110<RH<999拒绝数值准入，明确保留原生110%容差与999缺测哨兵语义，不将101%一律等同严重错误。本检查只覆盖原生RH输入域，不宣称天气已全面校准。

该检查共识别23组使用区间内有越界RH，其中7组已被Severe捕获，另外16组此前未被日志门槛捕获。与22组不收敛合计45组后果未知；其余455组通过本版数值/完整性准入。原生日志、SQL、天气、早期回读和此前471/29题包均保留；本轮只重绑定资料，不重跑引擎、不改A/B、不换天气或样本。无论问题出现在前史、主日或恢复期，均保守地将该配对后果标为未知，不断言所有时刻均错误。这45组仍在500题中，不把输入或求解问题写成B在生活上失败。准入规则在上线前复核中补齐，不是事前登记的样本配比或成败筛选。

## 正式资料与回答含义

`reference_physical_release`派生新的v2题包，逐题验证原A/B语义哈希，保留计划、变化、背景、日期和住房设备。原提案题包保持原字节。新题包附上本题新物理结果、状态和绑定；未知仍为null。原先的v69回答协议和量表保持，视觉身份沿用UI91立体剖面及并排比较，版本明确区分。

问卷显示当日住宅用电、情境单价电费、完整房间温度范围、按次日08:00截断的运行/取出计数、最近出发电量和固定18:00—19:00的响应。共享住宅用电不伪称目标户实测分表；全天温度不等于个人舒适；无独立热水交付核验时明确标为未知；后续费用无完整单价覆盖时不补零。回路超限只表示模拟平均功率超过参考容量，未模拟跳闸。

对原生混合水模型，本版回读`Water Use Equipment Total Volume`与`Mixed Water Temperature`：先验证累计体积的Sum聚合，再列住宅总出水量、10分钟报告体积加权温度及有流量时的最低10分钟均温。计划用水量按原请求与当天窗口的交叠计，不改需求。字段含义依据[EnergyPlus24.1水系统文档](https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-water-systems.html)。不把混合水等同纯热水，不作逐人分摊，不从报告均温推断瞬时最低温，也不预设“所有洗澡都满意”。通道或累计类型未核实时保留未知。

受访者站在给定家庭的立场，判断是否原样接受B、四项评分和理由。物理/工程状态、VPP达标与接受标签分开。四项初始为空，不由模型预填。

## 发布与验证记录

全量汇总、原始凭据哈希、未达标/失败计数和自查结论写入`FULL500_PHYSICS_VALIDATION.json`。这不是家庭实测标定声明，也不是1000户验收。受控SQL、题包、身份和回答不进入公共仓库。

新正式服务采用新发布指纹、新cohort和独立数据库。切换前备份旧库与恢复密钥；旧服务和旧发布内容保留。先在临时库完成真实HTTP/恢复/版本/必填检查，再在main检查通过后切换入口。线上检查只读取健康、资产和入口，不生成代理正式答卷。


## UI91展示整理（clean.v2）

洗衣与烘干按各自程序、时段分开展示。源资料以同一个laundry标识归集两种程序，不据此声称是洗烘一体机；每张卡仍绑定原asset_id和程序类型。家庭设备清单和立体房间图也分别显示洗衣机、烘干机。装载、取出操作不再进入问卷，工程约束诊断和审计提示留在原题数据中。程序完成数、室温、电量、电费、出发电量、热水与VPP结果仍取同一题绑定的仿真记录。

删除“查看完整资料”入口、逐卡解释小字和重复评分说明。保留一处“仿真估算”、统计时段和电费不含补偿的简短标识；未知仍显示未知。评分字段与必填规则保留，四项均改为0—5的方块单选，初始不选中，不提供手动输入。0分是有效答案，与未作答区分。前端、后端正式答卷和草稿校验均只接受0、1、2、3、4、5。原版小数评分按原发布保留，不取整。晚餐、洗澡与调整边界直接显示在家庭资料中。

从已封存的正式题包派生新版展示，不修改原发布包：

```sh
python -B -m benchmark.project.reference_presentation_release \
  --parent-release /controlled/current-UI91-release \
  --out /controlled/UI91-clean-v2
```

该命令逐字节核验500题和50户资料不变，不生成A/B、不运行EnergyPlus，也不复制任何旧答卷。DISPLAY_MODELS与发布指纹随展示变化重新封存，完整排程不再作为可见输入。旧答卷仍属于原展示版本，不能冒称受访者看过精简版。线上状态以当前发布指针为准，构建命令本身不会切换服务。
