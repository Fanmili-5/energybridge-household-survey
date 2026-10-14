# 文档目录

## 当前版本入口

**1000户V27进展（2026-10-14）**：[当前状态与入口](household1000/README.md)。原50户已完成六类、政策到作息/服务/A/B/IDF、学校物理及原前端新版验收；1000户研究配比已冻结。真实偏好比例、真人有效性与正式benchmark没有得到验证。下一步验收全量静态生产，1000户全量EP继续关闭。

**原50户问卷线上改版**：[2026-10-14发布与核验](../deploy/questionnaire_revision_20261014/RELEASE.md)，使用V27任务、增加本人年龄/性别、保留影响与简略动作；工程试填范围。

下面是原自报问卷和旧版工程记录，按各自版本判读。

## 项目使用

| 文档 | 内容 |
|---|---|
| [问卷内容](QUESTIONNAIRE.md) | 收集哪些信息、如何使用 |
| [数据保存与导出](DATA.md) | 后台记录、交付文件和导出命令 |
| [案例编号与问题反馈](CASE_REPORTS.md) | 选填昵称、问题报告、后台核查和失败轨迹导出 |
| [原始记录与清洗文件](saved-json-and-cleaning.md) | 两步整理之间的关系 |
| [英文规划输入](planner-language.md) | 中文答案到 EB 字段的映射 |
| [天气与住宅](../simulation_resources/README.md) | 地点、住宅和日期选择 |
| [部署与维护](DEPLOYMENT.md) | 环境、配置、队列、更新和备份 |
| [验证记录](AUDIT.md) | 已检查的内容和未解决的测试问题 |
| [公开试填样例](../examples/real-test-20260914/README.md) | 实际收集和清洗后的 JSON |

## 开发记录

以下文件保留当时的设计讨论、测试结果和修复依据。其中的路径、版本及测试数量可能已变化，使用项目请先阅读上面的文档。

### 规划与设备接口

- [电器到 EnergyPlus 的连接：上游核对与候选修复](upstream-binding-review/README.md)
- [EB 原生流程重新审计 — v3.1](native-loop-collection-audit-20260912.md)
- [恢复原 EB 的规划检查与证据复核](native-planning-repair-20260912.md)

### 时间与仿真环境

- [24小时统计与完整时间轴](STATISTICS_24H_20260914.md)
- [问卷两份安排的比较时间：依据与建议](EVALUATION_HORIZON_RESEARCH_20260914.md)
- [十分钟精度修复（2026-09-14）](input-precision-fix-20260914.md)
- [问卷 → 地区环境 → 原 EB → 真人反馈](regional-environment/INTEGRATION.md)

### 页面与访问

- [免登录填写与本地图片验证码](public-access-local-captcha.md)
- [提交页面与反馈回执](submission-flow-v619.md)
- [连续时段端点与 EV 凌晨记录核对](timeline-run-endpoints-20260914.md)

### 历次审计

- [2026-09-11 完整链路复核](AUDIT_20260911.md)
- [数据采集交付修复记录 · 2026-09-12](DATA_COLLECTION_RELEASE_20260912.md)
- [上线前复验 · 2026-09-13](PRELAUNCH_AUDIT_20260913.md)
- [系统检查记录 · 2026-09-14](SYSTEM_AUDIT_20260914.md)
- [问卷系统三视角审计（2026-09-14）](three-perspective-audit-20260914.md)

部署历史：[服务器迁移](../deploy/VIRGINIA-MIGRATION-20260912.md)、[计算节点接入](../deploy/SCHOOL-COMPUTE.md)、[并发测试](../deploy/CONCURRENCY-20260912.md)。

`notion-review/` 保存早期交流材料，`examples/` 保存旧格式测试样例；当前数据格式见上面的公开试填样例。
