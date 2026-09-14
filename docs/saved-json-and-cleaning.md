# 实际保存与第一步清洗

已用线上数据库核对示例案例 `f5e211505dfa1f1c4822cee8285f12c0` 的五份核心文档哈希，均与导出记录一致。该案例是真人试填、真实 EB/API 与 EP 运行；系统仍将其标为工程测试。

服务器以 `state.sqlite3` 为权威存储，同时把每个任务镜像成可恢复的 JSON 和运行文件。它不是只保存最终展示的两份 JSON。

| 阶段 | 服务器实际保存的 JSON 记录 |
|---|---|
| 用户提交 | `questionnaire_submission.json`、`household_record.json`、`profile_components.json`：原始答案、规范化答案、成员资料及补充信息 |
| 仿真输入 | `household_config.json`、`request.json`、`simulation_environment.json`：设备参数、日程、日期、天气站、建筑原型、VPP 和价格口径 |
| 两路运行 | `baseline/` 和 `proposal/` 下的 `native_result.json`、`actuator_trace.json`、`ep_metric_series.json`、`service_evidence.json`：EB 决策、执行轨迹、逐时电量和温度、设备状态 |
| 结果和反馈 | `outcome.json`：两份方案及冻结展示内容；`decision.json`：真人选择、四项小数评分和原因 |
| 追溯 | `job.json`、`date_validation.json`、运行清单与哈希、模型调用的 `request.json` / `response.json` 等 |

新版本还保存每路 `planner_household_en.json`。这份历史试填早于该改动，原运行目录里没有该文件。历史兼容的 `sft_candidate.json` 仍在后台存档，本次交付不导出其中的提示词或 messages。EP 还会保存 SQL 和诊断文件，不全是 JSON。

从这些服务器原始记录中生成两份**初步整理／清洗结果**，供检查字段和交给后续数据处理：

1. `full-collected-record.json`：第一步是合并整理。从服务器多份原始记录中提取业务字段，合成一条完整案例，包含实际答案、该户配置、情境、两份方案与结果、冻结展示和真人反馈。它不是服务器原文件或整库转储；逐时 EP、模型调用和诊断文件通过哈希关联，不全部嵌入。
2. `cleaned-supervision.json`：第二步是初步监督字段清洗，文件顶层只保留 `input` 和 `output`。`input` 放家庭填写的画像与偏好、参与者已知的事件条件、No-DR 计划、EB Agent 计划，以及评分前实际看到的 EP 用电、费用、室温和任务完成结果；`output` 保留真人选择、四项评分及原因。清洗结果使用英文语义字段与 `day_1 19:40` 形式的明确时间，不放问卷题干、作答状态、界面文案、内部 `signal`、未向参与者展示的通知时刻、来源编号或审计元数据。完整 EP 轨迹和服务运行记录仍留在完整采集记录；文件哈希与导出校验留在单独的 `verification.json`。这一步不制作 system prompt 或训练 messages。

清洗核对来源、保留未知值和小数评分、去掉问卷题干、问卷模板与重复展示文案。计划中的跨日时刻仍可大于 24。英文结果值是当前确定性转换结果，真人原因保留原文。

不因为拒绝、回退、不省电或低评分而删除样本。工程样本仍不能直接作为正式训练发布；后续还需全量去重、按家庭划分集合及训练审核。未识别的页面文案报错待映射，不静默丢弃。
