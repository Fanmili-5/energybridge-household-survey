# Ubuntu 22.04 部署

约定源码 `/opt/energybridge`，虚拟环境 `/opt/energybridge/.venv`，持久目录 `/var/lib/energybridge`，外部配置 `/etc/energybridge`。不要把真实问卷、日志、数据库、密钥或模型配置写入源码仓库。

## 1. 安装与准备

将本仓库检出到 `/opt/energybridge` 后，安装基础工具与 Python 依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv git curl nginx certbot
sudo useradd --system --home-dir /var/lib/energybridge --shell /usr/sbin/nologin energybridge
sudo install -d -o energybridge -g energybridge -m 0750 /var/lib/energybridge/jobs /var/lib/energybridge/limits
sudo install -d -o root -g energybridge -m 0750 /etc/energybridge
sudo install -d -o root -g root -m 0755 /var/lib/energybridge/acme
cd /opt/energybridge
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.txt
sudo .venv/bin/python scripts/bootstrap_upstream.py
```

账号已存在时不用重复创建。源码保持服务账号只读；`/var/lib/energybridge` 才是服务写入位置。

EnergyPlus 从其官方发布渠道安装 **24.1 Linux x86_64** 到 `/opt/EnergyPlus-24-1-0`，检查可执行文件和 Python API 均存在：

```bash
sudo bash scripts/install_energyplus_linux.sh /opt/EnergyPlus-24-1-0
/opt/EnergyPlus-24-1-0/energyplus --version
test -d /opt/EnergyPlus-24-1-0/pyenergyplus
```

以开发账号在可写的检出目录执行 `EPLUS_ROOT=/opt/EnergyPlus-24-1-0 EB_TEST_NATIVE_EP=1 .venv/bin/python scripts/test_offline.py` 完成工程检查（不要让只读服务账号写测试输出）。此时不需要真实模型密钥，不应启用付费模型。

## 2. 配置域名与 HTTPS

先将自己的域名 A 记录指向服务器；仅在配置 IPv6 后才添加 AAAA。云安全组开放网站的 80、443，SSH 22 只开放给运维来源；**不用对公网开放 8767**。

将 `survey.example.org` 全部替换为实际域名。证书尚不存在时，不要直接启用包含不存在证书路径的 HTTPS 模板。

首次发证可临时停用 Nginx 后使用 standalone（服务器已有其他网站时，应改用与现有配置兼容的 webroot 验证）：

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d survey.example.org
```

