# 一份真实提交的数据

2026-09-14，项目本人在线填写并提交反馈，已授权公开。

- [用户填写后的问卷 JSON](questionnaire-answers.json)：仅含该用户实际提交的答案、提交时间和问卷版本，不含备选项、问卷模板或提示词。
- [问卷＋运行结果＋反馈 JSON](full-collected-record.json)：增加该户 EB 配置、仿真情境、两份方案、实际展示结果和真人反馈。
- [来源校验与文件哈希](verification.json)。

真实反馈为同意；四项评分为 4.2、4.3、2.9、4.2，原因保留原文。EB 实际调用 gpt-4o-mini，EP 实际运行。

历史记录的 `synthetic_engineering_test` 标记保留；这是真人试填，但当时系统按工程测试保存，不冒充正式采集数据。此记录产生于英文 EB 输入转换上线前，其历史输入未事后改写。

这里是从已保存记录中提取的交付数据，不是整个数据库的转储。问卷定义及后台校验快照独立保留，使用版本和哈希追溯；EP 原文件通过来源哈希关联，不嵌入 JSON。SFT 提示词及训练对话由后续负责训练的同学构造。

从数据库导出一份已完成且有反馈的答卷：

```bash
.venv/bin/python scripts/export_submitted_case.py \
  --data-dir /path/to/jobs \
  --case-id CASE_ID \
  --output-dir /path/to/case-export
```
