# G 模拟案例接受记录

- 首次有限接受：`G_SIMULATION_ACCEPTANCE.json` SHA `6cb6be71498637c708a7c063fc5ae818559897e201fff2914bfcd76695cdef10`，绑定原始 pending bank `6d159eb9...`、contrast `24fbc34e...` 和 E 形展示 `6d21a81b...`，只允许离线模拟案例投影。
- 对温度主值范围出现两种并行处理指令时，F 曾将同一接受文件临时改为 `REVOKED_SUPERSEDED_PENDING_TEMPERATURE_PROJECTION_CORRECTION` 并通知根任务；B 同期暂停晋级。G pending 原字节未变，也没有依据临时状态发布。
- 根任务在 [`REVIEW_009_TEMPERATURE_DECISION.md`](../REVIEW_009_TEMPERATURE_DECISION.md) 确定保留全本户房间×24 小时等权均温，含未受控空调房间，并要求页面准确标注。F 恢复首次接受文件的原精确 SHA 后，进一步逐一复算 6,000 个展示分支的此项均温与范围标签，重新出具当前 `G_SIMULATION_ACCEPTANCE.json`。当前文件的新 SHA 为实际有效版本；前述首次 SHA 仅为历史。

该接受仅批准已审模拟案例转为离线验收状态与工程预览准备；不批准真人研究采集、舒适度实测解释或对偏好作推断。
