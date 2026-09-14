# 原始记录与清洗文件

服务器按阶段保存答卷、家庭配置、仿真结果和反馈，SQLite 为主要存储。导出时再合并成一条案例，并提取 `input` / `output`。完整字段及命令见[数据保存与导出](DATA.md)。

```text
服务器记录
  答卷 + 家庭配置 + 情境 + 两路运行 + 展示 + 真人反馈
    ↓ export_submitted_case.py
  full-collected-record.json     合并案例，保留来源关联
    ↓ clean_collected_case.py（由导出脚本调用）
  cleaned-supervision.json       input / output
```

完整运行轨迹、模型请求和 EP 原文件留在后台，不全部嵌入清洗文件。来源核对结果保存在 `verification.json`。

[公开试填样例](../examples/real-test-20260914/README.md)来自真实填写及 EB/EP 运行，当时按工程测试保存。该案例早于英文输入转换功能，因此原运行目录没有 `planner_household_en.json`；样例中的英文清洗结果是后续转换所得，历史输入未改写。
