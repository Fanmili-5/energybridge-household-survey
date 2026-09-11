# 数据保存与研究用途

SQLite 为权威记录；JSON 文件是可恢复的兼容导出。默认部署位置为 `/var/lib/energybridge/jobs/state.sqlite3`，不同研究或工程试验应使用独立目录。

| 内容 | 保存位置 | 含义 |
|---|---|---|
| 独立家庭提交 | `household_submissions` 表 | 冻结原始回答、规范回答、题目快照、同意说明版本和哈希；不依赖计算成功 |
| 家庭派生资料 | intake 的 `household_record.derived_facts` | 例如已报告成员数、年龄段计数，带派生来源；缺失信息不补造 |
| 计算任务与阶段状态 | `jobs` 表 | 排队、运行、完成或失败，以及家庭 submission 链接 |
| EB 投影 | `documents` 中的 `household_config.json` | 实际进入 EB 的设备、日程、描述与明确研究默认值 |
| 仿真与规划资料 | `<case_id>/attempts/<序号>/` | 每次运行输入、EP 文件、规划记录和日志；文件组成随执行阶段而异 |
| 展示结果 | `documents` 中的 `outcome.json` | 原安排、调整安排、模拟结果及展示哈希 |
| 真人反馈 | `documents` 中的 `decision.json` | accept/reject、四项独立评分、小数分及可选原因 |
| SFT 候选 | `documents` 中的 `sft_candidate.json` | 输入与对应真人目标答案；并非已验收的训练发布版 |

`documents` 中通常还包括 `request.json`、`questionnaire_submission.json` 等复现资料，并映射到案例目录。独立 intake 尚无任务时，其资料已经保存在数据库，不要求案例目录存在。

## 数据含义

- `raw_answers` 是提交时的原始值，`normalized_answers/profile` 是按冻结题表规范化后的值。
- `answered`、`skipped`、`not_applicable` 分别表示已回答、未填写、不适用。选择“没有”与留空不同。
- 一位填答者代述成员资料，不等于每位成员独立回答；不推断填答者对应哪位成员。
- 地区、住房、收入等扩展信息用于研究留存。目前不据此切换天气文件、住宅或电价，也不全部放入 EB/SFT 提示词。
- EP 耗电、室温是统一研究情境的模拟结果，不是实测家庭负荷。
- 真人标签采用 `decision` 和 `score / comfort_score / energy_score / vpp_score`，不从评分反推接受与否，不把 EB 推理当真人原因。

## 导出

在源码目录运行，输出到持久目录或研究人员指定的安全位置：

```bash
.venv/bin/python realtime_pilot/export_household_records.py --data-dir /var/lib/energybridge/jobs --output /var/lib/energybridge/households-review.jsonl
.venv/bin/python realtime_pilot/export_candidates.py --data-dir /var/lib/energybridge/jobs --output /var/lib/energybridge/sft-review.jsonl
```

需用有读取数据库权限的账号执行。默认排除工程记录；只有检查格式时才使用 `--include-engineering`，该参数不会把测试数据转换为真人数据。

家庭导出包含尚未生成、计算失败和未评价的已保存提交；同一 intake 的多个案例通过 `case_ids` 关联，避免重复导出同一份提交。不同提交仍各自保留，不擅自合并。

SFT 导出只包含对应版本的已保存候选。扩展家庭资料可随记录携带，但是否进入训练输入需要另外选择与验证，不能认为附带了字段就已经训练使用。

## 身份与后续训练

`household_id` 当前基于浏览器会话，不是已验证的唯一真实家庭。换浏览器可能产生多个 ID，共用浏览器也可能混用同一 ID。研究正式划分训练/验证/测试前，应结合招募编号等方案处理重复家庭，不能只凭会话 ID 宣称家庭完全隔离。

所有导出保持 `training_release=false`。正式训练前需核对题表版本、家庭与案例关系、工程/真人来源、展示完整性、反馈缺失及家庭间数据划分。原始信息、转换值、模拟输出和真人评价应分别使用，不互相冒充。
