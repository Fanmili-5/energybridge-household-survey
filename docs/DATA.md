# 数据交付口径

用户填写后的问卷 JSON 只包含实际提交答案及身份关联、时间、问卷版本；不嵌入整份问卷定义或全部选项。原始值保持不变，未填写项不补答案。

完整案例另附该户配置、仿真情境、两份结果、实际展示和真人反馈，不生成 SFT 提示词或训练对话。

[查看真实答卷和运行结果](../examples/real-test-20260914/README.md)。使用 `scripts/export_submitted_case.py` 导出；以下旧 `export_household_records.py` / `export_candidates.py` 是后台完整审计及历史候选工具，不是当前对外交付格式。后台不可变记录及快照继续用于来源校验。

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
| 真人反馈 | `documents` 中的 `decision.json` | accept/reject、四项独立评分、小数分及必填的简短原因 |
| SFT 候选 | `documents` 中的 `sft_candidate.json` | 输入与对应真人目标答案；并非已验收的训练发布版 |

`documents` 中通常还包括 `request.json`、`questionnaire_submission.json` 等复现资料，并映射到案例目录。独立 intake 尚无任务时，其资料已经保存在数据库，不要求案例目录存在。

## 数据含义

- `raw_answers` 是提交时的原始值，`normalized_answers/profile` 是按冻结题表规范化后的值。
- `answered`、`skipped`、`not_applicable` 分别表示已回答、未填写、不适用。选择“没有”与留空不同。
- 一位填答者代述成员资料，不等于每位成员独立回答；不推断填答者对应哪位成员。
- 地区、房型、面积和楼层用于匹配天气与等效研究住宅，并进入冻结的环境记录及 EB 上下文；收入、设备数量等额外研究信息原样留存，不自动改变物理模型或电价。
- EP 耗电、室温是匹配研究情境的模拟结果，不是实测家庭负荷。典型气象年、住宅近似及统一设备参数随记录保存。
- 真人标签采用 `decision` 和 `score / comfort_score / energy_score / vpp_score`，不从评分反推接受与否，不把 EB 推理当真人原因。
- 当前新案例要求参与者填写简短原因；原文作为 `comment` 保存并进入监督目标。系统不补写、归纳或改写理由。
- VPP 开始时刻从 17:00、18:00、19:00 中抽取，持续时间从 1、2 小时中抽取。情境先于反馈冻结，不根据接受／拒绝或模拟结果重新抽样。
- 当前电价是原 EB 天津归一化分时价格这一统一研究条件。每次运行保存电价 ID、单位、来源和 SHA-256；未来地区电价须发布新版本，不覆盖历史记录。

## 导出

在源码目录运行，输出到持久目录或研究人员指定的安全位置：

```bash
.venv/bin/python realtime_pilot/export_household_records.py --data-dir /var/lib/energybridge/jobs --output /var/lib/energybridge/households-review.jsonl
.venv/bin/python realtime_pilot/export_candidates.py --data-dir /var/lib/energybridge/jobs --output /var/lib/energybridge/sft-review.jsonl
```

需用有读取数据库权限的账号执行。默认排除工程记录；只有检查格式时才使用 `--include-engineering`，该参数不会把测试数据转换为真人数据。

家庭导出包含尚未生成、计算失败和未评价的已保存提交；同一 intake 的多个案例通过 `case_ids` 关联，避免重复导出同一份提交。不同提交仍各自保留，不擅自合并。

监督样本导出只包含对应版本的已保存候选，并从同一 SQLite 快照核对题表、家庭记录、方案、展示及真人反馈；不一致时拒绝输出。排除原因和版本范围写入 manifest，旧版记录仍留在原库。扩展家庭资料可随记录携带，但是否进入训练输入需要另外选择与验证，不能认为附带了字段就已经训练使用。

## 交付边界与身份

`household_id` 当前基于浏览器会话，不是已验证的唯一真实家庭。换浏览器可能产生多个 ID，共用浏览器也可能混用同一 ID。研究正式划分训练/验证/测试前，应结合招募编号等方案处理重复家庭，不能只凭会话 ID 宣称家庭完全隔离。

所有导出保持 `training_release=false`：表示交付的是已核验的数据，不宣称下游已完成训练或评测。训练、独立评测、EB 评价适配器不在采集项目的工作范围内。数据交付仍包含来源、版本和会话身份范围说明，便于接收者正确使用。

EB 内部请求、回复、原生决策和执行轨迹保存在私有任务文件中用于追溯，不能当作真人理由或自动加入 assistant 目标。真正的目标标签只来自最终保存的真人回答。当前脚本不自动划分训练集／测试集。

完整数据形状可参考 [当前工程 SFT 候选样例](examples/engineering_sft_candidate.jsonl)；它经过真实两次 EnergyPlus，但规划与评价均为工程测试值，`target_source=engineering_test` 且 `training_release=false`，不是真人训练样本。
