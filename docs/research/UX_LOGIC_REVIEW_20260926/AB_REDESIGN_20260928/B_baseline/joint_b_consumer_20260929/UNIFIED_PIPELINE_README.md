# 统一 A/B 本地消费者

入口固定为 `unified_pipeline.py`。批次 manifest 指定来源文件、SHA、期望户数/题数、proposal schema 和来源版本；独立 consumer policy 只绑定可读取的来源版本。消费者输出同一 `eb.joint_b.consumer.v2`：家庭/住房/全设备、成员态度、轮次日期与 VPP、A/B 完整计划、逐条命令、可选物理证据、独立审计。页面固定使用 `template.html`、`unified_household_view.js`、`unified_joint_view.js` 和同一套样式/时间轴脚本，输入批次不修改页面代码。

在此目录运行完整历史 revision2 批次：

```sh
python3 unified_pipeline.py --manifest unified_revision2_manifest.json --policy unified_consumer_policy.json --out-root unified_preview/revision2_full
```

只重建指定家庭时加 `--roles cityrole-0012`；输出索引保留其他同 manifest 家庭，逐文件记录 SHA 和变更。旧 11 例改用 `unified_legacy11_manifest.json`，隔离的富设备工程夹具改用 `unified_rich_fixture_manifest.json`。后端直接提供 v2 case 时使用 `unified_case_json` adapter 和带来源哈希的发布回执，示例为 `unified_direct_fixture_manifest.json`。旧格式转换在 `legacy_case_adapter.py`，不修改原问卷或旧 `preview_page/`。

正式发布/暂缓由生产端负责。消费者只校验后端发布回执的 schema、来源版本、来源文件 SHA、角色状态类型及完整性，原样写入审计与索引；没有回执时状态为 `null`，不会自行补成通过。旧单类题可作为历史输入展示，不由前端按研究规则筛题。先前误放在消费者内的类别计数与配额判定已撤回；当时的代码和测试另存 `RETRACTED_*` 历史材料，不在活动构建或测试路径。

物理 sidecar 可增量绑定到具体 case，状态为 `not_computed`、`partial`、`complete`、`failed`。每个带数值通道有范围、单位、A/B 独立状态及证据 SHA；真实 sidecar 需匹配 case SHA、画像/A/B 计划/命令/VPP SHA，并固定原始证据文件 SHA。工程夹具 sidecar 仅可用于工程夹具批次。未计算值保持 `null`，不会补成零或跨源复用旧 SQL。模型输入仍只来自页面 23 个可见文本字段；来源、分组和物理审计留在导出审计中。

2026-09-30 页面复核：主时间轴聚焦事件当天，跨午夜任务延伸到次日；前一日和更晚的完整源计划保留在审计，不挤进主视图。计划区只列当天有安排的设备；未持有或未安装的设备从家庭卡隐藏，已配备但本轮未运行的设备仍留在家庭卡。页面不再允许参与者临时交换 A/B 位置。历史 revision2 来源的合成问卷提供通常开始与通常最晚完成时刻时，页面逐项对照 A/B；它们不是硬性可执行边界，缺失时明确写未知。旧 0012 批次没有绑定住宅几何，因此不画图；隔离的富设备工程夹具展示平面布局，不能当作 0012 的图或正式来源。

回答区按旧问卷改为一题明确的“同意采用 B／不同意采用 B”；移除“信息不足”决定选项。四项 1–5 分滑杆（整体、舒适、用电与费用、响应安排）可填一位小数；依据不足的分数可留空，导出为 `null`，并在唯一的必填原因中说明。统一页导出为 `eb.joint_b.local_test_export.v5`，状态仍是本地工程点击，不是人类反馈；正式采集端尚未接入这一新字段版本。

页面恢复旧版悬浮“报告问题”入口，问题类别和描述独立于偏好反馈。静态预览只下载 `eb.joint_b.local_issue.v1` JSON，明确标记 `local_download_not_submitted`。独立工程服务 `unified_live_server.py` 在公开的 `/joint-b` 路由提供实际答卷/问题写入与回执；写入仍检查会话、来源和 CSRF，存储独立于现有问卷，答卷固定为工程来源。服务只接受一户十轮的精确构建包，不能作为正式真人采集、邀请分配或合法历史协议的替代。工程包通过 `package_unified_live.py` 从已构建的私有页面生成，包内画像和情境不得提交公共 Git。

已实跑同一入口：旧 11 例（4 户）、历史 revision2 2970 轮（297 户）、隔离工程夹具四种物理状态及直接 v2 夹具。`test_unified_pages.js` 检查 2986 个页面案例的 DOM、事件当天计划/完整来源审计/命令展示、导出白名单、跨午夜与新增空调；各批静态文件 SHA 一致。`test_unified_release_binding.py` 验证历史单类输入可显示、后端 `held/published` 原样透传、无回执不补通过，以及错误来源哈希和非法单位被拒。错误 case SHA 的物理 sidecar 被拒；同一来源选择性重建 0012 的 10 轮时页面文件变更数为 0。DOM 检查不等于浏览器视觉检查。历史批次与工程夹具不计入新 3000；线上工程入口的范围和验证结果见 `ENGINEERING_DEPLOYMENT_20260930.md`。
