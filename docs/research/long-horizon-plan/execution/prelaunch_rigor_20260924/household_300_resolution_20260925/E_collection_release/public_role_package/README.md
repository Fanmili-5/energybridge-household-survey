# 300 个公开候选合成角色

本目录只有固定角色画像与问卷映射，状态为 `PUBLIC_CANDIDATE_FIXED_ROLES_ONLY_NOT_COLLECTION_READY`。角色均为合成条件，不代表 300 位受访者；这里没有十天验收结果或真人反馈。

`PUBLIC_MANIFEST.json` 给出逐表行数、SHA-256 和源版本指纹。`households_300.csv` 含角色卡、城市、住房原型 `source_catalog_key`、天气代理站 `weather_station_key`、模型及天气内容 SHA；`provenance_300.csv` 含字段来源 ID 与证据标签。模型与天气文件须由有权限的研究者在本地按来源和指纹解析。此包不包含 DeST/CSWD 原始资产、IDF/EPW 文件、源模型内部热区名称、运行日志或本机路径。

使用前先读 `PUBLIC_MANIFEST.json` 与上层 `DATA_DICTIONARY.md`、`DATA_MANUFACTURING_PATH.md`。问卷答案是合成设定及代理映射；`participant_feedback_status=NOT_COLLECTED`，`simulation_result_status=NOT_EXPORTED_PENDING_D_ACCEPTANCE`。任何真人收集须等待最终离线案例库和独立验收。
