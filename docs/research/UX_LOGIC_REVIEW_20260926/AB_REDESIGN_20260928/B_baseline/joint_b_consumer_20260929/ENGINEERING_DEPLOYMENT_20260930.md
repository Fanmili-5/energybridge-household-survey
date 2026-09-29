# 统一 A/B 工程试运行部署（2026-09-30）

入口：`https://47.85.194.154/joint-b/`，公开免登录，不再沿用管理员 Basic Auth；原问卷及其管理员入口不受此变更影响。只开放合成家庭 `cityrole-0012` 的 10 轮工程页面。页面明确标记工程模式；答卷与问题分别写入独立服务的 SQLite，回执分为 `ANS-` 与 `ISS-`。此工程服务没有模型调用，重复点击不会消耗模型 token；写入仍校验会话、来源和 CSRF。记录固定为工程点击，`human_label_count=0`、`training_release=false`、`formal_export_eligible=false`。不得当作正式真人采集或模型训练样本。

当前部署包 SHA-256：`d607a2a29e77dae2161d7e8d8429ef2f2f80c0978594c6893ff9418ea539200d`；`RELEASE.json` SHA-256：`86d53d737b482cc3475f5110634c5518442a13ff96e77f53e6c3c72cb7b16871`。包是私有构建产物，包含合成画像与计划，不提交 Git。服务器当前版本在 `/opt/energybridge-joint-b/releases/86d53d737b482cc3`，前一版本 `6275598c6f5ff300` 保留供回退；数据在 `/var/lib/energybridge-joint-b`，服务为 `energybridge-joint-b.service`，只监听 `127.0.0.1:18770`。Nginx 独立 `/joint-b` 路由，现有问卷服务及数据库不变。

上线检查：发布文件和案例哈希校验通过；新服务 health 报 `engineering_only`、10 轮；免登录 HTTPS 页面和脚本资源均返回 200，没有登录挑战；缺失 Origin 的 POST 返回 403，合法会话下的无效内容返回 400；原 `/` 与 `/api/session` 仍返回 200；TLS 校验通过；Nginx 配置检查通过。独立服务测试覆盖会话、Origin/CSRF、答卷、问题、幂等和非法选项；页面 DOM 检查覆盖 2986 个案例。改为公开入口后独立数据库的写入数为 0；尚未在公开入口试填一条有效答卷。

数据边界：当前 V5 来源只有 A 与锁定 B 的计划，B 的实际服务结果与物理结果尚未提供。`cityrole-0012` 没有绑定住宅几何，页面不生成其住宅剖面图。上线只是工程试运行，不代表正式采集可用。
