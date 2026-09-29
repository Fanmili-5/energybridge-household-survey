# 统一 A/B 工程试运行部署（2026-09-30）

入口：`https://47.85.194.154/joint-b/`，沿用现有管理员 Basic Auth。只开放合成家庭 `cityrole-0012` 的 10 轮工程页面。页面明确标记工程模式；答卷与问题分别写入独立服务的 SQLite，回执分为 `ANS-` 与 `ISS-`。记录固定为工程点击，`human_label_count=0`、`training_release=false`、`formal_export_eligible=false`。不得当作正式真人采集或模型训练样本。

部署包 SHA-256：`a0ad49b0115e59c245bdc04eb3e4a7992780bf339d2ef7053dbd65fd41324947`；`RELEASE.json` SHA-256：`6275598c6f5ff300e7df3620cc01fa824cfba8c03f2d825bd6a2615226c8c2ee`。包是私有构建产物，包含合成画像与计划，不提交 Git。服务器存放于 `/opt/energybridge-joint-b/releases/6275598c6f5ff300`，数据在 `/var/lib/energybridge-joint-b`，服务为 `energybridge-joint-b.service`，只监听 `127.0.0.1:18770`。Nginx 独立 `/joint-b` 路由，现有问卷服务及数据库不变。

上线检查：发布文件和案例哈希校验通过；新服务 health 报 `engineering_only`、10 轮；未授权 HTTPS 请求返回 401 和 Basic Auth；原 `/` 与 `/api/session` 仍返回 200；TLS 校验通过；Nginx 配置检查通过。独立服务测试覆盖会话、Origin/CSRF、答卷、问题、幂等和非法选项；页面 DOM 检查覆盖 2986 个案例。上线时独立数据库的写入数为 0。未用管理员凭据对外网授权页面执行浏览器提交，因此线上端到端授权提交仍需试填核对。

数据边界：当前 V5 来源只有 A 与锁定 B 的计划，B 的实际服务结果与物理结果尚未提供。`cityrole-0012` 没有绑定住宅几何，页面不生成其住宅剖面图。上线只是工程试运行，不代表正式采集可用。
