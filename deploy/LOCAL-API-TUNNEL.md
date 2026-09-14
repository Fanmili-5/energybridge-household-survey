# 本地 API 反向隧道（临时测试）

> 部署历史记录，文中的路径和参数不代表当前配置。安装与更新请参阅[部署说明](../docs/DEPLOYMENT.md)。

2026-09-12 后续迁移：两个 Mac LaunchAgent 已改连新实例 `47.85.194.154`，API 隧道使用 `MacBook.pem` 和迁移目录的 `known_hosts`。学校仍经 Mac relay 调用现有模型；新网站本身只转发计算任务，没有沿用下述旧网站的 `30-local-api-tunnel.conf`。以下旧实例启动命令及系统配置作为历史记录，当前运维以 [迁移记录](VIRGINIA-MIGRATION-20260912.md) 为准。

阿里云 EB SDK → 云端 `127.0.0.1:18080` → SSH 加密隧道 → 本地 `127.0.0.1:18081` → `www.dmxapi.cn:443`。

`scripts/api_tunnel.py` 仅接受发往 `www.dmxapi.cn:443` 的 CONNECT。API 的 HTTPS/TLS 仍由 SDK 与 DMX 建立、校验证书；转发程序不解密、存储或记录密钥与请求正文。SSH 校验服务器主机密钥，两端端口均只绑定回环地址。脚本默认最多同时转发 **64 条 TCP 连接**，通过 `--max-connections` 可设置为 1–256，连接监听队列为 128。已运行的旧进程需要由部署流程重启后才使用新配置。

TCP 连接数包含 SDK 保留的空闲连接，**不等于同时付费调用模型的请求数**。实际模型请求仍由学校端 `EB_API_SLOTS` 单独限制。连接已满时新连接收到 503；旧连接关闭后名额释放。

2026-09-12 更新：问卷数据库和网站留在阿里云，EB＋EP 任务已迁到学校端；学校经另一条 SSH 转发接入本机同一个 API relay。完整路径与运行配置见 [SCHOOL-COMPUTE.md](SCHOOL-COMPUTE.md)。

## 当前运行

- 本地 Python：`/Users/fanmili/studytest/.venv/bin/python`
- 本地进程和日志：仓库 `artifacts/api_tunnel/relay.pid`、`relay.log`（Git 忽略）
- SSH 密钥仍使用原下载文件；API 密钥仍在云端原配置文件中，未复制到转发程序。
- 本地监督进程在 SSH 中断后每 5 秒尝试重新连接；现由 `org.energybridge.api-tunnel` LaunchAgent 在登录时自动维护。电脑必须保持开机、联网且不进入睡眠。
- 云端 systemd 附加配置：`/etc/systemd/system/energybridge.service.d/30-local-api-tunnel.conf`

```ini
[Service]
Environment="HTTPS_PROXY=http://127.0.0.1:18080"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
```

这项设置影响该服务及其子进程中遵循 HTTPS_PROXY 的 HTTPS 请求；转发服务只允许 DMX 目标。如以后增加其他外部 HTTPS 功能，应另行适配，不可假定这些请求也能通过。

## 启动命令

在仓库根目录执行（启动前先检查现有进程，避免重复启动）：

```sh
/Users/fanmili/studytest/.venv/bin/python -u scripts/api_tunnel.py \
  --host root@47.76.205.32 \
  --identity /Users/fanmili/Downloads/xuhao.pem \
  --known-hosts artifacts/api_tunnel/known_hosts \
  --pid-file artifacts/api_tunnel/relay.pid \
  --max-connections 64
```

上面是手动运行方式；目前已交给 LaunchAgent，请勿重复启动。暂停服务前先确认没有进行中的问卷任务，再通过 launchctl 停止对应服务。直接杀进程会被 KeepAlive 重新启动。停止隧道会使当前云端及学校端 API 路径不可用。

## 恢复直连

先验证云端直连已经恢复，再删除上述 systemd 附加配置，执行 `systemctl daemon-reload` 和 `systemctl restart energybridge`。重启前检查没有进行中的任务。原 DMX base URL、密钥文件均未修改。

## 已验证范围（2026-09-12）

- 本地 6 项测试覆盖：连接参数范围与回环监听、16 条连接同时保持并双向透传、容量耗尽返回 503 及关闭后复用、阻止其他目的地址/方法、双向透传二进制字节、上游连接失败返回 502。上游全部由本地 socketpair 替代，没有连接真实 API，也没有模型费用。
- 云端回环 18080 监听，无公网绑定。
- 云端经隧道认证查询 `/v1/models` 返回 200，约 3.95 秒，包含当前模型。
- 使用服务账号 `ebpilot`、现有 EB LLMClient 和 SDK 查询模型列表成功，约 3.55 秒。
- 重启后线上主页、会话接口均 200，生成开关开启，仍是 engineering 模式。
- 未调用模型生成；上述耗时不是完整 EB 规划耗时，也不是问卷端到端通过证明。
