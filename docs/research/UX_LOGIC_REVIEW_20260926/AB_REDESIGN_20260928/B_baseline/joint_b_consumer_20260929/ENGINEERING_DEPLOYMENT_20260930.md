# 统一 A/B 工程试运行部署（2026-09-30）

入口：`https://47.85.194.154/joint-b/`，公开免登录，不再沿用管理员 Basic Auth；原问卷及其管理员入口不受此变更影响。只开放合成家庭 `cityrole-0012` 的 10 轮工程页面。页面明确标记工程模式；答卷与问题分别写入独立服务的 SQLite，回执分为 `ANS-` 与 `ISS-`。此工程服务没有模型调用，重复点击不会消耗模型 token；写入仍校验会话、来源和 CSRF。记录固定为工程点击，`human_label_count=0`、`training_release=false`、`formal_export_eligible=false`。不得当作正式真人采集或模型训练样本。

当前部署包 SHA-256：`ac65325eca24281ea0f6d8af5e57d975f0e220e284c498fb6289f2265c2b73cb`；`RELEASE.json` SHA-256：`69c3d2f83a5ea68998777a8e28e3ff33342a11f0dc7fa0f0b9b51b2d78c212e8`。包是私有构建产物，包含合成画像与计划，不提交 Git。服务器当前版本在 `/opt/energybridge-joint-b/releases/69c3d2f83a5ea689`，前一版本 `e8fdbe97823ca6d1` 保留供回退；数据在 `/var/lib/energybridge-joint-b`，服务为 `energybridge-joint-b.service`，只监听 `127.0.0.1:18770`。Nginx 独立 `/joint-b` 路由，现有问卷服务及数据库不变。

首次上线检查（前一版）：发布文件和案例哈希校验通过；服务 health 报 `engineering_only`、10 轮；免登录 HTTPS 页面和脚本资源均返回 200，没有登录挑战；缺失 Origin 的 POST 返回 403，合法会话下的无效内容返回 400；原 `/` 与 `/api/session` 仍返回 200；TLS 校验通过；Nginx 配置检查通过。独立服务测试覆盖会话、Origin/CSRF、答卷、问题、幂等和非法选项；页面 DOM 检查覆盖 2986 个案例。前一版曾在浏览器核对第 1 和第 9 个情境的可见内容与排版；当时独立数据库的答卷与问题写入数均为 0。

同日页面调整：目标说明压为一行，默认展示完整设备清单、生活需求、时间轴和已知安排变化；重复的 A/B 逐台文字明细收起供核对。线上第 1 个情境已读回这些区块，`joint-view.js` 与发布包逐字节哈希一致。发布时首次服务健康检查早于监听端口就绪，系统自动恢复旧版本；随后按就绪重试完成切换，当前服务 active。该次调整的 Git 提交为 `6afd446`。

数据边界：当前 V5 来源只有 A 与锁定 B 的计划，B 的实际服务结果与物理结果尚未提供。`cityrole-0012` 没有绑定住宅几何，页面不生成其住宅剖面图。上线只是工程试运行，不代表正式采集可用。
