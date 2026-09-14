# 部署与维护

网站负责问卷、队列、结果展示和数据保存。EB 与 EnergyPlus 可以在同一台机器运行，也可以通过私有计算服务运行。

以下单机步骤对应仓库配置模板，路径为 `/opt/energybridge`，不代表现有演示站的实际安装路径。密钥保存在 `/etc/energybridge`，数据保存在 `/var/lib/energybridge`。

## 单机安装

环境：Ubuntu 22.04、Python 3.10+、EnergyPlus 24.1 Linux x86_64。

```bash
sudo apt-get update
sudo apt-get install -y python3-venv git curl nginx certbot
sudo useradd --system --home-dir /var/lib/energybridge --shell /usr/sbin/nologin energybridge
sudo install -d -o energybridge -g energybridge -m 0750 /var/lib/energybridge/jobs /var/lib/energybridge/limits
sudo install -d -o root -g energybridge -m 0750 /etc/energybridge
sudo git clone https://github.com/Fanmili-5/energybridge-household-survey.git /opt/energybridge
cd /opt/energybridge
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.txt
sudo .venv/bin/python scripts/bootstrap_upstream.py
sudo .venv/bin/python scripts/bootstrap_resources.py
sudo bash scripts/install_energyplus_linux.sh /opt/EnergyPlus-24-1-0
```

账号或目录已存在时跳过创建。源码对服务账号只读，数据目录允许写入。

## 配置与启动

```bash
sudo install -o root -g energybridge -m 0640 deploy/service.env.example /etc/energybridge/service.env
sudo install -o root -g energybridge -m 0640 deploy/model.env.example /etc/energybridge/model.env
sudo install -m 0644 deploy/energybridge.service /etc/systemd/system/energybridge.service
```

编辑 `service.env` 中的 `EB_PUBLIC_ORIGIN`，填写网站 HTTPS 地址。首次测试保持 `EB_PLANNING_ENABLED=0`；若使用工程答卷，将 `EB_HUMAN_PILOT=0` 并使用独立测试数据目录。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now energybridge
sudo systemctl status energybridge
```

Nginx 代理到 `127.0.0.1:8767`。按 [nginx.conf.example](../deploy/nginx.conf.example) 配置实际域名和证书路径，通过 `nginx -t` 后启用。对外开放 80/443，应用和计算服务端口只在内网或回环地址监听。证书签发与续期需按所用域名或 IP 证书方案配置并验证。

先检查保存答卷、刷新恢复和查看回执。随后在 `model.env` 配置 `USE_LLM=true`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`，再将 `EB_PLANNING_ENABLED=1` 并重启。用户生成方案会产生模型调用费用。

当前直接运行 `server.py` 时可使用 `--local-captcha` 启用本地图片验证码。现有 `start.sh` 模板没有传入此参数，部署时需显式添加。参与者入口无需账号，管理员认证由 Nginx 单独配置，见[访问配置](public-access-local-captcha.md)。

## 队列与远程计算

| 参数 | 作用 |
|---|---|
| `EB_WORKERS` | 网站同时处理的计算任务数 |
| `EB_EP_SLOTS` | 同时运行的 EnergyPlus 进程数 |
| `EB_API_SLOTS` | 同时发起的模型请求数 |
| `EB_MAX_PENDING` | 未结束任务上限 |
| `EB_MAX_SESSION_JOBS` | 单浏览器会话生成次数上限 |
| `EB_MAX_DAILY_JOBS` | 每日新计算任务上限 |
| `EB_MAX_SESSION_INTAKES` / `EB_MAX_DAILY_INTAKES` | 家庭资料提交次数上限 |
| `EB_MAX_QUEUE_WAIT` | 等待开始计算的最长时间 |
| `EB_JOB_TIMEOUT` | 网站工作进程总时限 |

参数默认值见 [service.env.example](../deploy/service.env.example)。填写人数和执行并发是两回事；队列可接纳的任务数也不代表都能立即完成。

远程模式使用 [compute.service.example](../deploy/compute.service.example) 启动计算服务，通过 SSH 隧道转发到网站节点的回环地址。网站配置 `EB_COMPUTE_URL` 和 `EB_COMPUTE_TOKEN_FILE`。两端代码及资源哈希必须一致，连接失败不会自动改为本地重跑。

[service.remote-2g.env.example](../deploy/service.remote-2g.env.example) 提供远程模式参数示例。当前 `start.sh` 的启动检查仍要求本地 EP 和模型配置，不能仅设置计算地址就直接作为纯转发节点使用；现有演示站使用单独的 systemd 启动命令。

超时应满足：计算进程时限 < `EB_REMOTE_TIMEOUT` < `EB_JOB_TIMEOUT`。例如 1200 < 1320 < 1440 秒。根据实际运行时间调整，不能把模板参数当成性能保证。

## 更新与备份

源码目录可以从 GitHub 更新，但数据、密钥和模型配置放在目录外。更新前等待在途任务结束并备份，更新后按[发布检查](../deploy/RELEASE-CHECK.md)核对两端版本及私有计算连接。

```bash
.venv/bin/python scripts/scheduled_backup.py \
  --data-dir /var/lib/energybridge/jobs \
  --backup-dir /var/lib/energybridge/backups \
  --keep 24
```

定时快照包含数据库和案例文档，不复制 EP 轨迹；需要备份已完成案例的运行附件时，使用 `realtime_pilot/backup_backend.py`。备份完成后核对清单，并在独立目录测试恢复。跨机器保存备份可避免主机或磁盘故障同时损坏原始数据与备份。

清理旧代码目录时，检查 systemd 主服务、备份任务和定时器是否仍引用旧路径。历史案例使用的资源版本和数据库备份不属于可随代码一起删除的旧版本。
