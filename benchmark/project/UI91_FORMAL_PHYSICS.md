# 冻结50户新A/B与UI91正式采集

这是提案版之后的新信息版本，原A46与已选collection-selection-v4 B不变。原提案包、旧B57包、旧身份/查看/草稿/答卷均独立保留；旧答案不转换成看过新仿真结果的答案。1000户及950户扩展未执行。

## 输入、运行与边界

1. `reference_collection_physics`核对冻结500组、原全年A和原家庭设备/住房包，导出全部50户×10日期。车辆初态只从原全年A账本积分，不读取旧B结果。
2. 同房多台空调的参考门控与适用边界见[具体方法](../housing_simulation/MULTI_AC_METHOD.md)。全部设备、原房间和每台请求保留，不通过修改A或换B解决兼容问题。
3. `reference_physics_batch`按明示历史天数编译，固定5分钟物理步长、9日后续期、参考换气与典型天气。历史不足112天时登记原有实际天数，不补造日程。`reference_physics_execute`采用独立进程、受限并发，每臂一次引擎尝试；中断恢复只读取已完成输出，失败不重试。IDF、天气、引擎、SQL、轨迹和源计划均绑定哈希。
4. `reference_physics_results`保留完整500行。服务未完成、舒适范围超出、回路容量超限、VPP未达标和恢复残差保留为结果；读取/单位/能量闭合/通知前轨迹等完整性错误保留为诊断，正式资料中实际后果保持未知。计算完成不等于全部检查通过。

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

## 正式资料与回答含义

`reference_physical_release`派生新的v2题包，逐题验证原A/B语义哈希，保留计划、变化、背景、日期和住房设备。原提案题包保持原字节。新题包附上本题新物理结果、状态和绑定；未知仍为null。原先的v69回答协议和量表保持，视觉身份沿用UI91立体剖面及并排比较，版本明确区分。

问卷显示当日住宅用电、情境单价电费、完整房间温度范围、按次日08:00截断的运行/取出计数、最近出发电量和固定18:00—19:00的响应。共享住宅用电不伪称目标户实测分表；全天温度不等于个人舒适；无独立热水交付核验时明确标为未知；后续费用无完整单价覆盖时不补零。回路超限只表示模拟平均功率超过参考容量，未模拟跳闸。

受访者站在给定家庭的立场，判断是否原样接受B、四项评分和理由。物理/工程状态、VPP达标与接受标签分开。四项初始为空，不由模型预填。

## 发布与验证记录

全量汇总、原始凭据哈希、未达标/失败计数和自查结论写入`FULL500_PHYSICS_VALIDATION.json`。这不是家庭实测标定声明，也不是1000户验收。受控SQL、题包、身份和回答不进入公共仓库。

新正式服务采用新发布指纹、新cohort和独立数据库。切换前备份旧库与恢复密钥；旧服务和旧发布内容保留。先在临时库完成真实HTTP/恢复/版本/必填检查，再在main检查通过后切换入口。线上检查只读取健康、资产和入口，不生成代理正式答卷。
