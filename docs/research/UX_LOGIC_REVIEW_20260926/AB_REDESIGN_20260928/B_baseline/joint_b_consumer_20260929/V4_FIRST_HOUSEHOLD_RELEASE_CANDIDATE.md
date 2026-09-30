# cityrole-0021 首户体验发布候选

- 本地体验：`http://127.0.0.1:8878/joint-b/`；已上线入口：`https://47.85.194.154/joint-b/`。
- 不可变包：`/private/tmp/joint-b-v4-0021-actual-release-final.tar.gz`，SHA-256 `c9eb940fa418bc622c8e58a652ab6cd30a07fd36e1adab3aa4d35fd18d2377be`。
- 解包目录：`/private/tmp/joint-b-v4-0021-actual-release-final`；`RELEASE.json` SHA-256 `c1d48e955932db17f903cc89497e1d313ff3860afbed2bae277057458baea05c`；`verify_unified_release.py` 已验证 10 轮、13 个包内文件。
- E 来源：`RELEASE_MANIFEST.json` SHA-256 `d032f90d57e7bd900157dad31b4a71808096b2d1699847db5628db57e8ac47ed`；`SITE_DATA.json` SHA-256 `dc940330ebff7a5b60c64265e3a229021ca2eec5a07b8bc1e43fd797791bf338`。消费者侧 10 轮 sidecar SHA-256 `43cfefdad345efb1e82cded243d9173c498d5a4f757b0f1d51919ecb89d5b19a`，只在本地审计，不进公开包。
- 公开 HTTP 白名单：`index.html`、`style.css`、`candidate.css`、`joint-view.css`、`plan-view.js`、`source-draft.js`、`household-view.js`、`joint-view.js`。页面扫描 `/Users/`、`/home/`、`.sql`、`.idf`、`.epw`、`private_research` 均为零命中。
- 内容核验：住宅图来自首户锁定 C IDF 的 13 个 floor surface，六区、100 m²，未补造家具或洗衣机。十轮各四台设备、A/B 日期和左右位置经页面验证。10 轮模型中均达购电削减目标；B 的电动车充电目标在第 1、2、3、5、7、10 轮出现未达日，A 无此缺口；这不等于无法出行。费用未知，室温未校准，目标时段削减不等于后续持续节电。
- 服务核验：`/joint-b/api/health` 返回 `experience_only`、10 cases；POST `/api/answers` 和 `/api/issues` 均为 405；没有创建数据目录。公开页无保存、下载或报告提交入口。

## 上线与回滚边界

根确认页面后，先按归档 SHA 核验上传包，在服务器新建独立 release 目录解包并运行 `verify_unified_release.py <release-dir> --sha256 c1d48e955932db17f903cc89497e1d313ff3860afbed2bae277057458baea05c`。保留当前 release、服务配置和 `/var/lib/energybridge-joint-b` 原样；将服务 `__RELEASE__` 指向新目录后重启并验 `/joint-b/api/health` 的 `experience_only`、首页 10 轮、两个 POST 405。回滚时将服务 `__RELEASE__` 指回原目录并重启，检查原首页与健康接口。不能把旧库记录当作本次体验数据。

## 2026-09-30 实际上线读回

- 已切换独立 `energybridge-joint-b.service` 至 `/opt/energybridge-joint-b/releases/c1d48e955932db17`，服务器对上传归档与 `RELEASE.json` 分别核哈希，release 验证通过。旧 release `/opt/energybridge-joint-b/releases/69c3d2f83a5ea689` 保留；切换前 unit 备份 `/root/energybridge-joint-b.service.before-c1d48e955932db17`，SHA-256 `23e49c47715b4b9e9b9441346671db53bcf729146bffaf3e4d5af789adc4f27d`。
- 线上 `https://47.85.194.154/joint-b/`、原 `/` 与 `/api/session` 均 HTTPS 200、TLS 校验成功。`/joint-b/api/health` 为 `{"cases":10,"mode":"experience_only"}`。首页没有 Set-Cookie；答卷和问题 POST 均为 405 且无 Set-Cookie。
- 在线 8 个公开文件与 `RELEASE.json` 的 SHA-256 全部一致；首页响应仅增加预期的 `window.EBExperienceOnly=true` 脚本，去掉该注入后与包内 `index.html` 逐字节一致。无原问卷服务或数据库变更。