复制 `deploy/nginx.conf.example` 到 `/etc/nginx/sites-available/energybridge`，替换域名和证书目录，再启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/energybridge /etc/nginx/sites-enabled/energybridge
sudo nginx -t
sudo systemctl start nginx
```

模板位于 Nginx 的 `http` 上下文，不能放进另一个 `server` 块。80 端口重定向 HTTPS，并保留 ACME webroot。若首次使用 standalone，后续需为证书配置 Nginx 配套的 webroot 续期或停启钩子；用 `certbot renew --dry-run` 验证续期方式，并确保续期后 reload Nginx。此步骤尚未自动配置；不能仅因为首次证书有效就认为续期已完成。

## 3. 先启动“只采集、不计算”模式

```bash
sudo install -o root -g energybridge -m 0640 deploy/service.env.example /etc/energybridge/service.env
sudo install -o root -g energybridge -m 0640 deploy/model.env.example /etc/energybridge/model.env
```

编辑 `service.env` 中的 `EB_PUBLIC_ORIGIN`，保持 `EB_PLANNING_ENABLED=0`。`model.env` 此时可保持空模板，不需填写任何密钥。

```bash
sudo install -m 0644 deploy/energybridge.service /etc/systemd/system/energybridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now energybridge
sudo systemctl status energybridge
```

规划关闭仅停止计算，不会把问卷变成只读页面：独立资料保存与恢复继续可用。

访问 HTTPS 地址，验证研究同意、保存回执、刷新恢复，以及数据库中独立家庭资料记录。用隔离工程目录做功能测试，避免把工程答案写进真人采集目录。真人公开模式只接受 HTTPS origin；本地无公开 origin 的测试不受影响。

## 4. 经过确认再开放规划

仅在准备做真实端到端测试时，手工编辑 `/etc/energybridge/model.env`：填入自己的服务地址、模型名与密钥，并设 `USE_LLM=true`。不要上传该文件、终端打印密钥或复制到上游目录。

把 `service.env` 的 `EB_PLANNING_ENABLED` 改为 `1` 后重启服务。启动脚本只做本地配置和 EP 版本检查，不在启动时试调用模型；**开启后用户生成方案会消耗模型 API**。

初始建议：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `EB_WORKERS` | 2 | 同时处理的计算任务数 |
| `EB_EP_SLOTS` | 1 | 同时进行 EP 计算的槽数 |
| `EB_API_SLOTS` | 1 | 同时进行模型请求的槽数 |
| `EB_MAX_DAILY_API_CALLS` | 0 | UTC 自然日逻辑模型调用硬上限；0 表示关闭。SDK 隐藏重试已关闭，EB 显式重试仍计在同一次逻辑调用内 |
| `EB_JOB_TIMEOUT` | 300秒 | 每个工作进程总时限，包含资源等待；远程计算时必须大于 `EB_REMOTE_TIMEOUT` |
| `EB_MAX_PENDING` | 100 | 全部未结束计算任务上限 |
| `EB_MAX_SESSION_JOBS` | 3 | 单浏览器会话累计计算次数，排队过期不占次数 |
| `EB_MAX_DAILY_JOBS` | 250 | UTC 自然日全局新任务上限，失败也计数 |
| `EB_MAX_SESSION_INTAKES` | 5 | 单浏览器会话累计家庭资料提交上限；幂等重试不重复计数 |
| `EB_MAX_DAILY_INTAKES` | 2000 | UTC 自然日全局新家庭资料上限，用于保护磁盘和数据库 |
| `EB_MAX_QUEUE_WAIT` | 120秒 | 等待开始计算的上限；预计到达上限则暂不接纳新计算，已接收任务到期则结束排队 |
| `EB_ESTIMATED_JOB_SECONDS` | 60秒 | 无近期数据时的初始估算，未经实测，不是完成承诺 |

家庭资料与计算任务分别限额；原请求的幂等重试不会重复计数。按实际活动规模调整，额度不是金额预算，也不代表这些任务能及时完成。

页面分别显示排队与计算时间。开始时间估算使用最近20个同采集模式配对任务的运行耗时80分位数和工作线程占用情况；工程任务不会用于估算真人任务。资源争用和模型响应变化仍会使估算偏差，等待截止时间则持久保存在任务中，重启不会刷新。排队过期后保留原资料、请求和案例状态，只在参与者手动重试时创建新案例，不自动重调模型。过期案例仍计入全局日额度。

`deploy/load_test_backend.py` 专用于全量排队、重启与 EP 容量测试，会显式关闭等待时长限制（`max_queue_wait=0`）。它不能用来证明50个用户都能在两分钟内开始或完成仿真。生产默认同时保留计数准入和等待准入。

当前这种“2 vCPU / 2 GiB 网站节点 + 私有远端计算服务”的部署使用
`deploy/service.remote-2g.env.example`：网站 worker 16、在途任务 128、单会话
2 次、UTC 每日 250 个新任务、最长等待开始 2400 秒，首次按每任务 300 秒估算。
Nginx 允许同一公网 IP 瞬时提交 150 个生成请求，以免校园网或家庭网 NAT
误伤真实参与者；应用层的单会话额度、全局日额度与在途上限仍是最终准入边界。
这组设置保证突发请求先可靠保存并排队，并不承诺 128 个任务同时执行或在固定时间内完成。
远程计算的超时必须从内向外递增：计算节点进程上限 < `EB_REMOTE_TIMEOUT` < `EB_JOB_TIMEOUT`。当前远程模板采用 1200 < 1320 < 1440 秒，避免网站进程先结束而收不到计算结果或取消回执。

先验证一个真实模型案例的家庭输入、原安排、VPP、EB 决策、两份 EP 输出及最终评分保存，再逐步增加少量并行请求，测量端到端时间及峰值内存。工程桩完成的50人并发测试不能替代这一步。

## 5. 备份、恢复与更新

用一致性备份脚本，不能只复制正在使用的 SQLite 主文件而漏掉 WAL：

```bash
sudo install -d -o energybridge -g energybridge -m 0700 /var/lib/energybridge/backups
sudo -u energybridge /opt/energybridge/.venv/bin/python /opt/energybridge/realtime_pilot/backup_backend.py --data-dir /var/lib/energybridge/jobs --output /var/lib/energybridge/backups/survey-backup.tar.gz
```

输出文件必须是新名称。备份包含数据库（包括没有任务的家庭资料）及已完成的仿真痕迹。将备份复制到受控的其他存储，定期检查恢复；同一台服务器上的备份不能防止整盘故障。留意备份和 EP 痕迹占用，设置与研究需求一致的保留周期。

恢复时先停止服务，将归档解压到**新的空目录**，校验清单与 SQLite 完整性，修正为 `energybridge` 所有，再修改 `EB_DATA_DIR` 指向该目录。第一次恢复保持 `EB_PLANNING_ENABLED=0`，先核对家庭记录、案例与反馈数量；开放计算可能重新执行中断任务并再次发生模型费用。

升级前备份，替换源码、安装依赖、运行离线测试后重启。持久目录与外部模型配置不随源码替换。不要混用不同问卷版本的字段含义或删改旧记录。

服务器常驻内存仅保存任务摘要和未结束任务；已完成结果在读取该案例时才从 SQLite 加载，不长期缓存。会话列表、轮询和家庭保存回执均使用轻量查询。启动恢复只重新导出未结束任务；历史 JSON 镜像以 SQLite 为准，可通过备份/导出重新生成。备份逐条处理文档并分块计算校验值，避免一次载入全部仿真结果。

## 交付边界

配置模板尚需在目标 Linux 上运行 `nginx -t` 和 `systemd-analyze verify`。域名解析、证书、模型连通性、实际并发性能和备份外存都不是仅提交本仓库即可完成的事项。
