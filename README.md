# EnergyBridge 真人家庭问卷

通过问卷保存真人家庭资料，将其中的运行信息接入 EnergyBridge（EB）和 EnergyPlus（EP），展示原安排与调整方案，再收集家庭的接受／拒绝、四项评分和原因，构造家庭角色模拟器的 SFT 候选数据。

**当前交付是研究原型，已有受邀演示部署，不等于正式采集验收完成。** 2026-09-11 已验证现有部署的 HTTPS、普通／管理员登录和 EP 工程链路；真实模型参与的端到端延迟、正式采集配置与公开分发防滥用仍需验收。仓库默认关闭方案生成；家庭资料可以独立保存。

## 主要流程

```mermaid
flowchart LR
    A[填写家庭资料] --> B[保存不可变问卷记录]
    B --> C[生成 EB 运行配置]
    C --> D[原安排与 EP 仿真]
    C --> E[VPP 事件下 EB 规划与 EP 仿真]
    D --> F[时间轴及结果对比]
    E --> F
    F --> G[真人决定 四项评分 原因]
    G --> H[SFT 候选导出]
    B --> I[完整家庭资料导出]
```

- 成员信息由一位填答者根据了解代填，不当作成员独立投票。
- 家庭成员、设备、日常习惯与态度原样留存；研究扩展资料不自动改变天气、建筑或设备数量。
- 当前 EP 使用统一研究住宅与天津典型夏季天气，不是对每个真实住宅的重建。
- 不使用模拟评分器代替真人标签；不强制归入原 EB 五类家庭。
- 尚未生成方案或未评价的家庭资料，也可独立导出。

## 仓库与上游

```text
realtime_pilot/                 问卷、服务、EB/EP 接入及测试
QUESTIONNAIRE_CODEBOOK.json     基础问卷定义
scripts/                       上游获取、离线测试和发布检查
upstream_2b17ae6/               单独获取的固定 EB 源码，不提交 Git
deploy/                       systemd、Nginx 与环境变量模板
docs/                         部署及数据说明
```

上游固定为 `2b17ae63e613da776c93e900f5dace50d63a88a8`，通过 `python scripts/bootstrap_upstream.py` 获取并验证。本仓库不内嵌上游源码；上游授权情况需单独核实，本仓库没有声明开源许可证。

## 本地验证

使用 Python 3.10+；持续集成使用 Python 3.11。Ubuntu 部署基线为 22.04、EnergyPlus 24.1。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/bootstrap_upstream.py
EPLUS_ROOT=/你的/EnergyPlus-24.1目录 EB_TEST_NATIVE_EP=1 .venv/bin/python scripts/test_offline.py
```

离线测试脚本阻止外部网络连接，使用工程答案及模型桩。部分真实 EP 测试需先安装 EP 24.1；跳过它们不能作为 EP 验收通过。

仅查看问卷、验证保存流程：

```bash
.venv/bin/python realtime_pilot/server.py --port 8766 --disable-planning --data-dir /tmp/energybridge-survey-test
```

此命令为工程模式，保存的答案不标记为真人训练标签。更换新测试目录可隔离历史数据。浏览器打开 `http://127.0.0.1:8766/`。

## 部署与数据

- [Ubuntu 部署步骤](docs/DEPLOYMENT.md)
- [资料保存、标签与导出](docs/DATA.md)
- [部署配置](deploy/service.env.example)

50 人同时填写与保存，不等于 50 个 EP 仿真同时运行。2 vCPU / 4 GB 可先设置 2 个任务工作线程、1 个 EP 计算槽，按实测再决定是否升至 2 个 EP 槽；真实模型等待时间、排队时间、内存和磁盘都需要观察。
# 演示数据备份

`scripts/scheduled_backup.py --data-dir <任务目录> --backup-dir <备份目录> --keep 24`
使用 SQLite 一致性快照保存问卷、任务和评分，每次成功后保留最近 24 份。
它不调用模型，也不复制 EP 原始轨迹；原始轨迹仍保留在任务目录。
部署时可用 systemd timer 每小时执行。备份目录应仅服务账号可读写。
同机快照用于误操作恢复，不能替代服务器故障时所需的异地备份。

## 管理员测试入口

在 HTTPS 反向代理添加独立管理员登录后，后端可配置 `--admin-user <管理员用户名>`
（部署脚本对应 `EB_ADMIN_USER`），通过 `/admin` 查看运行状态并进入问卷测试。
Nginx 必须认证用户并用 `$remote_user` 覆盖 `X-EB-Authenticated-User`；
不能信任参与者发来的角色字段或身份请求头。后端仍只监听回环地址。

管理员免受个人次数和参与者每日任务额度限制，但仍受队列容量、并发、
超时、同一管理员单任务及幂等保护约束。管理员任务不消耗参与者每日任务额度，
其问卷与任务始终标为工程测试，即使服务切换为真人采集模式也不会自动变为真人样本。
管理员点击生成仍会产生模型费用。凭据只保存在服务器或被 Git 忽略的本地文件，
不能随问卷链接分发。浏览器已记住普通账号时，可用无痕窗口登录管理员账号。

人机验证尚未启用。应接入验证服务，后端验证通过后才允许创建新计算任务；
不能用前端勾选框代替服务端校验。
