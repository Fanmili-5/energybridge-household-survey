# 中文答案转为英文 EB 输入

参与者使用中文填写。后台保留原始答案，按固定词表生成英文 EB 输入，不调用翻译 API。

| 信息 | 转换方式 |
|---|---|
| 家庭和成员选项 | 选项编码映射为英文含义 |
| 时刻、温度、时长和设备参数 | 保留数值及单位 |
| 城市 | 保留原文，同时提供匹配气象站的英文名称 |
| 日程和环境说明 | 使用英文任务窗口与模型假设 |
| 最终评价 | 在规划完成后保存，原因保留原文 |

例如 `confirm_required` 表示 `Ask first and adjust only after explicit agreement each time`。“3 天或更早”对应 `3 days or more`，保留原选项的范围含义。

`household_config.json` 保存家庭配置。每个运行分支另存 `planner_household_en.json`，附源配置哈希、翻译版本和词表哈希。历史记录不因词表更新而重写。

相关代码：

- [planner_language.py](../realtime_pilot/planner_language.py)：生成英文规划输入。
- [planner_english_catalog.json](../realtime_pilot/planner_english_catalog.json)：中英字段和选项映射。
- [clean_collected_case.py](../scripts/clean_collected_case.py)：提取监督样本中的英文语义字段。

修改题目或选项时需同步词表。当前映射不处理任意自由文本翻译；未填写的字段不补答案。
