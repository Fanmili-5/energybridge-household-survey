# 数据保存与导出

答卷先保存，计算任务随后创建。计算失败或用户暂未评价时，已提交的家庭资料仍然保留。

## 服务器记录

SQLite 数据库 `state.sqlite3` 保存家庭提交、任务状态和案例文档。案例目录保存 JSON 镜像、EB 运行记录及 EnergyPlus 输出。

| 内容 | 表或文件 |
|---|---|
| 独立家庭提交 | `household_submissions` 表：原始答案、规范化答案、题目快照、提交时间与版本 |
| 排队和运行状态 | `jobs` 表：案例编号、状态及关联的家庭提交编号 |
| 答卷及家庭资料 | `questionnaire_submission.json`、`household_record.json`、`profile_components.json` |
| EB 输入 | `household_config.json`；每个运行分支的 `planner_household_en.json` |
| 仿真情境 | `request.json`、`simulation_environment.json`：日期、天气、住宅、VPP 和电价 |
| 两路运行 | `baseline/`、`proposal/` 中的计划、执行轨迹、电量和室温序列，以及 EP SQL、诊断文件 |
| 展示与反馈 | `outcome.json` 保存展示内容；`decision.json` 保存选择、评分和原因 |
| 来源校验 | 版本、文件哈希、模型请求与回复、执行日志 |

案例文档也保存在 `documents` 表中。独立家庭提交尚未生成任务时，不要求案例目录存在。不同执行阶段产生的文件不同；失败案例可能只有部分运行文件。

## 对外交付

`scripts/export_submitted_case.py` 从一次 SQLite 读取快照中关联答卷、方案和反馈，检查来源后生成：

| 文件 | 内容 |
|---|---|
| `questionnaire-answers.json` | 用户实际提交的答案及提交版本，不包含整份问卷模板 |
| `full-collected-record.json` | 合并后的家庭配置、情境、两份方案、展示结果和反馈；运行附件以哈希关联 |
| `cleaned-supervision.json` | 顶层只有 `input` 与 `output`，详见下表 |
| `verification.json` | 导出文件的哈希及来源核对结果 |

| 清洗字段 | 内容 |
|---|---|
| `input.household_profile` | 家庭事实、偏好与成员信息 |
| `input.event_condition` | 日期、季节、VPP 时段与价格单位 |
| `input.no_dr_plan` | 参与者看到的 No-DR 日常安排 |
| `input.agent_plan` | 参与者看到的 EB 调整安排 |
| `input.displayed_results` | 评分前实际展示的电量、成本、室温和任务完成信息 |
| `output` | `decision`、`score`、`comfort_score`、`energy_score`、`vpp_score`、`comment` |

清洗后使用英文语义字段和结果值，原因保留原文。问卷题干、全部选项、`response_status`、界面文案和内部控制字段不进入监督样本。这一步不生成 system prompt 或训练 messages。

```bash
.venv/bin/python scripts/export_submitted_case.py \
  --data-dir /path/to/jobs \
  --case-id CASE_ID \
  --output-dir /path/to/case-export
```

这是单案例导出命令，需要数据库读取权限。它会检查完整配对仿真、反馈和来源关联，但不会自动排除工程案例；正式整理数据时需根据原始采集标记筛选。

[查看授权公开的试填样例](../examples/real-test-20260914/README.md)。上述文件是从后台记录整理出的交付文件，服务器不只保存这几份 JSON。

## 数据处理约定

- 保留原始答案、缺失值和小数评分。拒绝、低分、用电增加、方案不变或回退都不是删样本的理由。
- `household_id` 来自浏览器会话，不能据此确认真实家庭唯一。批量整理时需要另行处理重复家庭。
- 天气、建筑及电量属于匹配情境下的模拟数据，不是该户实测负荷。电价目前使用原 EB 的归一化分时价格。
- EB 推理和模拟接受判断不能作为真人评价目标。目标只取最终保存的参与者反馈。
- 工程测试标记保留，不能通过导出变成正式采集记录。后续去重、数据集划分和训练由接收数据的项目负责。

`export_household_records.py` 可导出所有已保存家庭，包括尚未计算或评价的提交；`export_candidates.py` 与 `sft_candidate.json` 用于历史格式兼容和来源检查。它们默认排除工程记录，格式与上述 `cleaned-supervision.json` 不同。
