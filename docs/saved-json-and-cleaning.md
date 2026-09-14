# 实际保存与第一步清洗

已用线上数据库核对示例案例 `f5e211505dfa1f1c4822cee8285f12c0` 的五份核心文档哈希，均与导出记录一致。该案例是真人试填、真实 EB/API 与 EP 运行；系统仍将其标为工程测试。

| 阶段 | 后台 JSON 记录 |
|---|---|
| 用户提交 | `questionnaire_submission.json`、`household_record.json`、`profile_components.json`：原始答案、规范化答案、成员资料及补充信息 |
| 仿真输入 | `household_config.json`、`request.json`、`simulation_environment.json`：设备参数、日程、日期、天气站、建筑原型、VPP 和价格口径 |
| 两路运行 | `baseline/` 和 `proposal/` 下的 `native_result.json`、`actuator_trace.json`、`ep_metric_series.json`、`service_evidence.json`：EB 决策、执行轨迹、逐时电量和温度、设备状态 |
| 结果和反馈 | `outcome.json`：两份方案及冻结展示内容；`decision.json`：真人选择、四项小数评分和原因 |
| 追溯 | `job.json`、`date_validation.json`、运行清单与哈希、模型调用的 `request.json` / `response.json` 等 |

新版本还保存每路 `planner_household_en.json`。这份历史试填早于该改动，原运行目录里没有该文件。历史兼容的 `sft_candidate.json` 仍在后台存档，本次交付不导出其中的提示词或 messages。EP 还会保存 SQL 和诊断文件，不全是 JSON。

对外交付展示两份：

1. `full-collected-record.json`：从上述真实记录中合并提取业务字段，包含实际答案、该户配置、情境、两份结果、冻结展示和真人反馈。不是整库转储；逐时 EP 与模型调用原文件通过哈希关联，不全部嵌入。
2. `cleaned-supervision.json`：第一步清洗结果。`input` 放家庭答案和用户实际看到的对比；`target` 保留真人选择、四项评分及原因；`auxiliary` 保存补充调查信息和仿真情境；`provenance` 保存来源和清洗信息。不制作 system prompt 或训练 messages。

清洗核对来源、保留未知值和小数评分、去掉问卷模板与重复展示文案，将图表值转成有单位的字段。统计窗口与展示窗口分别保留，跨日时刻仍可大于 24。相对成本不改写成人民币。英文文本是当前确定性转换结果，真人原因保留原文。

不因为拒绝、回退、不省电或低评分而删除样本。工程样本仍不能直接作为正式训练发布；后续还需全量去重、按家庭划分集合及训练审核。未识别的页面文案报错待映射，不静默丢弃。
